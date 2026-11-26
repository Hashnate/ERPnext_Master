from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document


class WorkSightLateRecord(Document):
	def validate(self) -> None:
		if (self.late_minutes or 0) < 0:
			frappe.throw(_("Late Minutes cannot be negative."))
		if (self.billable_late_minutes or 0) < 0:
			frappe.throw(_("Billable Late Minutes cannot be negative."))
		if (self.deduction_amount or 0) < 0:
			frappe.throw(_("Deduction Amount cannot be negative."))

	def before_submit(self) -> None:
		if self.status == "Pending":
			self.status = "Approved"
