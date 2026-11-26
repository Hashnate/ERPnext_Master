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
