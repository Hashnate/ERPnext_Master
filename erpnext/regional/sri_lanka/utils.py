# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import getdate

from erpnext import get_region
from erpnext.regional.sri_lanka.constants import COUNTRY_NAME


def validate_sri_lanka_report_filters(filters, report_name: str):
	"""Validate date range, company permission, and Sri Lanka region for regional reports."""
	filters = frappe._dict(filters or {})
	from_date = filters.get("from_date")
	to_date = filters.get("to_date")
	if from_date and to_date and getdate(from_date) > getdate(to_date):
		frappe.throw(_("From Date must be before To Date"))

	if not filters.get("company"):
		frappe.throw(_("Company is required"))

	frappe.has_permission("Company", doc=filters.company, throw=True)
	if get_region(filters.company) != COUNTRY_NAME:
		frappe.throw(_("{0} is only available for Sri Lanka companies.").format(report_name))

	return filters
