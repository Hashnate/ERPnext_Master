# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from dataclasses import dataclass

import frappe
from frappe import _
from frappe.utils import flt

from erpnext import get_region
from erpnext.controllers.taxes_and_totals import get_itemised_tax
from erpnext.regional.sri_lanka.constants import COUNTRY_NAME


@dataclass(frozen=True)
class VATReturnSummary:
	standard_rated_sales: float
	output_vat: float
	zero_rated_sales: float
	exempt_sales: float
	sales_credit_notes: float
	output_vat_adjustments: float
	standard_rated_purchases: float
	input_vat_claimable: float
	exempt_purchases: float
	purchase_debit_notes: float
	input_vat_adjustments: float
	net_vat_payable: float


def classify_vat_supply(
	is_zero_rated: bool = False,
	is_exempt: bool = False,
	is_export: bool = False,
	tax_rate: float = 0.0,
) -> str:
	"""Classify an invoice line into a Sri Lanka VAT supply category."""
	if is_exempt:
		return "Exempt"
	if is_zero_rated or is_export:
		return "Zero Rated"
	if flt(tax_rate) > 0:
		return "Standard Rated"
	return "Zero Rated"


def compute_vat_return_summary(
	sales_rows: list[dict],
	purchase_rows: list[dict],
	precision: int = 2,
) -> VATReturnSummary:
	"""Aggregate Sales and Purchase VAT lines into an IRD VAT Return summary."""
	std_sales = 0.0
	output_vat = 0.0
	zero_sales = 0.0
	exempt_sales = 0.0
	sales_credit_notes = 0.0
	output_vat_adj = 0.0

	for row in sales_rows:
		net = flt(row.get("net_amount"))
		vat = flt(row.get("vat_amount"))
		category = row.get("supply_category") or classify_vat_supply(
			is_zero_rated=bool(row.get("is_zero_rated")),
			is_exempt=bool(row.get("is_exempt")),
			is_export=bool(row.get("is_export")),
			tax_rate=flt(row.get("tax_rate")) or (1.0 if abs(vat) > 0 else 0.0),
		)
		if row.get("is_return"):
			sales_credit_notes += abs(net)
			output_vat_adj -= abs(vat)
			continue

		if category == "Exempt":
			exempt_sales += net
		elif category == "Zero Rated":
			zero_sales += net
		else:
			std_sales += net
			output_vat += vat

	std_purchases = 0.0
	input_vat = 0.0
	exempt_purchases = 0.0
	purchase_debit_notes = 0.0
	input_vat_adj = 0.0

	for row in purchase_rows:
		net = flt(row.get("net_amount"))
		vat = flt(row.get("vat_amount"))
		category = row.get("supply_category") or classify_vat_supply(
			is_zero_rated=bool(row.get("is_zero_rated")),
			is_exempt=bool(row.get("is_exempt")),
			tax_rate=flt(row.get("tax_rate")) or (1.0 if abs(vat) > 0 else 0.0),
		)
		if row.get("is_return"):
			purchase_debit_notes += abs(net)
			input_vat_adj -= abs(vat)
			continue

		if category == "Exempt":
			exempt_purchases += net
		else:
			std_purchases += net
			input_vat += vat

	net_output_vat = output_vat + output_vat_adj
	net_input_vat = input_vat + input_vat_adj
	net_vat_payable = flt(net_output_vat - net_input_vat, precision)

	return VATReturnSummary(
		standard_rated_sales=flt(std_sales, precision),
		output_vat=flt(output_vat, precision),
		zero_rated_sales=flt(zero_sales, precision),
		exempt_sales=flt(exempt_sales, precision),
		sales_credit_notes=flt(sales_credit_notes, precision),
		output_vat_adjustments=flt(output_vat_adj, precision),
		standard_rated_purchases=flt(std_purchases, precision),
		input_vat_claimable=flt(input_vat, precision),
		exempt_purchases=flt(exempt_purchases, precision),
		purchase_debit_notes=flt(purchase_debit_notes, precision),
		input_vat_adjustments=flt(input_vat_adj, precision),
		net_vat_payable=net_vat_payable,
	)


def is_export_invoice(doc) -> bool:
	"""Return True when a Sales Invoice supplies goods/services outside Sri Lanka."""
	if getattr(doc, "doctype", None) not in ("Sales Invoice", "POS Invoice"):
		return False

	address_name = getattr(doc, "customer_address", None)
	if not address_name:
		return False

	company_country = frappe.get_cached_value("Company", doc.company, "country")
	customer_country = frappe.db.get_value("Address", address_name, "country")
	return bool(customer_country and company_country and customer_country != company_country)


def get_sri_lanka_vat_accounts(company: str) -> dict[str, dict]:
	"""Fetch configured Sri Lanka VAT Accounts keyed by Account name."""
	rows = frappe.get_all(
		"Sri Lanka VAT Account",
		filters={"parent": company},
		fields=["account", "vat_type"],
	)
	return {row.account: row for row in rows}


def update_itemised_tax_data(doc):
	"""Populate item-level VAT rate, VAT amount, and supply flags for Sri Lanka documents."""
	if not getattr(doc, "items", None):
		return

	meta = frappe.get_meta(doc.items[0].doctype)
	if not meta.has_field("tax_rate"):
		return

	itemised_tax = get_itemised_tax(doc)
	export_flag = is_export_invoice(doc)

	for row in doc.items:
		tax_rate = 0.0
		tax_amount = 0.0
		item_code = row.item_code or row.item_name

		if itemised_tax.get(item_code):
			for tax in itemised_tax[item_code].values():
				rate = flt(tax.get("tax_rate", 0), row.precision("tax_rate"))
				tax_amount += flt((row.net_amount * rate) / 100, row.precision("tax_amount"))
				tax_rate += rate

		if row.item_code and not row.get("is_exempt"):
			row.is_exempt = frappe.get_cached_value("Item", row.item_code, "is_exempt") or 0

		if not row.get("is_exempt") and (not tax_rate or row.get("is_zero_rated")):
			item_zero = (
				frappe.get_cached_value("Item", row.item_code, "is_zero_rated") if row.item_code else 0
			)
			row.is_zero_rated = int(bool(export_flag or item_zero))

		row.tax_rate = flt(tax_rate, row.precision("tax_rate"))
		row.tax_amount = flt(tax_amount, row.precision("tax_amount"))
		row.total_amount = flt(row.net_amount + row.tax_amount, row.precision("total_amount"))


def validate_sri_lanka_invoice(doc, method=None):
	"""Validate Sri Lanka VAT rules on Sales and Purchase Invoices."""
	if not doc.company or get_region(doc.company) != COUNTRY_NAME:
		return

	_validate_item_vat_flags(doc)
	_validate_tax_invoice_registration(doc)


def _validate_item_vat_flags(doc):
	for row in doc.get("items") or []:
		if row.get("is_exempt") and row.get("is_zero_rated"):
			frappe.throw(
				_("Row #{0}: Item {1} cannot be both Exempt and Zero Rated.").format(
					row.idx, frappe.bold(row.item_code or row.item_name)
				)
			)

		if (row.get("is_exempt") or row.get("is_zero_rated")) and flt(row.get("tax_rate")) > 0:
			label = _("Exempt") if row.get("is_exempt") else _("Zero Rated")
			frappe.throw(
				_("Row #{0}: {1} item {2} cannot carry a positive VAT rate ({3}%).").format(
					row.idx,
					label,
					frappe.bold(row.item_code or row.item_name),
					flt(row.get("tax_rate")),
				)
			)


def _validate_tax_invoice_registration(doc):
	if doc.doctype != "Sales Invoice":
		return

	vat_invoice_type = doc.get("vat_invoice_type")
	if vat_invoice_type != "Tax Invoice":
		return

	company_vat = doc.get("company_vat_reg_no") or frappe.get_cached_value("Company", doc.company, "tax_id")
	if not company_vat:
		frappe.throw(
			_("Company {0} must have a VAT Registration / TIN Number to issue a Tax Invoice.").format(
				frappe.bold(doc.company)
			)
		)

	customer_vat = doc.get("customer_vat_reg_no") or doc.get("tax_id")
	if not customer_vat and not is_export_invoice(doc):
		frappe.throw(
			_(
				"Customer VAT Registration / TIN Number is required for a Sri Lanka Tax Invoice. "
				"Use 'Simplified Tax Invoice' for unregistered customers."
			)
		)
