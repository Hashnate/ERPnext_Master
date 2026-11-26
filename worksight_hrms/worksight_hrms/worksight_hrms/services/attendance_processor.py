from __future__ import annotations

from datetime import datetime
from typing import Any

import frappe
from frappe.utils import cint, flt, get_datetime, getdate

from worksight_hrms.worksight_hrms.services.calculator import (
	compute_hourly_rate,
	compute_late_deduction,
	compute_late_metrics,
	compute_overtime_amount,
	compute_overtime_metrics,
	compute_shift_window,
)

_WORKED_STATUSES = {"Present", "Half Day", "Work From Home"}


def _get_settings():
	return frappe.get_cached_doc("WorkSight Settings")


def _get_employee_hourly_rate(employee: str, settings) -> float:
	assignment = frappe.db.get_all(
		"Salary Structure Assignment",
		filters={"employee": employee, "docstatus": 1},
		fields=["base"],
		order_by="from_date desc",
		limit=1,
	)
	base_salary = flt(assignment[0]["base"]) if assignment else 0.0
	return compute_hourly_rate(
		base_salary=base_salary,
		working_days_per_month=cint(settings.standard_working_days_per_month) or 26,
		working_hours_per_day=flt(settings.standard_working_hours_per_day) or 8.0,
	)


def _resolve_shift_name(attendance_doc) -> str | None:
	if getattr(attendance_doc, "shift", None):
		return attendance_doc.shift

	att_date = getdate(attendance_doc.attendance_date)
	assigned = frappe.db.get_all(
		"Shift Assignment",
		filters={
			"employee": attendance_doc.employee,
			"docstatus": 1,
			"status": "Active",
			"start_date": ["<=", att_date],
		},
		fields=["shift_type", "end_date"],
		order_by="start_date desc",
		limit=5,
	)
	for row in assigned:
		if not row.get("end_date") or getdate(row["end_date"]) >= att_date:
			return row["shift_type"]

	return frappe.db.get_value("Employee", attendance_doc.employee, "default_shift")


def _resolve_in_out_times(attendance_doc) -> tuple[datetime | None, datetime | None]:
	in_time = get_datetime(attendance_doc.in_time) if getattr(attendance_doc, "in_time", None) else None
	out_time = get_datetime(attendance_doc.out_time) if getattr(attendance_doc, "out_time", None) else None
	if in_time and out_time:
		return in_time, out_time

	checkins = frappe.db.get_all(
		"Employee Checkin",
		filters={"attendance": attendance_doc.name},
		fields=["time", "log_type"],
		order_by="time asc",
	)
	if not checkins:
		att_date = getdate(attendance_doc.attendance_date)
		day_start = datetime.combine(att_date, datetime.min.time())
		day_end = datetime.combine(att_date, datetime.max.time())
		checkins = frappe.db.get_all(
			"Employee Checkin",
			filters={
				"employee": attendance_doc.employee,
				"time": ["between", [day_start, day_end]],
			},
			fields=["time", "log_type"],
			order_by="time asc",
		)

	if not checkins:
		return in_time, out_time

	in_punches = [get_datetime(c["time"]) for c in checkins if c.get("log_type") == "IN"]
	out_punches = [get_datetime(c["time"]) for c in checkins if c.get("log_type") == "OUT"]
	if not in_time:
		in_time = in_punches[0] if in_punches else get_datetime(checkins[0]["time"])
	if not out_time:
		out_time = out_punches[-1] if out_punches else get_datetime(checkins[-1]["time"])
	return in_time, out_time


def _is_holiday_for_employee(employee: str, company: str, attendance_date) -> bool:
	att_date = getdate(attendance_date)
	try:
		from hrms.utils.holiday_list import get_holiday_dates_for_employee

		if att_date in {getdate(d) for d in get_holiday_dates_for_employee(employee, att_date, att_date)}:
			return True
	except Exception:
		pass

	holiday_list = frappe.db.get_value("Employee", employee, "holiday_list")
	if not holiday_list and company:
		holiday_list = frappe.db.get_value("Company", company, "default_holiday_list")
	if not holiday_list:
		return False
	return bool(
		frappe.db.exists(
			"Holiday",
			{"parent": holiday_list, "holiday_date": att_date},
		)
	)


def _create_late_record(
	attendance_doc,
	shift_doc,
	shift_start_dt: datetime,
	actual_in_dt: datetime,
	grace_minutes: int,
	metrics: dict[str, Any],
	hourly_rate: float,
	settings,
) -> str | None:
	existing = frappe.db.get_value(
		"WorkSight Late Record",
		{"attendance": attendance_doc.name, "docstatus": ["!=", 2]},
		"name",
	)
	if existing:
		return existing

	deduction_amount = compute_late_deduction(
		billable_late_minutes=metrics["billable_late_minutes"],
		mode=settings.late_deduction_mode or "Hourly Rate",
		hourly_rate=hourly_rate,
		rate_per_minute=flt(settings.late_rate_per_minute),
		rate_per_hour=flt(settings.late_rate_per_hour),
		fixed_amount=flt(settings.late_fixed_amount),
		hourly_multiplier=flt(settings.late_hourly_multiplier) or 1.0,
	)

	doc = frappe.get_doc(
		{
			"doctype": "WorkSight Late Record",
			"employee": attendance_doc.employee,
			"company": attendance_doc.company,
			"attendance_date": attendance_doc.attendance_date,
			"attendance": attendance_doc.name,
			"shift": shift_doc.name if shift_doc else None,
			"shift_start_time": shift_start_dt,
			"actual_in_time": actual_in_dt,
			"grace_minutes": grace_minutes,
			"late_minutes": metrics["late_minutes"],
			"billable_late_minutes": metrics["billable_late_minutes"],
			"hourly_rate": hourly_rate,
			"deduction_amount": deduction_amount,
			"status": "Pending",
		}
	)
	doc.insert(ignore_permissions=True)
	if not cint(settings.require_approval_for_late):
		doc.submit()
	return doc.name


def _create_overtime_record(
	attendance_doc,
	shift_doc,
	shift_end_dt: datetime | None,
	actual_out_dt: datetime | None,
	working_hours: float,
	metrics: dict[str, Any],
	is_holiday: bool,
	hourly_rate: float,
	settings,
) -> str | None:
	existing = frappe.db.get_value(
		"WorkSight Overtime Record",
		{"attendance": attendance_doc.name, "docstatus": ["!=", 2]},
		"name",
	)
	if existing:
		return existing

	effective_rate = (
		flt(settings.fixed_overtime_hourly_rate)
		if settings.overtime_rate_mode == "Fixed Hourly Rate"
		else hourly_rate
	)
	multiplier = (
		flt(settings.holiday_overtime_multiplier) or 2.0
		if is_holiday
		else flt(settings.overtime_multiplier) or 1.5
	)
	overtime_amount = compute_overtime_amount(
		overtime_hours=metrics["overtime_hours"],
		hourly_rate=effective_rate,
		multiplier=multiplier,
	)

	doc = frappe.get_doc(
		{
			"doctype": "WorkSight Overtime Record",
			"employee": attendance_doc.employee,
			"company": attendance_doc.company,
			"attendance_date": attendance_doc.attendance_date,
			"attendance": attendance_doc.name,
			"shift": shift_doc.name if shift_doc else None,
			"shift_end_time": shift_end_dt,
			"actual_out_time": actual_out_dt,
			"working_hours": working_hours,
			"overtime_minutes": metrics["overtime_minutes"],
			"overtime_hours": metrics["overtime_hours"],
			"is_holiday": 1 if is_holiday else 0,
			"hourly_rate": effective_rate,
			"multiplier": multiplier,
			"overtime_amount": overtime_amount,
			"status": "Pending",
		}
	)
	doc.insert(ignore_permissions=True)
	if not cint(settings.require_approval_for_overtime):
		doc.submit()
	return doc.name


def evaluate_attendance(attendance_doc, settings=None) -> dict[str, Any]:
	"""Evaluate submitted Attendance into WorkSight Late and Overtime Records."""
	settings = settings or _get_settings()
	if not cint(settings.enabled):
		return {"skipped": "disabled"}

	if attendance_doc.status not in _WORKED_STATUSES:
		return {"skipped": f"status:{attendance_doc.status}"}

	shift_name = _resolve_shift_name(attendance_doc)
	shift_doc = frappe.get_cached_doc("Shift Type", shift_name) if shift_name else None
	in_time, out_time = _resolve_in_out_times(attendance_doc)

	shift_start_dt = None
	shift_end_dt = None
	standard_shift_hours = flt(settings.standard_working_hours_per_day) or 8.0
	if shift_doc and shift_doc.start_time is not None and shift_doc.end_time is not None:
		shift_start_dt, shift_end_dt = compute_shift_window(
			attendance_doc.attendance_date,
			shift_doc.start_time,
			shift_doc.end_time,
		)
		standard_shift_hours = round((shift_end_dt - shift_start_dt).total_seconds() / 3600.0, 2)

	hourly_rate = _get_employee_hourly_rate(attendance_doc.employee, settings)
	is_holiday = _is_holiday_for_employee(
		attendance_doc.employee,
		attendance_doc.company,
		attendance_doc.attendance_date,
	)

	working_hours = flt(getattr(attendance_doc, "working_hours", 0))
	if working_hours <= 0 and in_time and out_time and out_time > in_time:
		working_hours = round((out_time - in_time).total_seconds() / 3600.0, 2)

	created: dict[str, Any] = {"late_record": None, "overtime_record": None}

	if cint(settings.enable_late_tracking) and shift_start_dt and in_time and not is_holiday:
		grace_minutes = (
			cint(shift_doc.late_entry_grace_period)
			if shift_doc
			and cint(
				getattr(shift_doc, "enable_late_entry_marking", getattr(shift_doc, "enable_late_entry", 0))
			)
			else cint(settings.late_grace_minutes)
		)
		late_metrics = compute_late_metrics(shift_start_dt, in_time, grace_minutes=grace_minutes)
		if late_metrics["is_late"]:
			created["late_record"] = _create_late_record(
				attendance_doc=attendance_doc,
				shift_doc=shift_doc,
				shift_start_dt=shift_start_dt,
				actual_in_dt=in_time,
				grace_minutes=grace_minutes,
				metrics=late_metrics,
				hourly_rate=hourly_rate,
				settings=settings,
			)

	if cint(settings.enable_overtime_tracking):
		ot_metrics = compute_overtime_metrics(
			shift_end_dt=shift_end_dt,
			actual_out_dt=out_time,
			working_hours=working_hours,
			standard_shift_hours=standard_shift_hours,
			threshold_minutes=cint(settings.overtime_threshold_minutes),
			rounding_minutes=cint(settings.overtime_rounding_minutes),
			is_holiday=is_holiday,
		)
		if ot_metrics["has_overtime"]:
			created["overtime_record"] = _create_overtime_record(
				attendance_doc=attendance_doc,
				shift_doc=shift_doc,
				shift_end_dt=shift_end_dt,
				actual_out_dt=out_time,
				working_hours=working_hours,
				metrics=ot_metrics,
				is_holiday=is_holiday,
				hourly_rate=hourly_rate,
				settings=settings,
			)

	return created


def on_attendance_submit(doc, method=None) -> None:
	evaluate_attendance(doc)


def on_attendance_cancel(doc, method=None) -> None:
	for doctype in ("WorkSight Late Record", "WorkSight Overtime Record"):
		names = frappe.db.get_all(
			doctype,
			filters={"attendance": doc.name, "docstatus": ["!=", 2]},
			pluck="name",
		)
		for name in names:
			rec = frappe.get_doc(doctype, name)
			if rec.docstatus == 1:
				rec.cancel()
			else:
				frappe.delete_doc(doctype, name, ignore_permissions=True)


@frappe.whitelist()
def process_attendance_range(from_date: str, to_date: str, company: str | None = None) -> dict[str, Any]:
	"""Evaluate submitted Attendance records within a date range into Late & Overtime records."""
	frappe.only_for(("System Manager", "HR Manager", "HR User"))
	filters: dict[str, Any] = {
		"docstatus": 1,
		"attendance_date": ["between", [getdate(from_date), getdate(to_date)]],
		"status": ["in", list(_WORKED_STATUSES)],
	}
	if company:
		filters["company"] = company

	attendance_names = frappe.db.get_all("Attendance", filters=filters, pluck="name")
	settings = _get_settings()
	late_count = 0
	ot_count = 0
	for name in attendance_names:
		att = frappe.get_doc("Attendance", name)
		res = evaluate_attendance(att, settings=settings)
		if res.get("late_record"):
			late_count += 1
		if res.get("overtime_record"):
			ot_count += 1

	return {
		"attendance_evaluated": len(attendance_names),
		"late_records": late_count,
		"overtime_records": ot_count,
	}
