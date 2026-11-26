from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document


class WorkSightSettings(Document):
	def validate(self) -> None:
		if self.timestamp_tolerance_seconds is not None and self.timestamp_tolerance_seconds < 0:
			frappe.throw(_("Timestamp Tolerance (Seconds) cannot be negative."))
		if self.deduplication_window_seconds is not None and self.deduplication_window_seconds < 0:
			frappe.throw(_("Deduplication Window (Seconds) cannot be negative."))
		if self.standard_working_days_per_month is not None and self.standard_working_days_per_month <= 0:
			frappe.throw(_("Standard Working Days Per Month must be greater than zero."))
		if self.standard_working_hours_per_day is not None and self.standard_working_hours_per_day <= 0:
			frappe.throw(_("Standard Working Hours Per Day must be greater than zero."))
		if self.overtime_threshold_minutes is not None and self.overtime_threshold_minutes < 0:
			frappe.throw(_("Overtime Threshold (Minutes) cannot be negative."))
		if self.overtime_rounding_minutes is not None and self.overtime_rounding_minutes < 0:
			frappe.throw(_("Overtime Rounding Interval (Minutes) cannot be negative."))
		if self.late_grace_minutes is not None and self.late_grace_minutes < 0:
			frappe.throw(_("Default Grace Minutes cannot be negative."))
