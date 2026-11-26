from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

_LOG_TYPE_ALIASES: dict[str, str] = {
	"in": "IN",
	"check_in": "IN",
	"checkin": "IN",
	"entry": "IN",
	"enter": "IN",
	"1": "IN",
	"employee.arrived": "IN",
	"employee.came_back": "IN",
	"out": "OUT",
	"check_out": "OUT",
	"checkout": "OUT",
	"exit": "OUT",
	"leave": "OUT",
	"0": "OUT",
	"employee.went_away": "OUT",
}


def verify_hmac_signature(
	raw_body: bytes,
	signature_header: str | None,
	secret: str | None,
	tolerance_seconds: int = 300,
	now_ts: float | None = None,
) -> bool:
	"""Verify WorkSight HMAC-SHA256 signature (`t=<unix>,v1=<hex>` or `sha256=<hex>`)."""
	if not raw_body or not signature_header or not secret:
		return False
	provided = signature_header.strip()

	# WorkSight v1 format: X-WorkSight-Signature: t=<unix time>,v1=<hex>
	if "t=" in provided and "v1=" in provided:
		parts: dict[str, str] = {}
		for item in provided.split(","):
			if "=" in item:
				k, v = item.split("=", 1)
				parts[k.strip()] = v.strip()
		timestamp_str = parts.get("t")
		sig_v1 = parts.get("v1")
		if not timestamp_str or not sig_v1:
			return False
		try:
			event_ts = int(timestamp_str)
		except ValueError:
			return False
		if tolerance_seconds > 0:
			current_ts = now_ts if now_ts is not None else datetime.now(timezone.utc).timestamp()
			if abs(current_ts - event_ts) >= tolerance_seconds:
				return False
		signed_payload = (timestamp_str + ".").encode("utf-8") + raw_body
		expected = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
		return hmac.compare_digest(expected.lower(), sig_v1.lower())

	if provided.lower().startswith("sha256="):
		provided = provided.split("=", 1)[1].strip()
	if not provided:
		return False
	expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
	return hmac.compare_digest(expected.lower(), provided.lower())


def verify_bearer_token(auth_header: str | None, expected_token: str | None) -> bool:
	"""Verify HTTP Bearer token using constant-time comparison."""
	if not auth_header or not expected_token:
		return False
	parts = auth_header.strip().split(None, 1)
	if len(parts) != 2 or parts[0].lower() != "bearer":
		return False
	return hmac.compare_digest(parts[1].strip(), expected_token.strip())


def verify_timestamp_tolerance(
	timestamp_header: str | None,
	tolerance_seconds: int,
	now_ts: float | None = None,
) -> bool:
	"""Validate replay-protection timestamp header against tolerance_seconds."""
	if tolerance_seconds <= 0 or not timestamp_header:
		return True
	raw = timestamp_header.strip()
	try:
		event_ts = float(raw)
		if event_ts > 1e12:
			event_ts /= 1000.0
	except ValueError:
		try:
			parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
		except ValueError:
			return False
		if parsed.tzinfo is None:
			parsed = parsed.replace(tzinfo=timezone.utc)
		event_ts = parsed.timestamp()

	current_ts = now_ts if now_ts is not None else datetime.now(timezone.utc).timestamp()
	return abs(current_ts - event_ts) <= tolerance_seconds


def _resolve_tz(tz_name: str | None):
	clean = (tz_name or "UTC").strip()
	return timezone.utc if clean.upper() == "UTC" else ZoneInfo(clean)


def parse_checkin_timestamp(value: Any, target_timezone: str = "UTC") -> datetime:
	"""Parse ISO-8601 or Unix epoch (seconds or ms) into naive datetime in target_timezone."""
	if value is None or value == "":
		raise ValueError("Missing check-in timestamp.")

	tz = _resolve_tz(target_timezone)

	if isinstance(value, (int, float)):
		epoch = float(value)
		if epoch > 1e12:
			epoch /= 1000.0
		return datetime.fromtimestamp(epoch, tz=tz).replace(tzinfo=None)

	if isinstance(value, datetime):
		dt = value
	elif isinstance(value, str):
		raw = value.strip()
		if raw.replace(".", "", 1).isdigit():
			epoch = float(raw)
			if epoch > 1e12:
				epoch /= 1000.0
			return datetime.fromtimestamp(epoch, tz=tz).replace(tzinfo=None)
		dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
	else:
		raise ValueError(f"Unsupported timestamp format: {type(value).__name__}")

	if dt.tzinfo is not None:
		return dt.astimezone(tz).replace(tzinfo=None)
	return dt


def format_office_iso_timestamp(value: datetime | str | None, office_timezone: str = "Asia/Colombo") -> str:
	"""Format a datetime or ISO string as ISO 8601 with office UTC offset (required by WorkSight API)."""
	tz = _resolve_tz(office_timezone)
	if value is None or value == "":
		return datetime.now(tz).replace(microsecond=0).isoformat()
	if isinstance(value, str):
		raw = value.strip()
		dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
	else:
		dt = value
	if dt.tzinfo is None:
		dt = dt.replace(tzinfo=tz)
	else:
		dt = dt.astimezone(tz)
	return dt.replace(microsecond=0).isoformat()


def normalize_log_type(value: Any) -> str | None:
	"""Normalize WorkSight punch direction or event name into 'IN', 'OUT', or None."""
	if value is None:
		return None
	key = str(value).strip().lower()
	if not key:
		return None
	return _LOG_TYPE_ALIASES.get(key)


def _pick_first(payload: dict[str, Any], keys: tuple[str, ...]) -> Any:
	for key in keys:
		val = payload.get(key)
		if val is not None and val != "":
			return val
	return None


def normalize_checkin_payload(payload: dict[str, Any], target_timezone: str = "UTC") -> dict[str, Any]:
	"""Normalize WorkSight v1 webhook envelopes (`event` + `data`) and flat check-in payloads."""
	if not isinstance(payload, dict):
		raise ValueError("Check-in payload must be a JSON object.")

	event_name = str(payload.get("event") or "").strip().lower()
	raw_payload_json = json.dumps(payload, indent=2, default=str)

	if event_name == "webhook.test":
		return {
			"is_test": True,
			"event": "webhook.test",
			"event_id": str(_pick_first(payload, ("id", "event_id")) or "webhook-test"),
			"raw_payload": raw_payload_json,
		}

	data = payload.get("data") if isinstance(payload.get("data"), dict) else payload

	employee_identifier = _pick_first(
		data,
		(
			"employeeCode",
			"employee_code",
			"employee_identifier",
			"attendance_device_id",
			"employee_id",
			"badge_id",
			"person_id",
			"face_id",
			"user_id",
		),
	) or _pick_first(
		payload,
		("employeeCode", "employee_code", "employee_identifier", "attendance_device_id", "employee_id"),
	)
	if not employee_identifier:
		raise ValueError("Missing employee identifier (e.g. data.employeeCode or attendance_device_id).")

	raw_time = _pick_first(
		data,
		("at", "checkin_time", "timestamp", "time", "punched_at", "event_time", "createdAt"),
	) or _pick_first(
		payload,
		("checkin_time", "timestamp", "time", "punched_at", "event_time", "createdAt"),
	)
	checkin_dt = parse_checkin_timestamp(raw_time, target_timezone=target_timezone)
	checkin_time_str = checkin_dt.strftime("%Y-%m-%d %H:%M:%S")

	raw_log_type = _pick_first(data, ("log_type", "direction", "event_type", "punch_type"))
	if raw_log_type is None:
		raw_log_type = _pick_first(payload, ("log_type", "direction", "event_type", "punch_type", "event"))
	log_type = normalize_log_type(raw_log_type)
	if raw_log_type is not None and str(raw_log_type).strip() != "" and log_type is None:
		raise ValueError(f"Invalid log_type/event value: {raw_log_type!r}")

	device_id = _pick_first(data, ("device_id", "camera_id", "terminal_id", "kiosk_id")) or _pick_first(
		payload, ("device_id", "camera_id", "terminal_id", "kiosk_id")
	)
	location = _pick_first(data, ("location", "gate", "zone", "site")) or _pick_first(
		payload, ("location", "gate", "zone", "site")
	)
	raw_confidence = _pick_first(data, ("confidence", "match_score", "score"))
	if raw_confidence is None:
		raw_confidence = _pick_first(payload, ("confidence", "match_score", "score"))
	confidence = float(raw_confidence) if raw_confidence is not None else None

	event_id = _pick_first(payload, ("id", "event_id", "checkin_id", "uuid")) or _pick_first(
		data, ("id", "event_id", "checkin_id", "uuid")
	)
	if not event_id:
		fingerprint = json.dumps(
			{
				"employee_identifier": str(employee_identifier),
				"checkin_time": checkin_time_str,
				"device_id": str(device_id or ""),
				"log_type": log_type or "",
			},
			sort_keys=True,
		).encode("utf-8")
		event_id = f"ws-{hashlib.sha256(fingerprint).hexdigest()[:20]}"

	return {
		"is_test": False,
		"event": event_name or None,
		"event_id": str(event_id),
		"employee_identifier": str(employee_identifier).strip(),
		"checkin_dt": checkin_dt,
		"checkin_time": checkin_time_str,
		"log_type": log_type,
		"device_id": str(device_id).strip() if device_id is not None else None,
		"location": str(location).strip() if location is not None else None,
		"confidence": confidence,
		"raw_payload": raw_payload_json,
	}
