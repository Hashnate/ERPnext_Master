from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, get_datetime

from worksight_hrms.worksight_hrms.services.security import (
	normalize_checkin_payload,
	verify_bearer_token,
	verify_hmac_signature,
	verify_timestamp_tolerance,
)

_ALLOWED_MATCH_FIELDS = {"attendance_device_id", "name", "employee_number"}


def _get_settings():
	return frappe.get_cached_doc("WorkSight Settings")


def _authenticate_request(settings) -> None:
	"""Authenticate incoming WorkSight webhook via HMAC-SHA256 or Bearer token."""
	if not cint(settings.enabled):
		frappe.throw(_("WorkSight integration is disabled."), frappe.PermissionError)

	secret = settings.get_password("webhook_secret", raise_exception=False) if settings.webhook_secret else ""
	bearer = settings.get_password("bearer_token", raise_exception=False) if settings.bearer_token else ""
	if not secret and not bearer:
		frappe.throw(
			_("WorkSight webhook authentication is not configured in WorkSight Settings."),
			frappe.AuthenticationError,
		)

	request = getattr(frappe, "request", None)
	if request is None:
		return

	headers = request.headers or {}
	raw_body = request.get_data() or b""
	sig_header_name = settings.signature_header or "X-WorkSight-Signature"
	tolerance = cint(settings.timestamp_tolerance_seconds)

	hmac_ok = bool(secret) and verify_hmac_signature(
		raw_body,
		headers.get(sig_header_name),
		secret,
		tolerance_seconds=tolerance,
	)
	bearer_ok = bool(bearer) and verify_bearer_token(headers.get("Authorization"), bearer)

	if not (hmac_ok or bearer_ok):
		frappe.throw(_("Invalid WorkSight webhook credentials."), frappe.AuthenticationError)

	ts_header = headers.get("X-WorkSight-Timestamp")
	if ts_header and not verify_timestamp_tolerance(ts_header, tolerance):
		frappe.throw(_("Stale or invalid WorkSight webhook timestamp."), frappe.AuthenticationError)


def _extract_events_from_request() -> list[dict[str, Any]]:
	request = getattr(frappe, "request", None)
	if request is not None:
		raw_data = request.get_data(as_text=True) or ""
		if raw_data.strip():
			parsed = json.loads(raw_data)
		else:
			parsed = dict(frappe.form_dict or {})
			parsed.pop("cmd", None)
	else:
		parsed = dict(frappe.form_dict or {})
		parsed.pop("cmd", None)

	if isinstance(parsed, list):
		return parsed
	if isinstance(parsed, dict) and isinstance(parsed.get("events"), list):
		return parsed["events"]
	if isinstance(parsed, dict):
		return [parsed]
	frappe.throw(_("Webhook body must be a JSON object or list of events."))
	return []


def _resolve_employee(identifier: str, match_field: str) -> str | None:
	primary = match_field if match_field in _ALLOWED_MATCH_FIELDS else "attendance_device_id"
	search_order = [primary] + [f for f in ("attendance_device_id", "employee_number", "name") if f != primary]
	for field in search_order:
		employee = frappe.db.get_value("Employee", {field: identifier, "status": "Active"}, "name")
		if employee:
			return employee
	return None


def _is_rapid_duplicate(employee: str, checkin_dt, window_seconds: int) -> str | None:
	if window_seconds <= 0:
		return frappe.db.get_value(
			"Employee Checkin",
			{"employee": employee, "time": checkin_dt},
			"name",
		)
	window_start = checkin_dt - timedelta(seconds=window_seconds)
	window_end = checkin_dt + timedelta(seconds=window_seconds)
	return frappe.db.get_value(
		"Employee Checkin",
		{
			"employee": employee,
			"time": ["between", [window_start, window_end]],
		},
		"name",
	)


def _resolve_log_type(employee: str, checkin_dt, payload_log_type: str | None, mode: str) -> str:
	if mode == "Use Payload Only":
		if not payload_log_type:
			raise ValueError("log_type is required when Log Type Resolution Mode is 'Use Payload Only'.")
		return payload_log_type

	if mode == "Use Payload or Alternate" and payload_log_type:
		return payload_log_type

	lookback_start = checkin_dt - timedelta(hours=16)
	previous_log = frappe.db.get_all(
		"Employee Checkin",
		filters={
			"employee": employee,
			"time": ["between", [lookback_start, checkin_dt]],
		},
		fields=["log_type"],
		order_by="time desc",
		limit=1,
	)
	if previous_log and previous_log[0].get("log_type") == "IN":
		return "OUT"
	return "IN"


def _write_checkin_log(
	normalized: dict[str, Any],
	status: str,
	matched_employee: str | None = None,
	employee_checkin: str | None = None,
	error_message: str | None = None,
) -> str:
	log = frappe.get_doc(
		{
			"doctype": "WorkSight Checkin Log",
			"event_id": normalized["event_id"],
			"status": status,
			"checkin_time": normalized.get("checkin_time"),
			"log_type": normalized.get("log_type") or "",
			"employee_identifier": normalized.get("employee_identifier") or normalized.get("event") or "",
			"matched_employee": matched_employee,
			"employee_checkin": employee_checkin,
			"device_id": normalized.get("device_id"),
			"location": normalized.get("location"),
			"confidence": normalized.get("confidence"),
			"raw_payload": normalized.get("raw_payload"),
			"error_message": error_message,
		}
	)
	log.insert(ignore_permissions=True)
	return log.name


def process_checkin_event(raw_event: dict[str, Any], settings=None) -> dict[str, Any]:
	"""Validate, deduplicate, and ingest a single WorkSight check-in event into Employee Checkin."""
	settings = settings or _get_settings()
	target_tz = settings.default_timezone or frappe.db.get_single_value("System Settings", "time_zone") or "UTC"
	normalized = normalize_checkin_payload(raw_event, target_timezone=target_tz)

	if normalized.get("is_test"):
		existing_test = frappe.db.get_value("WorkSight Checkin Log", {"event_id": normalized["event_id"]}, "name")
		if not existing_test:
			_write_checkin_log(
				normalized,
				status="Ignored",
				error_message="WorkSight webhook.test verification event acknowledged.",
			)
		return {
			"status": "test_acknowledged",
			"event": "webhook.test",
			"event_id": normalized["event_id"],
		}

	existing_log = frappe.db.get_value(
		"WorkSight Checkin Log",
		{"event_id": normalized["event_id"]},
		["name", "status", "employee_checkin"],
		as_dict=True,
	)
	if existing_log:
		return {
			"status": "duplicate",
			"event_id": normalized["event_id"],
			"checkin_log": existing_log.name,
			"employee_checkin": existing_log.employee_checkin,
		}

	employee = _resolve_employee(normalized["employee_identifier"], settings.employee_match_field)
	if not employee:
		err = f"No active Employee found matching {settings.employee_match_field}={normalized['employee_identifier']!r}."
		log_name = _write_checkin_log(normalized, status="Failed", error_message=err)
		return {
			"status": "failed",
			"event_id": normalized["event_id"],
			"checkin_log": log_name,
			"error": err,
		}

	checkin_dt = get_datetime(normalized["checkin_time"])
	dup_checkin = _is_rapid_duplicate(employee, checkin_dt, cint(settings.deduplication_window_seconds))
	if dup_checkin:
		log_name = _write_checkin_log(
			normalized,
			status="Duplicate",
			matched_employee=employee,
			employee_checkin=dup_checkin,
			error_message="Ignored rapid duplicate scan inside deduplication window.",
		)
		return {
			"status": "duplicate",
			"event_id": normalized["event_id"],
			"employee": employee,
			"checkin_log": log_name,
			"employee_checkin": dup_checkin,
		}

	resolved_log_type = _resolve_log_type(
		employee,
		checkin_dt,
		normalized["log_type"],
		settings.default_log_type_mode or "Use Payload or Alternate",
	)
	normalized["log_type"] = resolved_log_type

	device_label = normalized["device_id"] or normalized["location"] or "WorkSight"
	checkin_doc = frappe.get_doc(
		{
			"doctype": "Employee Checkin",
			"employee": employee,
			"time": normalized["checkin_time"],
			"log_type": resolved_log_type,
			"device_id": device_label,
			"skip_auto_attendance": 0 if cint(settings.auto_trigger_shift_sync) else 1,
		}
	)
	checkin_doc.insert(ignore_permissions=True)

	log_name = _write_checkin_log(
		normalized,
		status="Processed",
		matched_employee=employee,
		employee_checkin=checkin_doc.name,
	)

	return {
		"status": "processed",
		"event_id": normalized["event_id"],
		"employee": employee,
		"log_type": resolved_log_type,
		"checkin_log": log_name,
		"employee_checkin": checkin_doc.name,
	}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def receive_checkin() -> dict[str, Any]:
	"""Webhook endpoint for WorkSight face-recognition check-in events."""
	settings = _get_settings()
	_authenticate_request(settings)
	events = _extract_events_from_request()

	results = []
	processed = 0
	duplicates = 0
	failed = 0

	for event in events:
		try:
			res = process_checkin_event(event, settings=settings)
		except Exception as exc:
			failed += 1
			results.append({"status": "failed", "error": str(exc)})
			continue

		results.append(res)
		if res["status"] in ("processed", "test_acknowledged"):
			processed += 1
		elif res["status"] == "duplicate":
			duplicates += 1
		else:
			failed += 1

	return {
		"ok": failed == 0,
		"processed": processed,
		"duplicates": duplicates,
		"failed": failed,
		"results": results,
	}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def receive_checkins() -> dict[str, Any]:
	"""Batch alias for receive_checkin."""
	return receive_checkin()
