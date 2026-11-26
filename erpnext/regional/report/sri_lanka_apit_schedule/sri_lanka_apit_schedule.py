# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from frappe import _

from erpnext.regional.sri_lanka.payroll import get_sri_lanka_payroll_records
from erpnext.regional.sri_lanka.utils import validate_sri_lanka_report_filters


def execute(filters=None):
	filters = validate_sri_lanka_report_filters(filters, _("Sri Lanka APIT Schedule"))
	return get_columns(), get_data(filters)


def get_columns():
	return [
		{"fieldname": "employee", "label": _("Employee"), "fieldtype": "Link", "options": "Employee", "width": 120},
		{"fieldname": "employee_name", "label": _("Employee Name"), "fieldtype": "Data", "width": 180},
		{"fieldname": "nic_number", "label": _("NIC Number"), "fieldtype": "Data", "width": 130},
		{"fieldname": "gross_pay", "label": _("Monthly Remuneration"), "fieldtype": "Currency", "options": "currency", "width": 160},
		{"fieldname": "is_non_resident", "label": _("Non-Resident"), "fieldtype": "Check", "width": 110},
		{"fieldname": "apit_tax_amount", "label": _("APIT / PAYE Deducted"), "fieldtype": "Currency", "options": "currency", "width": 160},
	]


def get_data(filters) -> list[dict]:
	return get_sri_lanka_payroll_records(filters)
