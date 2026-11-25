# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt

from erpnext.regional.sri_lanka.constants import DEFAULT_ETF_EMPLOYER_RATE
from erpnext.regional.sri_lanka.payroll import calculate_epf_etf, get_payroll_settings
from erpnext.regional.sri_lanka.utils import validate_sri_lanka_report_filters


def execute(filters=None):
	filters = validate_sri_lanka_report_filters(filters, _("Sri Lanka ETF Return"))

	columns = get_columns()
	if not frappe.db.exists("DocType", "Salary Slip"):
		return columns, []

	return columns, get_data(filters)


def get_columns():
	return [
		{"fieldname": "employee", "label": _("Employee"), "fieldtype": "Link", "options": "Employee", "width": 120},
		{"fieldname": "employee_name", "label": _("Employee Name"), "fieldtype": "Data", "width": 180},
		{"fieldname": "epf_number", "label": _("EPF / Member No."), "fieldtype": "Data", "width": 130},
		{"fieldname": "nic_number", "label": _("NIC Number"), "fieldtype": "Data", "width": 130},
		{"fieldname": "liable_earnings", "label": _("Total Earnings for ETF"), "fieldtype": "Currency", "options": "currency", "width": 160},
		{"fieldname": "etf_employer", "label": _("ETF Contribution (3%)"), "fieldtype": "Currency", "options": "currency", "width": 160},
	]


def get_data(filters: frappe._dict) -> list[dict]:
	settings = get_payroll_settings(filters.company)
	etf_rate = flt(settings.etf_employer_rate) if settings else DEFAULT_ETF_EMPLOYER_RATE
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
		etf = calculate_epf_etf(base, etf_employer_rate=etf_rate)
		rows.append(
			{
				"employee": slip.employee,
				"employee_name": slip.employee_name,
				"epf_number": emp.get("epf_number") or "",
				"nic_number": emp.get("nic_number") or "",
				"liable_earnings": etf.liable_earnings,
				"etf_employer": etf.etf_employer,
				"currency": currency,
			}
		)
	return rows
