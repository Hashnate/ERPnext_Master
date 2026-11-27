# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.permissions import add_permission, update_permission_property

from erpnext.regional.sri_lanka.constants import (
	DEFAULT_EPF_EMPLOYEE_RATE,
	DEFAULT_EPF_EMPLOYER_RATE,
	DEFAULT_ETF_EMPLOYER_RATE,
	DEFAULT_MONTHLY_APIT_SLABS,
	DEFAULT_NON_RESIDENT_APIT_RATE,
	DEFAULT_VAT_RATE,
	SRI_LANKA_BANK_CODES,
)


def setup(company=None, patch=True):
	"""Install Sri Lanka regional custom fields, print formats, reports, and defaults."""
	make_custom_fields()
	add_print_formats()
	add_custom_roles_for_reports()
	add_permissions()
	seed_bank_codes()
	seed_salary_components()
	ensure_salary_slip_print_format()
	sync_sri_lanka_ui()
	if company:
		seed_company_settings(company)


def make_custom_fields(update=True):
	is_zero_rated = dict(
		fieldname="is_zero_rated",
		label="Is Zero Rated",
		fieldtype="Check",
		fetch_from="item_code.is_zero_rated",
		fetch_if_empty=1,
		insert_after="description",
		print_hide=1,
	)
	is_exempt = dict(
		fieldname="is_exempt",
		label="Is Exempt",
		fieldtype="Check",
		fetch_from="item_code.is_exempt",
		fetch_if_empty=1,
		insert_after="is_zero_rated",
		print_hide=1,
	)

	invoice_item_tax_fields = [
		is_zero_rated,
		is_exempt,
		dict(
			fieldname="tax_rate",
			label="Tax Rate",
			fieldtype="Float",
			insert_after="is_exempt",
			print_hide=1,
			hidden=1,
			read_only=1,
		),
		dict(
			fieldname="tax_amount",
			label="Tax Amount",
			fieldtype="Currency",
			insert_after="tax_rate",
			print_hide=1,
			hidden=1,
			read_only=1,
			options="currency",
		),
		dict(
			fieldname="total_amount",
			label="Total Amount",
			fieldtype="Currency",
			insert_after="tax_amount",
			print_hide=1,
			hidden=1,
			read_only=1,
			options="currency",
		),
	]

	custom_fields = {
		"Company": [
			dict(
				fieldname="tin_number",
				label="TIN Number",
				fieldtype="Data",
				insert_after="tax_id",
			),
			dict(
				fieldname="vat_reg_no",
				label="VAT Registration Number",
				fieldtype="Data",
				insert_after="tin_number",
			),
			dict(
				fieldname="is_vat_registered",
				label="Is VAT Registered",
				fieldtype="Check",
				insert_after="vat_reg_no",
			),
		],
		"Customer": [
			dict(
				fieldname="tin_number",
				label="TIN Number",
				fieldtype="Data",
				insert_after="tax_id",
			),
			dict(
				fieldname="vat_reg_no",
				label="VAT Registration Number",
				fieldtype="Data",
				insert_after="tin_number",
			),
			dict(
				fieldname="is_vat_registered",
				label="Is VAT Registered",
				fieldtype="Check",
				insert_after="vat_reg_no",
			),
		],
		"Supplier": [
			dict(
				fieldname="tin_number",
				label="TIN Number",
				fieldtype="Data",
				insert_after="tax_id",
			),
			dict(
				fieldname="vat_reg_no",
				label="VAT Registration Number",
				fieldtype="Data",
				insert_after="tin_number",
			),
			dict(
				fieldname="is_vat_registered",
				label="Is VAT Registered",
				fieldtype="Check",
				insert_after="vat_reg_no",
			),
		],
		"Item": [
			dict(
				fieldname="is_zero_rated",
				label="Is Zero Rated",
				fieldtype="Check",
				insert_after="item_group",
				print_hide=1,
			),
			dict(
				fieldname="is_exempt",
				label="Is Exempt",
				fieldtype="Check",
				insert_after="is_zero_rated",
				print_hide=1,
			),
		],
		"Sales Invoice": [
			dict(
				fieldname="vat_invoice_type",
				label="VAT Invoice Type",
				fieldtype="Select",
				options="\nTax Invoice\nSimplified Tax Invoice",
				default="Simplified Tax Invoice",
				insert_after="naming_series",
				print_hide=1,
			),
			dict(
				fieldname="company_vat_reg_no",
				label="Company VAT Registration No.",
				fieldtype="Read Only",
				fetch_from="company.vat_reg_no",
				insert_after="company_address",
				print_hide=1,
			),
			dict(
				fieldname="customer_vat_reg_no",
				label="Customer VAT Registration No.",
				fieldtype="Read Only",
				fetch_from="customer.vat_reg_no",
				insert_after="customer_address",
				print_hide=1,
			),
		],
		"Purchase Invoice": [
			dict(
				fieldname="company_vat_reg_no",
				label="Company VAT Registration No.",
				fieldtype="Read Only",
				fetch_from="company.vat_reg_no",
				insert_after="shipping_address",
				print_hide=1,
			),
			dict(
				fieldname="supplier_vat_reg_no",
				label="Supplier VAT Registration No.",
				fieldtype="Read Only",
				fetch_from="supplier.vat_reg_no",
				insert_after="supplier_address",
				print_hide=1,
			),
		],
		"Sales Invoice Item": invoice_item_tax_fields,
		"Purchase Invoice Item": invoice_item_tax_fields,
		"Bank": [
			dict(
				fieldname="sri_lanka_bank_code",
				label="Sri Lanka Bank Code (4-Digit SLIPS)",
				fieldtype="Data",
				insert_after="swift_number",
			),
		],
		"Bank Account": [
			dict(
				fieldname="sri_lanka_branch_code",
				label="Sri Lanka Branch Code (3-Digit SLIPS)",
				fieldtype="Data",
				insert_after="branch_code",
			),
		],
	}

	# Conditionally extend HRMS DocTypes when the hrms app is installed
	if frappe.db.exists("DocType", "Employee"):
		custom_fields["Employee"] = [
			dict(fieldname="nic_number", label="NIC Number", fieldtype="Data", insert_after="employee_name"),
			dict(fieldname="epf_number", label="EPF Member No.", fieldtype="Data", insert_after="nic_number"),
			dict(
				fieldname="sri_lanka_bank_code",
				label="Sri Lanka Bank Code",
				fieldtype="Data",
				insert_after="bank_name",
			),
			dict(
				fieldname="sri_lanka_branch_code",
				label="Sri Lanka Branch Code",
				fieldtype="Data",
				insert_after="sri_lanka_bank_code",
			),
			dict(
				fieldname="is_non_resident_for_apit",
				label="Non-Resident for APIT",
				fieldtype="Check",
				insert_after="epf_number",
			),
			dict(
				fieldname="sri_lanka_basic_salary",
				label="Monthly Basic Salary (Sri Lanka Payroll)",
				fieldtype="Currency",
				options="salary_currency",
				insert_after="ctc",
			),
			dict(
				fieldname="sri_lanka_epf_allowances",
				label="Monthly EPF-Liable Allowances / BRA",
				fieldtype="Currency",
				options="salary_currency",
				insert_after="sri_lanka_basic_salary",
			),
			dict(
				fieldname="sri_lanka_non_epf_allowances",
				label="Monthly Non-EPF Allowances",
				fieldtype="Currency",
				options="salary_currency",
				insert_after="sri_lanka_epf_allowances",
			),
		]

	if frappe.db.exists("DocType", "Salary Component"):
		custom_fields["Salary Component"] = [
			dict(
				fieldname="is_epf_etf_applicable",
				label="Liable for EPF / ETF",
				fieldtype="Check",
				insert_after="statistical_component",
			),
			dict(
				fieldname="is_apit_lump_sum",
				label="APIT Lump Sum / Bonus Component",
				fieldtype="Check",
				insert_after="is_epf_etf_applicable",
			),
		]

	if frappe.db.exists("DocType", "Salary Slip"):
		custom_fields["Salary Slip"] = [
			dict(
				fieldname="epf_liable_earnings",
				label="EPF / ETF Liable Earnings",
				fieldtype="Currency",
				read_only=1,
				insert_after="gross_pay",
			),
			dict(
				fieldname="epf_employer_contribution",
				label="EPF Employer Contribution (12%)",
				fieldtype="Currency",
				read_only=1,
				insert_after="epf_liable_earnings",
			),
			dict(
				fieldname="etf_employer_contribution",
				label="ETF Employer Contribution (3%)",
				fieldtype="Currency",
				read_only=1,
				insert_after="epf_employer_contribution",
			),
			dict(
				fieldname="apit_tax_amount",
				label="APIT / PAYE Tax Amount",
				fieldtype="Currency",
				read_only=1,
				insert_after="etf_employer_contribution",
			),
		]

	create_custom_fields(custom_fields, update=update, ignore_validate=True)


def add_print_formats():
	for pf_folder in ("sri_lanka_tax_invoice", "sri_lanka_simplified_tax_invoice", "sri_lanka_payslip"):
		frappe.reload_doc("regional", "print_format", pf_folder)

	pf = frappe.qb.DocType("Print Format")
	(
		frappe.qb.update(pf)
		.set(pf.disabled, 0)
		.where(
			pf.name.isin(
				["Sri Lanka Tax Invoice", "Sri Lanka Simplified Tax Invoice", "Sri Lanka Payslip"]
			)
		)
		.run()
	)


def add_custom_roles_for_reports():
	report_roles = {
		"Sri Lanka VAT Return": ["Accounts User", "Accounts Manager", "Auditor"],
		"Sri Lanka EPF C Form": ["HR User", "HR Manager", "Accounts Manager"],
		"Sri Lanka ETF Return": ["HR User", "HR Manager", "Accounts Manager"],
		"Sri Lanka APIT Schedule": ["HR User", "HR Manager", "Accounts Manager"],
	}
	for report_name, roles in report_roles.items():
		if not frappe.db.get_value("Custom Role", dict(report=report_name)):
			frappe.get_doc(
				doctype="Custom Role",
				report=report_name,
				roles=[dict(role=r) for r in roles if frappe.db.exists("Role", r)],
			).insert(ignore_permissions=True)


def add_permissions():
	for doctype in (
		"Sri Lanka VAT Settings",
		"Sri Lanka VAT Account",
		"Sri Lanka Payroll Settings",
		"Sri Lanka APIT Slab",
		"Sri Lanka Payroll Entry",
		"Sri Lanka Payroll Employee",
	):
		for role in ("Accounts Manager", "Accounts User", "HR Manager", "HR User", "System Manager"):
			if frappe.db.exists("Role", role):
				add_permission(doctype, role, 0)
				update_permission_property(doctype, role, 0, "write", 1)
				update_permission_property(doctype, role, 0, "create", 1)
				if doctype == "Sri Lanka Payroll Entry" and role in (
					"Accounts Manager",
					"HR Manager",
					"System Manager",
				):
					update_permission_property(doctype, role, 0, "submit", 1)
					update_permission_property(doctype, role, 0, "cancel", 1)


def seed_bank_codes():
	for bank_name, code in SRI_LANKA_BANK_CODES.items():
		if frappe.db.exists("Bank", bank_name):
			frappe.db.set_value("Bank", bank_name, "sri_lanka_bank_code", code, update_modified=False)


def seed_company_settings(company: str):
	if not frappe.db.exists("Sri Lanka VAT Settings", company):
		vat_accounts = frappe.get_all(
			"Account",
			filters={"company": company, "account_type": "Tax", "is_group": 0},
			fields=["name"],
		)
		if vat_accounts:
			doc = frappe.get_doc(
				{
					"doctype": "Sri Lanka VAT Settings",
					"company": company,
					"default_vat_rate": DEFAULT_VAT_RATE,
					"vat_accounts": [
						{
							"account": acct.name,
							"vat_type": "Input VAT" if "input" in acct.name.lower() else "Output VAT",
						}
						for acct in vat_accounts
					],
				}
			)
			doc.insert(ignore_permissions=True)

	if not frappe.db.exists("Sri Lanka Payroll Settings", company):
		frappe.get_doc(
			{
				"doctype": "Sri Lanka Payroll Settings",
				"company": company,
				"auto_calculate_statutory": 1,
				"epf_employee_rate": DEFAULT_EPF_EMPLOYEE_RATE,
				"epf_employer_rate": DEFAULT_EPF_EMPLOYER_RATE,
				"etf_employer_rate": DEFAULT_ETF_EMPLOYER_RATE,
				"non_resident_apit_rate": DEFAULT_NON_RESIDENT_APIT_RATE,
				"apit_slabs": list(DEFAULT_MONTHLY_APIT_SLABS),
			}
		).insert(ignore_permissions=True)


SRI_LANKA_SALARY_SLIP_HTML = """<style>
	.sl-slip { font-family: Arial, Helvetica, sans-serif; font-size: 12px; color: #1a1a1a; }
	.sl-slip-hdr { display: flex; justify-content: space-between; border-bottom: 2px solid #1a1a1a; padding-bottom: 8px; margin-bottom: 12px; }
	.sl-slip-title { font-size: 18px; font-weight: 700; text-transform: uppercase; }
	.sl-meta { width: 100%; border-collapse: collapse; margin-bottom: 12px; }
	.sl-meta td { padding: 4px 8px; border: 1px solid #d0d0d0; font-size: 11px; }
	.sl-grid { display: flex; gap: 14px; margin-bottom: 12px; }
	.sl-col { flex: 1; }
	.sl-tbl { width: 100%; border-collapse: collapse; }
	.sl-tbl th { background: #f3f4f6; border: 1px solid #ccc; padding: 6px; font-size: 11px; text-align: left; }
	.sl-tbl td { border: 1px solid #ccc; padding: 6px; font-size: 11px; }
	.text-right { text-align: right; }
	.sl-net { border: 2px solid #1a1a1a; padding: 8px 12px; background: #f3f4f6; display: flex; justify-content: space-between; font-size: 14px; font-weight: 700; margin-bottom: 10px; }
	.sl-stat { font-size: 11px; color: #444; border: 1px solid #d0d0d0; padding: 8px 10px; border-radius: 4px; }
</style>
{% set emp = frappe.db.get_value("Employee", doc.employee, ["nic_number", "epf_number", "sri_lanka_bank_code", "sri_lanka_branch_code"], as_dict=True) or {} %}
<div class="sl-slip">
	<div class="sl-slip-hdr">
		<div>
			<div style="font-size: 16px; font-weight: 700;">{{ doc.company }}</div>
			<div>Salary Slip: {{ doc.name }}</div>
		</div>
		<div class="text-right">
			<div class="sl-slip-title">PAYSLIP</div>
			<div>Period: {{ doc.get_formatted('start_date') }} to {{ doc.get_formatted('end_date') }}</div>
			<div>Pay Date: {{ doc.get_formatted('posting_date') }}</div>
		</div>
	</div>
	<table class="sl-meta">
		<tr>
			<td><strong>Employee ID:</strong> {{ doc.employee }}</td>
			<td><strong>Employee Name:</strong> {{ doc.employee_name }}</td>
		</tr>
		<tr>
			<td><strong>NIC No.:</strong> {{ emp.nic_number or 'N/A' }}</td>
			<td><strong>EPF Member No.:</strong> {{ emp.epf_number or 'N/A' }}</td>
		</tr>
		<tr>
			<td><strong>Bank:</strong> {{ doc.bank_name or 'N/A' }} ({{ emp.sri_lanka_bank_code or '-' }} / {{ emp.sri_lanka_branch_code or '-' }})</td>
			<td><strong>Account No.:</strong> {{ doc.bank_account_no or 'N/A' }}</td>
		</tr>
	</table>
	<div class="sl-grid">
		<div class="sl-col">
			<table class="sl-tbl">
				<thead><tr><th>Earnings</th><th class="text-right">Amount ({{ doc.currency }})</th></tr></thead>
				<tbody>
					{% for row in doc.earnings %}
					<tr><td>{{ row.salary_component }}</td><td class="text-right">{{ row.get_formatted('amount', doc) }}</td></tr>
					{% endfor %}
					<tr><th>Gross Pay</th><th class="text-right">{{ doc.get_formatted('gross_pay') }}</th></tr>
				</tbody>
			</table>
		</div>
		<div class="sl-col">
			<table class="sl-tbl">
				<thead><tr><th>Deductions</th><th class="text-right">Amount ({{ doc.currency }})</th></tr></thead>
				<tbody>
					{% for row in doc.deductions %}
					<tr><td>{{ row.salary_component }}</td><td class="text-right">{{ row.get_formatted('amount', doc) }}</td></tr>
					{% endfor %}
					<tr><th>Total Deductions</th><th class="text-right">{{ doc.get_formatted('total_deduction') }}</th></tr>
				</tbody>
			</table>
		</div>
	</div>
	<div class="sl-net">
		<span>NET PAY ({{ doc.currency }})</span>
		<span>{{ doc.get_formatted('net_pay') }}</span>
	</div>
	<div class="sl-stat">
		<strong>Employer Statutory Contributions (Not Deducted from Pay):</strong>
		EPF Liable Base: {{ doc.get_formatted('epf_liable_earnings') }} |
		EPF Employer (12%): {{ doc.get_formatted('epf_employer_contribution') }} |
		ETF Employer (3%): {{ doc.get_formatted('etf_employer_contribution') }} |
		APIT / PAYE: {{ doc.get_formatted('apit_tax_amount') }}
	</div>
</div>"""


def seed_salary_components():
	"""Ensure Sri Lanka EPF/APIT Salary Components exist when HRMS is installed."""
	if not frappe.db.exists("DocType", "Salary Component"):
		return

	components = (
		{
			"salary_component": "EPF Employee",
			"salary_component_abbr": "EPFE",
			"type": "Deduction",
			"description": "Employee EPF Contribution (8%)",
		},
		{
			"salary_component": "APIT / PAYE",
			"salary_component_abbr": "APIT",
			"type": "Deduction",
			"description": "Advance Personal Income Tax (APIT / PAYE)",
		},
	)
	for comp in components:
		if not frappe.db.exists("Salary Component", comp["salary_component"]):
			frappe.get_doc({"doctype": "Salary Component", **comp}).insert(ignore_permissions=True)

	if frappe.db.exists("Salary Component", "Basic"):
		if not frappe.db.get_value("Salary Component", "Basic", "is_epf_etf_applicable"):
			frappe.db.set_value("Salary Component", "Basic", "is_epf_etf_applicable", 1, update_modified=False)


def ensure_salary_slip_print_format():
	"""Create/enable the Sri Lanka Salary Slip print format when HRMS Salary Slip exists."""
	if not frappe.db.exists("DocType", "Salary Slip"):
		return

	pf_name = "Sri Lanka Salary Slip"
	if not frappe.db.exists("Print Format", pf_name):
		frappe.get_doc(
			{
				"doctype": "Print Format",
				"name": pf_name,
				"doc_type": "Salary Slip",
				"module": "Regional",
				"standard": "No",
				"custom_format": 1,
				"print_format_type": "Jinja",
				"default_print_language": "en",
				"disabled": 0,
				"font": "Default",
				"font_size": 12,
				"margin_top": 15.0,
				"margin_bottom": 15.0,
				"margin_left": 15.0,
				"margin_right": 15.0,
				"page_number": "Hide",
				"html": SRI_LANKA_SALARY_SLIP_HTML,
			}
		).insert(ignore_permissions=True)
	elif frappe.db.get_value("Print Format", pf_name, "disabled"):
		frappe.db.set_value("Print Format", pf_name, "disabled", 0, update_modified=False)


def _insert_items_in_section(items: list, section_label: str | None, new_items: list[dict]) -> bool:
	"""Insert missing link dicts at the end of a named section (or after anchor) in a Sidebar items table."""
	existing_targets = {row.get("link_to") for row in items if row.get("link_to")}
	to_add = [item for item in new_items if item.get("link_to") not in existing_targets]
	if not to_add:
		return False

	insert_at = len(items)
	if section_label:
		in_section = False
		for idx, row in enumerate(items):
			if row.get("type") == "Section Break":
				if in_section:
					insert_at = idx
					break
				if row.get("label") == section_label:
					in_section = True
			elif in_section and not row.get("child"):
				insert_at = idx
				break
		# If section found and was the last section, insert_at stays len(items)

	for offset, item in enumerate(to_add):
		items.insert(insert_at + offset, item)
	return True


def _insert_items_after_link(items: list, anchor_link_to: str, new_items: list[dict]) -> bool:
	existing_targets = {row.get("link_to") for row in items if row.get("link_to")}
	to_add = [item for item in new_items if item.get("link_to") not in existing_targets]
	if not to_add:
		return False

	insert_at = len(items)
	for idx, row in enumerate(items):
		if row.get("link_to") == anchor_link_to:
			insert_at = idx + 1
			break

	for offset, item in enumerate(to_add):
		items.insert(insert_at + offset, item)
	return True


def _sync_sidebar_doctype(doctype: str, name: str, operations: list[tuple[str, str, list[dict]]]):
	if not frappe.db.exists("DocType", doctype) or not frappe.db.exists(doctype, name):
		return

	doc = frappe.get_doc(doctype, name)
	items = [row.as_dict() for row in (doc.get("items") or [])]
	changed = False
	for mode, target, new_items in operations:
		if mode == "section":
			changed |= _insert_items_in_section(items, target, new_items)
		elif mode == "after":
			changed |= _insert_items_after_link(items, target, new_items)

	if not changed:
		return

	doc.set("items", [])
	for item in items:
		item.pop("name", None)
		item.pop("idx", None)
		doc.append("items", item)
	doc.flags.ignore_permissions = True
	doc.save()


def _sync_accounting_workspace():
	if not frappe.db.exists("DocType", "Workspace") or not frappe.db.exists("Workspace", "Accounting"):
		return

	ws = frappe.get_doc("Workspace", "Accounting")
	links = [row.as_dict() for row in (ws.get("links") or [])]
	existing_targets = {row.get("link_to") for row in links if row.get("link_to")}
	vat_links = [
		{
			"hidden": 0,
			"is_query_report": 0,
			"label": "Sri Lanka VAT Settings",
			"link_count": 0,
			"link_to": "Sri Lanka VAT Settings",
			"link_type": "DocType",
			"onboard": 0,
			"only_for": "Sri Lanka",
			"type": "Link",
		},
		{
			"hidden": 0,
			"is_query_report": 1,
			"label": "Sri Lanka VAT Return",
			"link_count": 0,
			"link_to": "Sri Lanka VAT Return",
			"link_type": "Report",
			"onboard": 0,
			"only_for": "Sri Lanka",
			"type": "Link",
		},
	]
	to_add = [item for item in vat_links if item["link_to"] not in existing_targets]
	if not to_add:
		return

	insert_at = len(links)
	in_card = False
	card_idx = None
	for idx, row in enumerate(links):
		if row.get("type") == "Card Break":
			if in_card:
				insert_at = idx
				break
			if row.get("label") == "Tax & Compliance":
				in_card = True
				card_idx = idx

	for offset, item in enumerate(to_add):
		links.insert(insert_at + offset, item)

	if card_idx is not None:
		links[card_idx]["link_count"] = int(links[card_idx].get("link_count") or 0) + len(to_add)

	ws.set("links", [])
	for item in links:
		item.pop("name", None)
		item.pop("idx", None)
		ws.append("links", item)
	ws.flags.ignore_permissions = True
	ws.save()


def sync_sri_lanka_ui():
	"""Add Sri Lanka VAT and Payroll links into ERPNext Accounts and HRMS Payroll sidebars/workspaces."""
	vat_items = [
		{
			"child": 1,
			"collapsible": 1,
			"indent": 0,
			"keep_closed": 0,
			"label": "Sri Lanka VAT Settings",
			"link_to": "Sri Lanka VAT Settings",
			"link_type": "DocType",
			"open_in_new_tab": 0,
			"show_arrow": 0,
			"type": "Link",
		},
		{
			"child": 1,
			"collapsible": 1,
			"indent": 0,
			"keep_closed": 0,
			"label": "Sri Lanka VAT Return",
			"link_to": "Sri Lanka VAT Return",
			"link_type": "Report",
			"open_in_new_tab": 0,
			"show_arrow": 0,
			"type": "Link",
		},
	]
	for sb_doctype in ("Sidebar", "Workspace Sidebar"):
		_sync_sidebar_doctype(sb_doctype, "Accounts", [("section", "Taxes", vat_items)])
	_sync_accounting_workspace()

	if frappe.db.exists("DocType", "Salary Slip"):
		payroll_entry_item = [
			{
				"child": 0,
				"collapsible": 1,
				"icon": "wallet",
				"indent": 0,
				"keep_closed": 0,
				"label": "Sri Lanka Payroll Entry",
				"link_to": "Sri Lanka Payroll Entry",
				"link_type": "DocType",
				"open_in_new_tab": 0,
				"show_arrow": 0,
				"type": "Link",
			}
		]
		payroll_reports = [
			{
				"child": 1,
				"collapsible": 1,
				"indent": 0,
				"keep_closed": 0,
				"label": "Sri Lanka EPF C Form",
				"link_to": "Sri Lanka EPF C Form",
				"link_type": "Report",
				"open_in_new_tab": 0,
				"show_arrow": 0,
				"type": "Link",
			},
			{
				"child": 1,
				"collapsible": 1,
				"indent": 0,
				"keep_closed": 0,
				"label": "Sri Lanka ETF Return",
				"link_to": "Sri Lanka ETF Return",
				"link_type": "Report",
				"open_in_new_tab": 0,
				"show_arrow": 0,
				"type": "Link",
			},
			{
				"child": 1,
				"collapsible": 1,
				"indent": 0,
				"keep_closed": 0,
				"label": "Sri Lanka APIT Schedule",
				"link_to": "Sri Lanka APIT Schedule",
				"link_type": "Report",
				"open_in_new_tab": 0,
				"show_arrow": 0,
				"type": "Link",
			},
		]
		payroll_setup = [
			{
				"child": 1,
				"collapsible": 1,
				"indent": 0,
				"keep_closed": 0,
				"label": "Sri Lanka Payroll Settings",
				"link_to": "Sri Lanka Payroll Settings",
				"link_type": "DocType",
				"open_in_new_tab": 0,
				"show_arrow": 0,
				"type": "Link",
			}
		]
		apit_report = [payroll_reports[2]]
		for sb_doctype in ("Sidebar", "Workspace Sidebar"):
			_sync_sidebar_doctype(
				sb_doctype,
				"Payroll",
				[
					("after", "Payroll Entry", payroll_entry_item),
					("section", "Reports", payroll_reports),
					("section", "Setup", payroll_setup),
				],
			)
			_sync_sidebar_doctype(
				sb_doctype,
				"Tax & Benefits",
				[("section", "Reports", apit_report)],
			)


def after_migrate_sri_lanka():
	"""Keep Sri Lanka UI links, components, and print formats intact after bench migrate."""
	has_sri_lanka = (
		frappe.db.exists("Company", {"country": "Sri Lanka"})
		or (frappe.db.exists("DocType", "Sri Lanka Payroll Settings") and frappe.db.count("Sri Lanka Payroll Settings"))
		or (frappe.db.exists("DocType", "Sri Lanka VAT Settings") and frappe.db.count("Sri Lanka VAT Settings"))
	)
	if not has_sri_lanka:
		return

	seed_salary_components()
	ensure_salary_slip_print_format()
	sync_sri_lanka_ui()
