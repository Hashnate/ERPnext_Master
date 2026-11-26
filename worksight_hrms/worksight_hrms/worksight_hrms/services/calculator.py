from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any


def compute_hourly_rate(
	base_salary: float,
	working_days_per_month: int = 26,
	working_hours_per_day: float = 8.0,
) -> float:
	"""Derive hourly rate from monthly base salary."""
	if not base_salary or base_salary <= 0:
		return 0.0
	if working_days_per_month <= 0 or working_hours_per_day <= 0:
		raise ValueError("Working days and working hours must be positive.")
	return round(float(base_salary) / (working_days_per_month * float(working_hours_per_day)), 4)


def _coerce_time(value: time | timedelta | str) -> time:
	if isinstance(value, time):
		return value
	if isinstance(value, timedelta):
		total_seconds = int(value.total_seconds()) % 86400
		hours, remainder = divmod(total_seconds, 3600)
		minutes, seconds = divmod(remainder, 60)
		return time(hour=hours, minute=minutes, second=seconds)
	if isinstance(value, str):
		parts = [int(p) for p in value.strip().split(":")]
		return time(
			hour=parts[0],
			minute=parts[1] if len(parts) > 1 else 0,
			second=parts[2] if len(parts) > 2 else 0,
		)
	raise ValueError(f"Unsupported shift time value: {value!r}")


def compute_shift_window(
	attendance_date: date | str,
	shift_start_time: time | timedelta | str,
	shift_end_time: time | timedelta | str,
) -> tuple[datetime, datetime]:
	"""Compute shift start and end datetimes, handling overnight shifts."""
	if isinstance(attendance_date, str):
		att_date = date.fromisoformat(attendance_date)
	else:
		att_date = attendance_date

	start_t = _coerce_time(shift_start_time)
	end_t = _coerce_time(shift_end_time)

	start_dt = datetime.combine(att_date, start_t)
	end_dt = datetime.combine(att_date, end_t)
	if end_dt <= start_dt:
		end_dt += timedelta(days=1)
	return start_dt, end_dt


def compute_late_metrics(
	shift_start_dt: datetime,
	actual_in_dt: datetime,
	grace_minutes: int = 0,
) -> dict[str, Any]:
	"""Calculate raw late minutes and billable late minutes after grace period."""
	delta_seconds = (actual_in_dt - shift_start_dt).total_seconds()
	if delta_seconds <= 0:
		return {"is_late": False, "late_minutes": 0, "billable_late_minutes": 0}

	late_minutes = int(delta_seconds // 60)
	grace = max(0, int(grace_minutes or 0))
	if late_minutes <= grace:
		return {"is_late": False, "late_minutes": late_minutes, "billable_late_minutes": 0}

	return {
		"is_late": True,
		"late_minutes": late_minutes,
		"billable_late_minutes": late_minutes - grace,
	}


def compute_late_deduction(
	billable_late_minutes: int,
	mode: str,
	hourly_rate: float = 0.0,
	rate_per_minute: float = 0.0,
	rate_per_hour: float = 0.0,
	fixed_amount: float = 0.0,
	hourly_multiplier: float = 1.0,
) -> float:
	"""Compute monetary deduction for late arrival based on configured mode."""
	if billable_late_minutes <= 0:
		return 0.0

	calculators = {
		"Hourly Rate": lambda: (billable_late_minutes / 60.0) * float(hourly_rate or 0) * float(hourly_multiplier or 1.0),
		"Per Minute": lambda: billable_late_minutes * float(rate_per_minute or 0),
		"Per Hour": lambda: (billable_late_minutes / 60.0) * float(rate_per_hour or 0),
		"Fixed Per Incident": lambda: float(fixed_amount or 0),
	}
	if mode not in calculators:
		raise ValueError(f"Unsupported late deduction mode: {mode!r}")
	return round(max(0.0, calculators[mode]()), 2)


def compute_overtime_metrics(
	shift_end_dt: datetime | None,
	actual_out_dt: datetime | None,
	working_hours: float = 0.0,
	standard_shift_hours: float = 8.0,
	threshold_minutes: int = 30,
	rounding_minutes: int = 15,
	is_holiday: bool = False,
	inside_minutes: int | None = None,
	scheduled_minutes: int | None = None,
) -> dict[str, Any]:
	"""Calculate qualifying overtime minutes and rounded overtime hours.

	When WorkSight `/timesheets` `inside_minutes` is provided, overtime is calculated from
	actual inside-office minutes (excluding time away) rather than raw check-out span.
	"""
	if inside_minutes is not None:
		inside_val = max(0, int(inside_minutes))
		if is_holiday:
			raw_ot_minutes = inside_val
		else:
			sched = (
				int(scheduled_minutes)
				if scheduled_minutes is not None and int(scheduled_minutes) > 0
				else int(round(float(standard_shift_hours or 0) * 60))
			)
			raw_ot_minutes = max(0, inside_val - sched)
	elif is_holiday:
		raw_ot_minutes = max(0, int(round(float(working_hours or 0) * 60)))
	elif shift_end_dt is not None and actual_out_dt is not None:
		delta_seconds = (actual_out_dt - shift_end_dt).total_seconds()
		raw_ot_minutes = max(0, int(delta_seconds // 60))
	else:
		extra_hours = max(0.0, float(working_hours or 0) - float(standard_shift_hours or 0))
		raw_ot_minutes = int(round(extra_hours * 60))

	threshold = max(0, int(threshold_minutes or 0))
	if raw_ot_minutes == 0 or raw_ot_minutes < threshold:
		return {"has_overtime": False, "overtime_minutes": 0, "overtime_hours": 0.0}

	rounding = max(0, int(rounding_minutes or 0))
	if rounding > 0:
		overtime_minutes = (raw_ot_minutes // rounding) * rounding
	else:
		overtime_minutes = raw_ot_minutes

	if overtime_minutes <= 0:
		return {"has_overtime": False, "overtime_minutes": 0, "overtime_hours": 0.0}

	return {
		"has_overtime": True,
		"overtime_minutes": overtime_minutes,
		"overtime_hours": round(overtime_minutes / 60.0, 2),
	}


def compute_overtime_amount(overtime_hours: float, hourly_rate: float, multiplier: float) -> float:
	"""Compute overtime pay amount."""
	if overtime_hours <= 0 or hourly_rate <= 0 or multiplier <= 0:
		return 0.0
	return round(float(overtime_hours) * float(hourly_rate) * float(multiplier), 2)
