from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document


class WorkSightOvertimeRecord(Document):
	def validate(self) -> None:
		if (self.overtime_minutes or 0) < 0:
			frappe.throw(_("Overtime Minutes cannot be negative."))
		if (self.overtime_hours or 0) < 0:
			frappe.throw(_("Overtime Hours cannot be negative."))
		if (self.overtime_amount or 0) < 0:
			frappe.throw(_("Overtime Amount cannot be negative."))

	def before_submit(self) -> None:
		if self.status == "Pending":
			self.status = "Approved"
