from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, get_datetime, getdate

from worksight_hrms.worksight_hrms.services.security import (
	format_office_iso_timestamp,
	parse_checkin_timestamp,
)


class WorkSightAPIError(Exception):
	"""Raised when the WorkSight REST API returns an HTTP or payload error."""


class WorkSightClient:
	"""HTTP client for WorkSight REST API 1.0.0 (`/api/v1`)."""

	def __init__(self, base_url: str, api_key: str, timeout: int = 20):
		self.base_url = (base_url or "https://worksight.hashnate.com/api/v1").rstrip("/")
		if not self.base_url.startswith("https://"):
			raise WorkSightAPIError("WorkSight API Base URL must use HTTPS.")
		self.api_key = (api_key or "").strip()
		self.timeout = timeout
		if not self.api_key:
			raise WorkSightAPIError("WorkSight API Key is not configured in WorkSight Settings.")

	def _request(
		self,
		method: str,
		path: str,
		params: dict[str, Any] | None = None,
		body: dict[str, Any] | None = None,
	) -> dict[str, Any]:
		url = f"{self.base_url}/{path.lstrip('/')}"
		if params:
			clean_params = {k: v for k, v in params.items() if v is not None and v != ""}
			if clean_params:
				url = f"{url}?{urllib.parse.urlencode(clean_params)}"

		data = json.dumps(body).encode("utf-8") if body is not None else None
		headers = {
			"Authorization": f"Bearer {self.api_key}",
			"Accept": "application/json",
			"User-Agent": "worksight_hrms/1.0",
		}
		if data is not None:
			headers["Content-Type"] = "application/json"

		req = urllib.request.Request(url, data=data, method=method.upper(), headers=headers)
		try:
			with urllib.request.urlopen(req, timeout=self.timeout) as resp:
				raw = resp.read().decode("utf-8")
				parsed = json.loads(raw) if raw else {}
				if isinstance(parsed, dict) and parsed.get("success") is False:
					raise WorkSightAPIError(parsed.get("message") or f"WorkSight API {method} {path} failed.")
				return parsed
		except urllib.error.HTTPError as exc:
			detail = exc.read().decode("utf-8", errors="replace")
			message = detail
			try:
				err_json = json.loads(detail)
				if isinstance(err_json, dict) and err_json.get("message"):
					message = err_json["message"]
			except ValueError:
				pass
			raise WorkSightAPIError(f"WorkSight API {method} {path} failed ({exc.code}): {message}") from exc
		except urllib.error.URLError as exc:
			raise WorkSightAPIError(f"WorkSight API connection error for {path}: {exc.reason}") from exc

	def _paginate(self, path: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
		items: list[dict[str, Any]] = []
		cursor: str | None = None
		base_params = dict(params or {})
		while True:
			query = {**base_params, "cursor": cursor} if cursor else dict(base_params)
			resp = self._request("GET", path, params=query)
			items.extend(resp.get("data") or [])
			page = resp.get("page") or {}
			cursor = page.get("nextCursor")
			if not cursor:
				break
		return items

	# --- Employees & Organization ---

	def list_employees(
		self,
		active: bool | None = None,
		updated_since: str | None = None,
		limit: int = 100,
	) -> list[dict[str, Any]]:
		params: dict[str, Any] = {"limit": limit}
		if active is not None:
			params["active"] = "true" if active else "false"
		if updated_since:
			params["updatedSince"] = updated_since
		return self._paginate("/employees", params=params)

	def get_employee(self, employee_code: str) -> dict[str, Any]:
		code = urllib.parse.quote(employee_code.strip())
		return (self._request("GET", f"/employees/{code}")).get("data") or {}

	def upsert_employee(self, employee_code: str, payload: dict[str, Any]) -> dict[str, Any]:
		code = urllib.parse.quote(employee_code.strip())
		return (self._request("PUT", f"/employees/{code}", body=payload)).get("data") or {}

	def create_enrolment_link(self, employee_code: str) -> dict[str, Any]:
		code = urllib.parse.quote(employee_code.strip())
		return (self._request("POST", f"/employees/{code}/enrolment-link")).get("data") or {}

	def list_departments(self) -> list[dict[str, Any]]:
		return (self._request("GET", "/departments")).get("data") or []

	def list_work_schedules(self) -> list[dict[str, Any]]:
		return (self._request("GET", "/work-schedules")).get("data") or []

	# --- Attendance, Timesheets & Live Presence ---

	def list_attendance(
		self,
		from_date: str | None = None,
		to_date: str | None = None,
		employee_code: str | None = None,
		updated_since: str | None = None,
		limit: int = 100,
	) -> list[dict[str, Any]]:
		params: dict[str, Any] = {"limit": limit}
		if from_date:
			params["from"] = from_date
		if to_date:
			params["to"] = to_date
		if employee_code:
			params["employeeCode"] = employee_code
		if updated_since:
			params["updatedSince"] = updated_since
		return self._paginate("/attendance", params=params)

	def list_timesheets(
		self,
		from_date: str,
		to_date: str,
		employee_code: str | None = None,
		away_after_min: int | None = None,
	) -> list[dict[str, Any]]:
		"""Fetch /timesheets, automatically chunking ranges longer than the 92-day API limit."""
		start = getdate(from_date)
		end = getdate(to_date)
		if end < start:
			raise WorkSightAPIError("to_date cannot be earlier than from_date.")

		merged: dict[str, dict[str, Any]] = {}
		cursor_date = start
		while cursor_date <= end:
			chunk_end = min(end, cursor_date + timedelta(days=91))
			params: dict[str, Any] = {
				"from": str(cursor_date),
				"to": str(chunk_end),
			}
			if employee_code:
				params["employeeCode"] = employee_code
			if away_after_min is not None:
				params["awayAfterMin"] = int(away_after_min)

			rows = (self._request("GET", "/timesheets", params=params)).get("data") or []
			for row in rows:
				code = row["employeeCode"]
				if code not in merged:
					merged[code] = dict(row, days=list(row.get("days") or []))
				else:
					merged[code]["days"].extend(row.get("days") or [])
			cursor_date = chunk_end + timedelta(days=1)

		return list(merged.values())

	def get_presence_now(self, away_after_min: int | None = None) -> dict[str, Any]:
		params: dict[str, Any] = {}
		if away_after_min is not None:
			params["awayAfterMin"] = int(away_after_min)
		return self._request("GET", "/presence/now", params=params)

	def manual_check_in(self, employee_code: str, at: str | None = None) -> dict[str, Any]:
		body: dict[str, Any] = {"employeeCode": employee_code.strip()}
		if at:
			body["at"] = at
		return (self._request("POST", "/attendance/check-in", body=body)).get("data") or {}

	def manual_check_out(self, employee_code: str, at: str | None = None) -> dict[str, Any]:
		body: dict[str, Any] = {"employeeCode": employee_code.strip()}
		if at:
			body["at"] = at
		return (self._request("POST", "/attendance/check-out", body=body)).get("data") or {}

	# --- Webhooks ---

	def list_webhooks(self) -> list[dict[str, Any]]:
		return (self._request("GET", "/webhooks")).get("data") or []

	def register_webhook(
		self,
		url: str,
		events: list[str] | None = None,
		away_after_min: int = 15,
		description: str = "ERPNext HRMS WorkSight Integration",
	) -> dict[str, Any]:
		payload: dict[str, Any] = {
			"url": url,
			"awayAfterMin": away_after_min,
			"description": description,
		}
		if events:
			payload["events"] = events
		return (self._request("POST", "/webhooks", body=payload)).get("data") or {}

	def delete_webhook(self, webhook_id: str) -> dict[str, Any]:
		return self._request("DELETE", f"/webhooks/{urllib.parse.quote(webhook_id)}")

	def test_webhook(self, webhook_id: str) -> dict[str, Any]:
		return (self._request("POST", f"/webhooks/{urllib.parse.quote(webhook_id)}/test")).get("data") or {}

	def list_webhook_deliveries(self, webhook_id: str, limit: int = 50) -> list[dict[str, Any]]:
		return (
			self._request(
				"GET",
				f"/webhooks/{urllib.parse.quote(webhook_id)}/deliveries",
				params={"limit": limit},
			)
		).get("data") or []


def _get_settings():
	return frappe.get_cached_doc("WorkSight Settings")


def _get_client(settings=None) -> WorkSightClient:
	settings = settings or _get_settings()
	api_key = settings.get_password("api_key", raise_exception=False) if settings.api_key else ""
	return WorkSightClient(base_url=settings.api_base_url, api_key=api_key)


def _get_office_timezone(settings=None) -> str:
	settings = settings or _get_settings()
	return (
		getattr(settings, "default_timezone", None)
		or frappe.db.get_single_value("System Settings", "time_zone")
		or "Asia/Colombo"
	)


def _get_default_company(settings) -> str:
	if getattr(settings, "default_company", None):
		return settings.default_company
	default_company = frappe.db.get_single_value("Global Defaults", "default_company")
	if default_company:
		return default_company
	companies = frappe.db.get_all("Company", pluck="name", limit=1)
	if companies:
		return companies[0]
	frappe.throw(_("Please set Default Company in WorkSight Settings."))
	return ""


def _ensure_department(department_name: str | None, company: str) -> str | None:
	if not department_name:
		return None
	existing = frappe.db.get_value(
		"Department",
		{"department_name": department_name, "company": company},
		"name",
	)
	if existing:
		return existing
	if frappe.db.exists("Department", department_name):
		return department_name
	doc = frappe.get_doc(
		{
			"doctype": "Department",
			"department_name": department_name,
			"company": company,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def _ensure_designation(job_title: str | None) -> str | None:
	if not job_title:
		return None
	if frappe.db.exists("Designation", job_title):
		return job_title
	doc = frappe.get_doc({"doctype": "Designation", "designation_name": job_title})
	doc.insert(ignore_permissions=True)
	return doc.name


def _resolve_employment_type(employment_type: str | None) -> str | None:
	if not employment_type:
		return None
	clean = employment_type.strip()
	if frappe.db.exists("Employment Type", clean):
		return clean
	all_types = frappe.db.get_all("Employment Type", pluck="name")
	for candidate in all_types:
		if candidate.lower() == clean.lower():
			return candidate
	doc = frappe.get_doc({"doctype": "Employment Type", "employee_type_name": clean})
	doc.insert(ignore_permissions=True)
	return doc.name


def _format_shift_time(hh_mm: str) -> str:
	raw = (hh_mm or "").strip()
	return f"{raw}:00" if len(raw) == 5 else raw


def _ensure_shift_type(schedule: dict[str, Any], process_after: str | None = None) -> str:
	name = schedule["name"]
	start_time = _format_shift_time(schedule["startTime"])
	end_time = _format_shift_time(schedule["endTime"])
	grace = cint(schedule.get("graceMinutes", 0))

	if frappe.db.exists("Shift Type", name):
		shift = frappe.get_doc("Shift Type", name)
		shift.start_time = start_time
		shift.end_time = end_time
		shift.enable_auto_attendance = 1
		shift.determine_check_in_and_check_out = "Alternating entries as IN and OUT during the same shift"
		shift.working_hours_calculation_based_on = "First Check-in and Last Check-out"
		shift.begin_check_in_before_shift_start_time = shift.begin_check_in_before_shift_start_time or 60
		shift.allow_check_out_after_shift_end_time = shift.allow_check_out_after_shift_end_time or 240
		shift.enable_late_entry_marking = 1
		shift.late_entry_grace_period = grace
		if process_after and (not shift.process_attendance_after or str(shift.process_attendance_after) > process_after):
			shift.process_attendance_after = process_after
		shift.save(ignore_permissions=True)
		return shift.name

	shift = frappe.get_doc(
		{
			"doctype": "Shift Type",
			"__newname": name,
			"start_time": start_time,
			"end_time": end_time,
			"enable_auto_attendance": 1,
			"determine_check_in_and_check_out": "Alternating entries as IN and OUT during the same shift",
			"working_hours_calculation_based_on": "First Check-in and Last Check-out",
			"begin_check_in_before_shift_start_time": 60,
			"allow_check_out_after_shift_end_time": 240,
			"process_attendance_after": process_after or str(date.today() - timedelta(days=7)),
			"enable_late_entry_marking": 1,
			"late_entry_grace_period": grace,
		}
	)
	shift.insert(ignore_permissions=True)
	return shift.name


def _split_full_name(full_name: str) -> tuple[str, str]:
	parts = (full_name or "Employee").strip().split(None, 1)
	first = parts[0]
	last = parts[1] if len(parts) > 1 else ""
	return first, last


def _find_erp_employee(employee_code: str, email: str | None = None) -> str | None:
	candidates = [employee_code.strip()]
	upper_code = candidates[0].upper()
	if upper_code not in candidates:
		candidates.append(upper_code)

	for cand in candidates:
		for field in ("attendance_device_id", "employee_number", "name"):
			match = frappe.db.get_value("Employee", {field: cand}, "name")
			if match:
				return match
	if email:
		match = frappe.db.get_value("Employee", {"company_email": email}, "name")
		if match:
			return match
	return None


def _resolve_employee_code(employee: str) -> str:
	doc = frappe.db.get_value(
		"Employee",
		employee,
		["name", "attendance_device_id", "employee_number"],
		as_dict=True,
	)
	if not doc:
		return employee.strip().upper()
	code = doc.attendance_device_id or doc.employee_number or doc.name
	return str(code).strip().upper()


def sync_work_schedules_and_employees(
	settings=None,
	client: WorkSightClient | None = None,
	incremental: bool = False,
	process_after: str | None = None,
) -> dict[str, Any]:
	"""Sync WorkSight Departments, WorkSchedules (Shift Type), and Employees into ERPNext HRMS."""
	settings = settings or _get_settings()
	client = client or _get_client(settings)
	company = _get_default_company(settings)

	departments = client.list_departments()
	synced_departments = 0
	for dept in departments:
		if dept.get("name"):
			_ensure_department(dept["name"], company)
			synced_departments += 1

	schedules = client.list_work_schedules()
	synced_shifts: list[str] = []
	for sched in schedules:
		synced_shifts.append(_ensure_shift_type(sched, process_after=process_after))

	updated_since = settings.last_employee_sync if incremental and getattr(settings, "last_employee_sync", None) else None
	employees = client.list_employees(updated_since=updated_since)
	created = 0
	updated = 0
	skipped = 0
	max_updated_at: str | None = None

	for ws_emp in employees:
		code = str(ws_emp["employeeCode"]).strip().upper()
		if ws_emp.get("updatedAt") and (max_updated_at is None or ws_emp["updatedAt"] > max_updated_at):
			max_updated_at = ws_emp["updatedAt"]

		ws_sched = ws_emp.get("workSchedule")
		shift_name = _ensure_shift_type(ws_sched, process_after=process_after) if isinstance(ws_sched, dict) and ws_sched.get("name") else None
		dept_name = _ensure_department(ws_emp.get("department"), company)
		desig_name = _ensure_designation(ws_emp.get("jobTitle"))
		emp_type = _resolve_employment_type(ws_emp.get("employmentType"))

		erp_emp_name = _find_erp_employee(code, ws_emp.get("email"))
		first_name, last_name = _split_full_name(ws_emp.get("fullName", code))
		target_status = "Active" if ws_emp.get("isActive", True) else "Left"

		if erp_emp_name:
			emp_doc = frappe.get_doc("Employee", erp_emp_name)
			emp_doc.attendance_device_id = code
			emp_doc.employee_number = code
			emp_doc.first_name = first_name
			if last_name:
				emp_doc.last_name = last_name
			if ws_emp.get("email"):
				emp_doc.company_email = ws_emp["email"]
			if ws_emp.get("phoneNumber"):
				emp_doc.cell_number = ws_emp["phoneNumber"]
			if dept_name:
				emp_doc.department = dept_name
			if desig_name:
				emp_doc.designation = desig_name
			if emp_type:
				emp_doc.employment_type = emp_type
			if shift_name:
				emp_doc.default_shift = shift_name
			if ws_emp.get("joiningDate"):
				emp_doc.date_of_joining = ws_emp["joiningDate"]
			emp_doc.status = target_status
			emp_doc.save(ignore_permissions=True)
			updated += 1
		elif cint(settings.auto_create_missing_employees):
			emp_doc = frappe.get_doc(
				{
					"doctype": "Employee",
					"first_name": first_name,
					"last_name": last_name,
					"gender": "Prefer not to say",
					"date_of_birth": "1995-01-01",
					"date_of_joining": ws_emp.get("joiningDate") or str(date.today()),
					"company": company,
					"status": target_status,
					"attendance_device_id": code,
					"employee_number": code,
					"company_email": ws_emp.get("email"),
					"cell_number": ws_emp.get("phoneNumber"),
					"department": dept_name,
					"designation": desig_name,
					"employment_type": emp_type,
					"default_shift": shift_name,
				}
			)
			emp_doc.insert(ignore_permissions=True)
			created += 1
		else:
			skipped += 1

	if max_updated_at:
		frappe.db.set_value("WorkSight Settings", "WorkSight Settings", "last_employee_sync", max_updated_at)

	return {
		"departments_synced": synced_departments,
		"shifts_synced": len(synced_shifts),
		"employees_created": created,
		"employees_updated": updated,
		"employees_skipped": skipped,
	}


def sync_timesheets_from_worksight(
	from_date: str,
	to_date: str,
	employee_code: str | None = None,
	away_after_min: int | None = None,
	settings=None,
	client: WorkSightClient | None = None,
) -> dict[str, Any]:
	"""Sync `/timesheets` (actual inside-office minutes, excluding time away) into WorkSight Daily Timesheet."""
	settings = settings or _get_settings()
	client = client or _get_client(settings)
	target_tz = _get_office_timezone(settings)
	away_min = away_after_min if away_after_min is not None else (cint(getattr(settings, "away_after_minutes", 15)) or 15)

	rows = client.list_timesheets(
		from_date=from_date,
		to_date=to_date,
		employee_code=employee_code,
		away_after_min=away_min,
	)

	upserted = 0
	skipped_unmapped = 0

	for emp_ts in rows:
		code = str(emp_ts.get("employeeCode") or "").strip().upper()
		erp_emp = _find_erp_employee(code)
		if not erp_emp:
			skipped_unmapped += 1
			continue

		scheduled_minutes = cint(emp_ts.get("scheduledMinutesPerDay"))
		for day in emp_ts.get("days") or []:
			att_date = day.get("date")
			if not att_date:
				continue
			doc_name = f"{erp_emp}-{att_date}"

			check_in_str = None
			if day.get("checkIn"):
				check_in_str = parse_checkin_timestamp(day["checkIn"], target_timezone=target_tz).strftime("%Y-%m-%d %H:%M:%S")
			last_seen_str = None
			if day.get("lastSeen"):
				last_seen_str = parse_checkin_timestamp(day["lastSeen"], target_timezone=target_tz).strftime("%Y-%m-%d %H:%M:%S")

			inside_min = cint(day.get("insideMinutes"))
			existing_att = frappe.db.get_value(
				"Attendance",
				{"employee": erp_emp, "attendance_date": att_date, "docstatus": ["!=", 2]},
				"name",
			)

			payload = {
				"employee": erp_emp,
				"employee_code": code,
				"attendance_date": att_date,
				"attendance": existing_att,
				"is_working_day": 1 if day.get("isWorkingDay") is not False else 0,
				"present": 1 if day.get("present") else 0,
				"measured": 1 if day.get("measured") else 0,
				"check_in": check_in_str,
				"last_seen": last_seen_str,
				"scheduled_minutes": scheduled_minutes,
				"inside_minutes": inside_min,
				"inside_hours": round(inside_min / 60.0, 2),
				"away_minutes": cint(day.get("awayMinutes")),
				"times_away": cint(day.get("timesAway")),
				"span_minutes": cint(day.get("spanMinutes")),
				"is_late": 1 if day.get("isLate") else 0,
				"late_by_minutes": cint(day.get("lateByMinutes")),
				"is_early_departure": 1 if day.get("isEarlyDeparture") else 0,
			}

			if frappe.db.exists("WorkSight Daily Timesheet", doc_name):
				doc = frappe.get_doc("WorkSight Daily Timesheet", doc_name)
				doc.update(payload)
				doc.save(ignore_permissions=True)
			else:
				doc = frappe.get_doc({"doctype": "WorkSight Daily Timesheet", **payload})
				doc.insert(ignore_permissions=True)
			upserted += 1

	return {
		"employees_fetched": len(rows),
		"daily_timesheets_upserted": upserted,
		"skipped_unmapped": skipped_unmapped,
	}


def _upsert_checkin_from_attendance(
	employee: str,
	employee_code: str,
	event_id: str,
	iso_time: str,
	log_type: str,
	raw_record: dict[str, Any],
	target_tz: str,
	skip_auto_attendance: int,
) -> tuple[str, datetime]:
	dt = parse_checkin_timestamp(iso_time, target_timezone=target_tz)
	time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
	source_label = f"WorkSight-{raw_record.get('source') or 'API'}"

	existing_log = frappe.db.get_value(
		"WorkSight Checkin Log",
		{"event_id": event_id},
		["name", "employee_checkin"],
		as_dict=True,
	)
	if existing_log and existing_log.employee_checkin and frappe.db.exists("Employee Checkin", existing_log.employee_checkin):
		checkin_doc = frappe.get_doc("Employee Checkin", existing_log.employee_checkin)
		if str(checkin_doc.time) != time_str and not checkin_doc.attendance:
			checkin_doc.time = time_str
			checkin_doc.save(ignore_permissions=True)
			frappe.db.set_value("WorkSight Checkin Log", existing_log.name, "checkin_time", time_str)
			return "updated", dt
		return "unchanged", dt

	exact_existing = frappe.db.get_value(
		"Employee Checkin",
		{"employee": employee, "time": time_str, "log_type": log_type},
		"name",
	)
	if exact_existing:
		if not existing_log:
			frappe.get_doc(
				{
					"doctype": "WorkSight Checkin Log",
					"event_id": event_id,
					"status": "Processed",
					"checkin_time": time_str,
					"log_type": log_type,
					"employee_identifier": employee_code,
					"matched_employee": employee,
					"employee_checkin": exact_existing,
					"device_id": source_label,
					"raw_payload": json.dumps(raw_record, indent=2, default=str),
				}
			).insert(ignore_permissions=True)
		return "unchanged", dt

	checkin_doc = frappe.get_doc(
		{
			"doctype": "Employee Checkin",
			"employee": employee,
			"time": time_str,
			"log_type": log_type,
			"device_id": source_label,
			"skip_auto_attendance": skip_auto_attendance,
		}
	)
	checkin_doc.insert(ignore_permissions=True)

	frappe.get_doc(
		{
			"doctype": "WorkSight Checkin Log",
			"event_id": event_id,
			"status": "Processed",
			"checkin_time": time_str,
			"log_type": log_type,
			"employee_identifier": employee_code,
			"matched_employee": employee,
			"employee_checkin": checkin_doc.name,
			"device_id": source_label,
			"raw_payload": json.dumps(raw_record, indent=2, default=str),
		}
	).insert(ignore_permissions=True)
	return "created", dt


def sync_attendance_from_worksight(
	from_date: str | None = None,
	to_date: str | None = None,
	updated_since: str | None = None,
	process_auto_attendance: bool = True,
	finalize_today: bool = False,
	sync_timesheets_first: bool = True,
	settings=None,
	client: WorkSightClient | None = None,
) -> dict[str, Any]:
	"""Pull attendance & timesheets from WorkSight API into ERPNext and trigger HRMS Auto Attendance."""
	settings = settings or _get_settings()
	client = client or _get_client(settings)
	target_tz = _get_office_timezone(settings)
	skip_auto = 0 if cint(settings.auto_trigger_shift_sync) else 1

	if not from_date and not updated_since:
		if getattr(settings, "last_attendance_sync", None):
			updated_since = settings.last_attendance_sync
		else:
			from_date = str(date.today() - timedelta(days=7))
			to_date = str(date.today())

	records = client.list_attendance(from_date=from_date, to_date=to_date, updated_since=updated_since)
	created = 0
	updated = 0
	skipped_unmapped = 0
	touched_shifts: set[str] = set()
	max_punch_dt: datetime | None = None
	max_updated_at: str | None = None
	min_date: str | None = None
	max_date: str | None = None

	for rec in records:
		code = str(rec.get("employeeCode") or "").strip().upper()
		emp_name = _find_erp_employee(code)
		if not emp_name:
			skipped_unmapped += 1
			continue

		att_id = rec["id"]
		rec_date = rec.get("date")
		if rec_date:
			if min_date is None or rec_date < min_date:
				min_date = rec_date
			if max_date is None or rec_date > max_date:
				max_date = rec_date
		if rec.get("updatedAt") and (max_updated_at is None or rec["updatedAt"] > max_updated_at):
			max_updated_at = rec["updatedAt"]

		for suffix, field, log_type in (
			("in", "checkIn", "IN"),
			("out", "checkOut", "OUT"),
		):
			iso_val = rec.get(field)
			if not iso_val:
				continue
			outcome, dt = _upsert_checkin_from_attendance(
				employee=emp_name,
				employee_code=code,
				event_id=f"ws-att-{att_id}-{suffix}",
				iso_time=iso_val,
				log_type=log_type,
				raw_record=rec,
				target_tz=target_tz,
				skip_auto_attendance=skip_auto,
			)
			if outcome == "created":
				created += 1
			elif outcome == "updated":
				updated += 1
			if max_punch_dt is None or dt > max_punch_dt:
				max_punch_dt = dt

		emp_shift = frappe.db.get_value("Employee", emp_name, "default_shift")
		if emp_shift:
			touched_shifts.add(emp_shift)

	if max_updated_at:
		frappe.db.set_value("WorkSight Settings", "WorkSight Settings", "last_attendance_sync", max_updated_at)

	ts_summary: dict[str, Any] = {}
	ts_from = from_date or min_date
	ts_to = to_date or max_date or ts_from
	if sync_timesheets_first and ts_from and ts_to:
		ts_summary = sync_timesheets_from_worksight(
			from_date=str(ts_from),
			to_date=str(ts_to),
			settings=settings,
			client=client,
		)

	shifts_processed = 0
	if process_auto_attendance and touched_shifts:
		cutoff_date = date.today() if finalize_today else (date.today() - timedelta(days=1))
		if to_date and getdate(to_date) < cutoff_date:
			cutoff_date = getdate(to_date)
		sync_cutoff = f"{cutoff_date} 23:59:59"
		if max_punch_dt and finalize_today:
			sync_cutoff = (max_punch_dt + timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
		process_after = str(getdate(min_date)) if min_date else None
		for shift_name in sorted(touched_shifts):
			shift_doc = frappe.get_doc("Shift Type", shift_name)
			if not cint(shift_doc.enable_auto_attendance):
				continue
			changed = False
			if process_after and (not shift_doc.process_attendance_after or str(shift_doc.process_attendance_after) > process_after):
				shift_doc.process_attendance_after = process_after
				changed = True
			if not shift_doc.last_sync_of_checkin or get_datetime(shift_doc.last_sync_of_checkin) < get_datetime(sync_cutoff):
				shift_doc.last_sync_of_checkin = sync_cutoff
				changed = True
			if changed:
				shift_doc.save(ignore_permissions=True)
			shift_doc.process_auto_attendance()
			shifts_processed += 1

	return {
		"attendance_records_fetched": len(records),
		"checkins_created": created,
		"checkins_updated": updated,
		"skipped_unmapped": skipped_unmapped,
		"shifts_processed": shifts_processed,
		"timesheets": ts_summary,
	}


@frappe.whitelist()
def sync_all(
	from_date: str | None = None,
	to_date: str | None = None,
	process_auto_attendance: int = 1,
	finalize_today: int = 0,
) -> dict[str, Any]:
	"""Sync departments, schedules, employees, attendance, and timesheets from WorkSight API."""
	frappe.only_for(("System Manager", "HR Manager"))
	settings = _get_settings()
	if not cint(settings.enabled):
		frappe.throw(_("WorkSight integration is disabled in WorkSight Settings."))
	client = _get_client(settings)
	emp_res = sync_work_schedules_and_employees(
		settings=settings,
		client=client,
		incremental=False,
		process_after=from_date,
	)
	att_res = sync_attendance_from_worksight(
		from_date=from_date,
		to_date=to_date,
		process_auto_attendance=bool(cint(process_auto_attendance)),
		finalize_today=bool(cint(finalize_today)),
		sync_timesheets_first=True,
		settings=settings,
		client=client,
	)
	return {"employees": emp_res, "attendance": att_res}


@frappe.whitelist()
def sync_timesheets(
	from_date: str,
	to_date: str,
	employee_code: str | None = None,
) -> dict[str, Any]:
	"""On-demand sync of WorkSight `/timesheets` inside-office hours for payroll."""
	frappe.only_for(("System Manager", "HR Manager", "HR User"))
	settings = _get_settings()
	if not cint(settings.enabled):
		frappe.throw(_("WorkSight integration is disabled in WorkSight Settings."))
	return sync_timesheets_from_worksight(
		from_date=from_date,
		to_date=to_date,
		employee_code=employee_code,
		settings=settings,
	)


@frappe.whitelist()
def get_live_presence(away_after_min: int | None = None) -> dict[str, Any]:
	"""Query WorkSight `/presence/now` for who is currently in the office."""
	frappe.only_for(("System Manager", "HR Manager", "HR User"))
	settings = _get_settings()
	client = _get_client(settings)
	away_min = cint(away_after_min) if away_after_min is not None else (cint(getattr(settings, "away_after_minutes", 15)) or 15)
	return client.get_presence_now(away_after_min=away_min)


@frappe.whitelist()
def push_employee_to_worksight(employee: str) -> dict[str, Any]:
	"""Create or update an ERPNext Employee in WorkSight via `PUT /employees/{employeeCode}`."""
	frappe.only_for(("System Manager", "HR Manager"))
	settings = _get_settings()
	client = _get_client(settings)
	emp_doc = frappe.get_doc("Employee", employee)
	code = _resolve_employee_code(emp_doc.name)

	if not emp_doc.attendance_device_id:
		emp_doc.db_set("attendance_device_id", code)

	dept_name = None
	if emp_doc.department:
		dept_name = frappe.db.get_value("Department", emp_doc.department, "department_name") or emp_doc.department

	payload: dict[str, Any] = {
		"fullName": emp_doc.employee_name,
		"email": emp_doc.company_email or emp_doc.personal_email or None,
		"phoneNumber": emp_doc.cell_number or None,
		"jobTitle": emp_doc.designation or None,
		"department": dept_name,
		"workSchedule": emp_doc.default_shift or None,
		"employmentType": emp_doc.employment_type or None,
		"joiningDate": str(emp_doc.date_of_joining) if emp_doc.date_of_joining else None,
		"isActive": emp_doc.status == "Active",
	}
	return client.upsert_employee(code, payload)


@frappe.whitelist()
def issue_face_enrolment_link(employee: str) -> dict[str, Any]:
	"""Generate a one-time phone face-enrolment link for an employee via WorkSight API."""
	frappe.only_for(("System Manager", "HR Manager"))
	settings = _get_settings()
	client = _get_client(settings)
	code = _resolve_employee_code(employee)
	return client.create_enrolment_link(code)


@frappe.whitelist()
def manual_check_in(employee: str, at: str | None = None) -> dict[str, Any]:
	"""Record an off-site/manual check-in in WorkSight (`POST /attendance/check-in`) with office offset."""
	frappe.only_for(("System Manager", "HR Manager", "HR User"))
	settings = _get_settings()
	client = _get_client(settings)
	code = _resolve_employee_code(employee)
	iso_at = format_office_iso_timestamp(at, office_timezone=_get_office_timezone(settings))
	return client.manual_check_in(code, at=iso_at)


@frappe.whitelist()
def manual_check_out(employee: str, at: str | None = None) -> dict[str, Any]:
	"""Record an off-site/manual check-out in WorkSight (`POST /attendance/check-out`) with office offset."""
	frappe.only_for(("System Manager", "HR Manager", "HR User"))
	settings = _get_settings()
	client = _get_client(settings)
	code = _resolve_employee_code(employee)
	iso_at = format_office_iso_timestamp(at, office_timezone=_get_office_timezone(settings))
	return client.manual_check_out(code, at=iso_at)


@frappe.whitelist()
def register_worksight_webhook(public_url: str | None = None, away_after_min: int | None = None) -> dict[str, Any]:
	"""Register this site's HTTPS webhook URL with WorkSight and save the signing secret."""
	frappe.only_for(("System Manager", "HR Manager"))
	settings = _get_settings()
	target_url = (public_url or settings.public_webhook_url or "").strip()
	if not target_url.startswith("https://"):
		frappe.throw(_("WorkSight requires a public https:// webhook URL."))

	if not target_url.endswith("worksight_hrms.api.webhook.receive_checkin"):
		target_url = f"{target_url.rstrip('/')}/api/method/worksight_hrms.api.webhook.receive_checkin"

	away_min = cint(away_after_min) if away_after_min is not None else (cint(getattr(settings, "away_after_minutes", 15)) or 15)
	client = _get_client(settings)
	created = client.register_webhook(url=target_url, away_after_min=away_min)
	if created.get("id"):
		settings.worksight_webhook_id = created["id"]
	if created.get("secret"):
		settings.webhook_secret = created["secret"]
	settings.public_webhook_url = target_url
	settings.save(ignore_permissions=True)

	return {
		"webhook_id": created.get("id"),
		"url": target_url,
		"away_after_min": away_min,
		"secret_saved": bool(created.get("secret")),
	}


@frappe.whitelist()
def test_worksight_webhook(webhook_id: str | None = None) -> dict[str, Any]:
	"""Trigger WorkSight `POST /webhooks/{id}/test` to verify webhook delivery."""
	frappe.only_for(("System Manager", "HR Manager"))
	settings = _get_settings()
	target_id = (webhook_id or getattr(settings, "worksight_webhook_id", None) or "").strip()
	if not target_id:
		frappe.throw(_("No Registered WorkSight Webhook ID found in WorkSight Settings."))
	client = _get_client(settings)
	return client.test_webhook(target_id)


@frappe.whitelist()
def get_webhook_deliveries(webhook_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
	"""Fetch recent webhook delivery attempts from WorkSight."""
	frappe.only_for(("System Manager", "HR Manager"))
	settings = _get_settings()
	target_id = (webhook_id or getattr(settings, "worksight_webhook_id", None) or "").strip()
	if not target_id:
		frappe.throw(_("No Registered WorkSight Webhook ID found in WorkSight Settings."))
	client = _get_client(settings)
	return client.list_webhook_deliveries(target_id, limit=cint(limit) or 50)


def scheduled_sync_from_worksight() -> None:
	"""Hourly scheduler hook to pull WorkSight employees, attendance, and timesheets."""
	settings = _get_settings()
	if not cint(settings.enabled) or not cint(settings.enable_api_polling_sync):
		return
	if not settings.api_key:
		return
	try:
		client = _get_client(settings)
		sync_work_schedules_and_employees(settings=settings, client=client, incremental=True)
		sync_attendance_from_worksight(
			from_date=str(date.today() - timedelta(days=1)),
			to_date=str(date.today()),
			process_auto_attendance=True,
			finalize_today=False,
			sync_timesheets_first=True,
			settings=settings,
			client=client,
		)
	except Exception:
		frappe.log_error(title="WorkSight Hourly Sync Failed", message=frappe.get_traceback())
