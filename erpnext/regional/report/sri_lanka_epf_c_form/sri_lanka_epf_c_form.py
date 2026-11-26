# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from frappe import _

from erpnext.regional.sri_lanka.payroll import get_sri_lanka_payroll_records
from erpnext.regional.sri_lanka.utils import validate_sri_lanka_report_filters


def execute(filters=None):
	filters = validate_sri_lanka_report_filters(filters, _("Sri Lanka EPF C Form"))
	return get_columns(), get_data(filters)


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


def get_data(filters) -> list[dict]:
	return get_sri_lanka_payroll_records(filters)
