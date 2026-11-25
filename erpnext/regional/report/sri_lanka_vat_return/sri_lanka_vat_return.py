# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt

from erpnext.regional.sri_lanka.utils import validate_sri_lanka_report_filters
from erpnext.regional.sri_lanka.vat import compute_vat_return_summary, get_sri_lanka_vat_accounts


def execute(filters=None):
	filters = validate_sri_lanka_report_filters(filters, _("Sri Lanka VAT Return"))

	columns = get_columns()
	data = get_data(filters)
	currency = frappe.get_cached_value("Company", filters.company, "default_currency") or "LKR"
	for row in data:
		row["currency"] = currency
	return columns, data


def get_columns():
	return [
		{"fieldname": "box", "label": _("Box"), "fieldtype": "Data", "width": 70},
		{"fieldname": "description", "label": _("Description"), "fieldtype": "Data", "width": 380},
		{
			"fieldname": "value",
			"label": _("Supply / Value"),
			"fieldtype": "Currency",
			"options": "currency",
			"width": 160,
		},
		{
			"fieldname": "vat_amount",
			"label": _("VAT Amount"),
			"fieldtype": "Currency",
			"options": "currency",
			"width": 160,
		},
	]


def _fetch_invoice_rows(doctype: str, filters: frappe._dict, vat_accounts: dict) -> list[dict]:
	invoices = frappe.get_all(
		doctype,
		filters={
			"company": filters.company,
			"docstatus": 1,
			"posting_date": ["between", [filters.from_date, filters.to_date]],
		},
		fields=["name", "is_return"],
	)
	if not invoices:
		return []

	invoice_map = {inv.name: inv for inv in invoices}
	tax_table = "Sales Taxes and Charges" if doctype == "Sales Invoice" else "Purchase Taxes and Charges"

	tax_by_invoice: dict[str, float] = {}
	if vat_accounts:
		taxes = frappe.get_all(
			tax_table,
			filters={
				"parent": ["in", list(invoice_map)],
				"account_head": ["in", list(vat_accounts)],
			},
			fields=["parent", "base_tax_amount_after_discount_amount"],
		)
		for t in taxes:
			tax_by_invoice[t.parent] = tax_by_invoice.get(t.parent, 0.0) + flt(
				t.base_tax_amount_after_discount_amount
			)

	items = frappe.get_all(
		f"{doctype} Item",
		filters={"parent": ["in", list(invoice_map)]},
		fields=["parent", "base_net_amount", "is_zero_rated", "is_exempt", "tax_rate", "tax_amount"],
	)

	rows = []
	for item in items:
		inv = invoice_map[item.parent]
		vat_amt = flt(item.tax_amount)
		if not vat_amt and not item.is_exempt and not item.is_zero_rated and item.parent in tax_by_invoice:
			vat_amt = tax_by_invoice[item.parent]
			tax_by_invoice[item.parent] = 0.0
		rows.append(
			{
				"net_amount": flt(item.base_net_amount),
				"vat_amount": vat_amt,
				"is_zero_rated": item.is_zero_rated,
				"is_exempt": item.is_exempt,
				"tax_rate": flt(item.tax_rate),
				"is_return": inv.is_return,
			}
		)
	return rows


def get_data(filters: frappe._dict) -> list[dict]:
	vat_accounts = get_sri_lanka_vat_accounts(filters.company)
	sales_rows = _fetch_invoice_rows("Sales Invoice", filters, vat_accounts)
	purchase_rows = _fetch_invoice_rows("Purchase Invoice", filters, vat_accounts)
	summary = compute_vat_return_summary(sales_rows, purchase_rows)

	return [
		{
			"box": "1",
			"description": _("Standard Rated Supplies & Output VAT"),
			"value": summary.standard_rated_sales,
			"vat_amount": summary.output_vat,
		},
		{
			"box": "2",
			"description": _("Zero-Rated Supplies (Exports & 0% Rated)"),
			"value": summary.zero_rated_sales,
			"vat_amount": 0.0,
		},
		{
			"box": "3",
			"description": _("Exempt Supplies"),
			"value": summary.exempt_sales,
			"vat_amount": 0.0,
		},
		{
			"box": "4",
			"description": _("Sales Credit Notes / Output VAT Adjustments"),
			"value": -summary.sales_credit_notes,
			"vat_amount": summary.output_vat_adjustments,
		},
		{
			"box": "5",
			"description": _("Standard Rated Purchases & Claimable Input VAT"),
			"value": summary.standard_rated_purchases,
			"vat_amount": summary.input_vat_claimable,
		},
		{
			"box": "6",
			"description": _("Exempt Purchases"),
			"value": summary.exempt_purchases,
			"vat_amount": 0.0,
		},
		{
			"box": "7",
			"description": _("Purchase Debit Notes / Input VAT Adjustments"),
			"value": -summary.purchase_debit_notes,
			"vat_amount": summary.input_vat_adjustments,
		},
		{
			"box": "8",
			"description": _("Net VAT Payable / (Refundable)"),
			"value": None,
			"vat_amount": summary.net_vat_payable,
		},
	]
