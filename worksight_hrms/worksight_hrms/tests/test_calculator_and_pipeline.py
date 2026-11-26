from __future__ import annotations

import sys
import unittest
from datetime import datetime, time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
	sys.path.insert(0, str(REPO_ROOT))

try:
	import frappe  # noqa: F401
	HAS_REAL_FRAPPE = True
except ImportError:
	HAS_REAL_FRAPPE = False

if not HAS_REAL_FRAPPE:
	from worksight_hrms.tests.frappe_stub import install_frappe_stub


class TestCalculatorAndPipeline(unittest.TestCase):
	def test_late_and_overtime_calculators(self):
		from worksight_hrms.worksight_hrms.services.calculator import (
			compute_hourly_rate,
			compute_late_deduction,
			compute_late_metrics,
			compute_overtime_amount,
			compute_overtime_metrics,
			compute_shift_window,
		)

		rate = compute_hourly_rate(base_salary=20800, working_days_per_month=26, working_hours_per_day=8.0)
		self.assertEqual(rate, 100.0)

		shift_start, shift_end = compute_shift_window("2026-11-26", time(9, 0), time(17, 0))
		self.assertEqual(shift_start, datetime(2026, 11, 26, 9, 0))
		self.assertEqual(shift_end, datetime(2026, 11, 26, 17, 0))

		# Overnight shift wraps to next day
		night_start, night_end = compute_shift_window("2026-11-26", time(22, 0), time(6, 0))
		self.assertEqual(night_start, datetime(2026, 11, 26, 22, 0))
		self.assertEqual(night_end, datetime(2026, 11, 27, 6, 0))

		# Within grace -> not late
		within = compute_late_metrics(shift_start, datetime(2026, 11, 26, 9, 15), grace_minutes=15)
		self.assertFalse(within["is_late"])
		self.assertEqual(within["billable_late_minutes"], 0)

		# 45 min after shift start with 15 min grace -> 30 billable minutes -> 50.0 deduction
		late = compute_late_metrics(shift_start, datetime(2026, 11, 26, 9, 45), grace_minutes=15)
		self.assertTrue(late["is_late"])
		self.assertEqual(late["late_minutes"], 45)
		self.assertEqual(late["billable_late_minutes"], 30)
		self.assertEqual(compute_late_deduction(30, "Hourly Rate", hourly_rate=100.0), 50.0)
		self.assertEqual(compute_late_deduction(30, "Per Minute", rate_per_minute=2.0), 60.0)
		self.assertEqual(compute_late_deduction(30, "Fixed Per Incident", fixed_amount=75.0), 75.0)

		# 100 min extra after shift end, threshold 30, rounding 15 -> 90 mins (1.5 hrs)
		ot = compute_overtime_metrics(
			shift_end_dt=shift_end,
			actual_out_dt=datetime(2026, 11, 26, 18, 40),
			threshold_minutes=30,
			rounding_minutes=15,
		)
		self.assertTrue(ot["has_overtime"])
		self.assertEqual(ot["overtime_minutes"], 90)
		self.assertEqual(ot["overtime_hours"], 1.5)
		self.assertEqual(compute_overtime_amount(1.5, 100.0, 1.5), 225.0)

	def test_end_to_end_attendance_to_payroll_sync(self):
		if HAS_REAL_FRAPPE:
			self.skipTest("Runs with standalone in-memory stub")

		db = install_frappe_stub()
		import frappe
		from worksight_hrms.worksight_hrms.services.attendance_processor import (
			on_attendance_cancel,
			on_attendance_submit,
		)
		from worksight_hrms.worksight_hrms.services.payroll_sync import (
			on_late_record_cancel,
			on_late_record_submit,
			on_overtime_record_cancel,
			on_overtime_record_submit,
		)
		db.register_hook("WorkSight Late Record", "on_submit", on_late_record_submit)
		db.register_hook("WorkSight Late Record", "on_cancel", on_late_record_cancel)
		db.register_hook("WorkSight Overtime Record", "on_submit", on_overtime_record_submit)
		db.register_hook("WorkSight Overtime Record", "on_cancel", on_overtime_record_cancel)

		db.set_single(
			"WorkSight Settings",
			{
				"enabled": 1,
				"enable_late_tracking": 1,
				"late_grace_minutes": 15,
				"late_deduction_mode": "Hourly Rate",
				"late_hourly_multiplier": 1.0,
				"late_salary_component": "Late Deduction",
				"require_approval_for_late": 0,
				"enable_overtime_tracking": 1,
				"overtime_threshold_minutes": 30,
				"overtime_rounding_minutes": 15,
				"overtime_rate_mode": "From Base Salary Hourly Rate",
				"overtime_multiplier": 1.5,
				"holiday_overtime_multiplier": 2.0,
				"overtime_salary_component": "Overtime Pay",
				"require_approval_for_overtime": 0,
				"standard_working_days_per_month": 26,
				"standard_working_hours_per_day": 8.0,
				"auto_submit_additional_salary": 1,
				"overwrite_salary_structure_amount": 0,
			},
		)

		db.insert_doc(
			frappe.get_doc(
				{
					"doctype": "Company",
					"name": "Hasnet Tech",
					"default_holiday_list": "",
				}
			)
		)
		db.insert_doc(
			frappe.get_doc(
				{
					"doctype": "Employee",
					"name": "HR-EMP-00001",
					"company": "Hasnet Tech",
					"default_shift": "Day Shift",
					"status": "Active",
				}
			)
		)
		db.insert_doc(
			frappe.get_doc(
				{
					"doctype": "Shift Type",
					"name": "Day Shift",
					"start_time": time(9, 0),
					"end_time": time(17, 0),
					"enable_late_entry_marking": 1,
					"late_entry_grace_period": 15,
				}
			)
		)
		db.insert_doc(
			frappe.get_doc(
				{
					"doctype": "Salary Structure Assignment",
					"name": "SSA-0001",
					"employee": "HR-EMP-00001",
					"from_date": "2026-01-01",
					"base": 20800.0,
					"docstatus": 1,
				}
			)
		)

		attendance = frappe.get_doc(
			{
				"doctype": "Attendance",
				"name": "HR-ATT-2026-00001",
				"employee": "HR-EMP-00001",
				"company": "Hasnet Tech",
				"attendance_date": "2026-11-26",
				"status": "Present",
				"shift": "Day Shift",
				"in_time": datetime(2026, 11, 26, 9, 45),
				"out_time": datetime(2026, 11, 26, 18, 40),
				"working_hours": 8.92,
				"docstatus": 1,
			}
		)
		db.insert_doc(attendance)

		on_attendance_submit(attendance)

		late_records = db.get_all("WorkSight Late Record")
		ot_records = db.get_all("WorkSight Overtime Record")
		add_salaries = db.get_all("Additional Salary")

		self.assertEqual(len(late_records), 1)
		self.assertEqual(late_records[0]["billable_late_minutes"], 30)
		self.assertEqual(late_records[0]["deduction_amount"], 50.0)
		self.assertEqual(late_records[0]["status"], "Synced to Payroll")

		self.assertEqual(len(ot_records), 1)
		self.assertEqual(ot_records[0]["overtime_minutes"], 90)
		self.assertEqual(ot_records[0]["overtime_amount"], 225.0)
		self.assertEqual(ot_records[0]["status"], "Synced to Payroll")

		self.assertEqual(len(add_salaries), 2)
		components = {s["salary_component"]: s["amount"] for s in add_salaries}
		self.assertEqual(components["Late Deduction"], 50.0)
		self.assertEqual(components["Overtime Pay"], 225.0)

		# Cancelling Attendance cancels Late/Overtime and linked Additional Salaries
		on_attendance_cancel(attendance)
		self.assertEqual(late_records[0]["status"], "Cancelled")
		self.assertEqual(ot_records[0]["status"], "Cancelled")
		self.assertTrue(all(s["docstatus"] == 2 for s in add_salaries))


if __name__ == "__main__":
	unittest.main()
