# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt

from erpnext.regional.sri_lanka.constants import DEFAULT_NON_RESIDENT_APIT_RATE
from erpnext.regional.sri_lanka.payroll import calculate_apit, get_payroll_settings
from erpnext.regional.sri_lanka.utils import validate_sri_lanka_report_filters


def execute(filters=None):
	filters = validate_sri_lanka_report_filters(filters, _("Sri Lanka APIT Schedule"))

	columns = get_columns()
	if not frappe.db.exists("DocType", "Salary Slip"):
		return columns, []

	return columns, get_data(filters)


def get_columns():
	return [
		{"fieldname": "employee", "label": _("Employee"), "fieldtype": "Link", "options": "Employee", "width": 120},
		{"fieldname": "employee_name", "label": _("Employee Name"), "fieldtype": "Data", "width": 180},
		{"fieldname": "nic_number", "label": _("NIC Number"), "fieldtype": "Data", "width": 130},
		{"fieldname": "gross_pay", "label": _("Monthly Remuneration"), "fieldtype": "Currency", "options": "currency", "width": 160},
		{"fieldname": "is_non_resident", "label": _("Non-Resident"), "fieldtype": "Check", "width": 110},
		{"fieldname": "apit_tax_amount", "label": _("APIT / PAYE Deducted"), "fieldtype": "Currency", "options": "currency", "width": 160},
	]


def get_data(filters: frappe._dict) -> list[dict]:
	settings = get_payroll_settings(filters.company)
	slabs = (
		[
			{"from_amount": s.from_amount, "to_amount": s.to_amount, "tax_rate": s.tax_rate}
			for s in (settings.get("apit_slabs") or [])
		]
		if settings
		else None
	)
	non_res_rate = (
		flt(settings.non_resident_apit_rate) if settings else DEFAULT_NON_RESIDENT_APIT_RATE
	)
	currency = frappe.get_cached_value("Company", filters.company, "default_currency") or "LKR"

	slips = frappe.get_all(
		"Salary Slip",
		filters={
			"company": filters.company,
			"docstatus": 1,
			"posting_date": ["between", [filters.from_date, filters.to_date]],
		},
		fields=["employee", "employee_name", "gross_pay", "apit_tax_amount"],
		order_by="employee asc",
	)

	rows = []
	for slip in slips:
		emp = frappe.db.get_value(
			"Employee", slip.employee, ["nic_number", "is_non_resident_for_apit"], as_dict=True
		) or {}
		is_non_res = bool(emp.get("is_non_resident_for_apit"))
		apit_amt = flt(slip.get("apit_tax_amount"))
		if not apit_amt and flt(slip.gross_pay) > 0:
			apit_amt = calculate_apit(
				flt(slip.gross_pay),
				tax_slabs=slabs,
				is_non_resident=is_non_res,
				non_resident_rate=non_res_rate,
			)
		rows.append(
			{
				"employee": slip.employee,
				"employee_name": slip.employee_name,
				"nic_number": emp.get("nic_number") or "",
				"gross_pay": flt(slip.gross_pay),
				"is_non_resident": int(is_non_res),
				"apit_tax_amount": apit_amt,
				"currency": currency,
			}
		)
	return rows
