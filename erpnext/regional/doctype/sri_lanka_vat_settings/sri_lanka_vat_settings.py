# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from erpnext import get_region
from erpnext.regional.sri_lanka.constants import COUNTRY_NAME


class SriLankaVATSettings(Document):
	def validate(self):
		self.validate_company_unchanged()
		self.validate_company_region()
		self.validate_accounts()

	def validate_company_unchanged(self):
		if not self.is_new() and self.has_value_changed("company"):
			frappe.throw(
				_("Company cannot be changed, create Sri Lanka VAT Settings for {0} instead").format(
					frappe.bold(self.company)
				)
			)

	def validate_company_region(self):
		if self.company and get_region(self.company) != COUNTRY_NAME:
			frappe.throw(_("Company {0} is not in Sri Lanka.").format(frappe.bold(self.company)))

	def validate_accounts(self):
		accounts = set()
		for row in self.vat_accounts:
			if not row.account:
				frappe.throw(_("Row #{0}: Account is mandatory").format(row.idx))
			if row.account in accounts:
				frappe.throw(_("Row #{0}: Account {1} is added more than once").format(row.idx, row.account))

			company, is_group = frappe.get_cached_value("Account", row.account, ["company", "is_group"])
			if company != self.company:
				frappe.throw(
					_("Row #{0}: Account {1} does not belong to company {2}").format(
						row.idx, row.account, self.company
					)
				)
			if is_group:
				frappe.throw(_("Row #{0}: Account {1} is a group account").format(row.idx, row.account))
			accounts.add(row.account)
