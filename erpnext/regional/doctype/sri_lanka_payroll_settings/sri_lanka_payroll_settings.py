# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from erpnext import get_region
from erpnext.regional.sri_lanka.constants import COUNTRY_NAME


class SriLankaPayrollSettings(Document):
	def validate(self):
		self.validate_company_unchanged()
		self.validate_company_region()
		self.validate_rates()
		self.validate_apit_slabs()

	def validate_company_unchanged(self):
		if not self.is_new() and self.has_value_changed("company"):
			frappe.throw(
				_("Company cannot be changed, create Sri Lanka Payroll Settings for {0} instead").format(
					frappe.bold(self.company)
				)
			)

	def validate_company_region(self):
		if self.company and get_region(self.company) != COUNTRY_NAME:
			frappe.throw(_("Company {0} is not in Sri Lanka.").format(frappe.bold(self.company)))

	def validate_rates(self):
		for fieldname, label in (
			("epf_employee_rate", "EPF Employee Rate"),
			("epf_employer_rate", "EPF Employer Rate"),
			("etf_employer_rate", "ETF Employer Rate"),
			("non_resident_apit_rate", "Non-Resident APIT Rate"),
		):
			if flt(self.get(fieldname)) < 0:
				frappe.throw(_("{0} cannot be negative.").format(_(label)))

	def validate_apit_slabs(self):
		slabs = sorted(self.get("apit_slabs") or [], key=lambda s: flt(s.from_amount))
		for idx, slab in enumerate(slabs):
			if flt(slab.from_amount) < 0:
				frappe.throw(_("Row #{0}: From Amount cannot be negative.").format(slab.idx))
			if flt(slab.to_amount) > 0 and flt(slab.to_amount) <= flt(slab.from_amount):
				frappe.throw(_("Row #{0}: To Amount must be greater than From Amount.").format(slab.idx))
			if flt(slab.tax_rate) < 0:
				frappe.throw(_("Row #{0}: Tax Rate cannot be negative.").format(slab.idx))
			if idx > 0 and flt(slabs[idx - 1].to_amount) == 0:
				frappe.throw(_("Only the highest APIT slab can have To Amount set to 0 (open-ended)."))
