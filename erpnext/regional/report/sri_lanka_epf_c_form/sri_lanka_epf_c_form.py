# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt

from erpnext.regional.sri_lanka.constants import (
	DEFAULT_EPF_EMPLOYEE_RATE,
	DEFAULT_EPF_EMPLOYER_RATE,
)
from erpnext.regional.sri_lanka.payroll import calculate_epf_etf, get_payroll_settings
from erpnext.regional.sri_lanka.utils import validate_sri_lanka_report_filters


def execute(filters=None):
	filters = validate_sri_lanka_report_filters(filters, _("Sri Lanka EPF C Form"))

	columns = get_columns()
	if not frappe.db.exists("DocType", "Salary Slip"):
		return columns, []

	return columns, get_data(filters)


def get_columns():
	return [
		{"fieldname": "employee", "label": _("Employee"), "fieldtype": "Link", "options": "Employee", "width": 120},
		{"fieldname": "employee_name", "label": _("Employee Name"), "fieldtype": "Data", "width": 180},
		{"fieldname": "epf_number", "label": _("EPF Member No."), "fieldtype": "Data", "width": 120},
		{"fieldname": "nic_number", "label": _("NIC Number"), "fieldtype": "Data", "width": 130},
		{"fieldname": "liable_earnings", "label": _("Total Earnings for EPF"), "fieldtype": "Currency", "options": "currency", "width": 160},
		{"fieldname": "epf_employee", "label": _("Employee 8%"), "fieldtype": "Currency", "options": "currency", "width": 130},
		{"fieldname": "epf_employer", "label": _("Employer 12%"), "fieldtype": "Currency", "options": "currency", "width": 130},
		{"fieldname": "epf_total", "label": _("Total EPF (20%)"), "fieldtype": "Currency", "options": "currency", "width": 140},
	]


def get_data(filters: frappe._dict) -> list[dict]:
	settings = get_payroll_settings(filters.company)
	emp_rate = flt(settings.epf_employee_rate) if settings else DEFAULT_EPF_EMPLOYEE_RATE
	er_rate = flt(settings.epf_employer_rate) if settings else DEFAULT_EPF_EMPLOYER_RATE
	currency = frappe.get_cached_value("Company", filters.company, "default_currency") or "LKR"

	slips = frappe.get_all(
		"Salary Slip",
		filters={
			"company": filters.company,
			"docstatus": 1,
			"posting_date": ["between", [filters.from_date, filters.to_date]],
		},
		fields=["employee", "employee_name", "epf_liable_earnings", "gross_pay"],
		order_by="employee asc",
	)

	rows = []
	for slip in slips:
		emp = frappe.db.get_value(
			"Employee", slip.employee, ["epf_number", "nic_number"], as_dict=True
		) or {}
		base = flt(slip.get("epf_liable_earnings") or slip.get("gross_pay"))
		epf = calculate_epf_etf(base, epf_employee_rate=emp_rate, epf_employer_rate=er_rate)
		rows.append(
			{
				"employee": slip.employee,
				"employee_name": slip.employee_name,
				"epf_number": emp.get("epf_number") or "",
				"nic_number": emp.get("nic_number") or "",
				"liable_earnings": epf.liable_earnings,
				"epf_employee": epf.epf_employee,
				"epf_employer": epf.epf_employer,
				"epf_total": epf.epf_total,
				"currency": currency,
			}
		)
	return rows
