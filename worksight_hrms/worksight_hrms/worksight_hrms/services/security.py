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
	"out": "OUT",
	"check_out": "OUT",
	"checkout": "OUT",
	"exit": "OUT",
	"leave": "OUT",
	"0": "OUT",
}


def verify_hmac_signature(raw_body: bytes, signature_header: str | None, secret: str | None) -> bool:
	"""Verify HMAC-SHA256 webhook signature using constant-time comparison."""
	if not raw_body or not signature_header or not secret:
		return False
	provided = signature_header.strip()
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


def parse_checkin_timestamp(value: Any, target_timezone: str = "UTC") -> datetime:
	"""Parse ISO-8601 or Unix epoch timestamps into naive datetime in target_timezone."""
	if value is None or value == "":
		raise ValueError("Missing check-in timestamp.")

	tz_name = (target_timezone or "UTC").strip()
	tz = timezone.utc if tz_name.upper() == "UTC" else ZoneInfo(tz_name)

	if isinstance(value, (int, float)):
		return datetime.fromtimestamp(float(value), tz=tz).replace(tzinfo=None)

	if isinstance(value, datetime):
		dt = value
	elif isinstance(value, str):
		raw = value.strip()
		if raw.replace(".", "", 1).isdigit():
			return datetime.fromtimestamp(float(raw), tz=tz).replace(tzinfo=None)
		dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
	else:
		raise ValueError(f"Unsupported timestamp format: {type(value).__name__}")

	if dt.tzinfo is not None:
		return dt.astimezone(tz).replace(tzinfo=None)
	return dt


def normalize_log_type(value: Any) -> str | None:
	"""Normalize WorkSight punch direction into 'IN', 'OUT', or None."""
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
	"""Normalize an incoming WorkSight check-in webhook payload."""
	if not isinstance(payload, dict):
		raise ValueError("Check-in payload must be a JSON object.")

	employee_identifier = _pick_first(
		payload,
		(
			"employee_identifier",
			"attendance_device_id",
			"employee_id",
			"badge_id",
			"person_id",
			"face_id",
			"user_id",
		),
	)
	if not employee_identifier:
		raise ValueError("Missing employee identifier (e.g. employee_id or attendance_device_id).")

	raw_time = _pick_first(payload, ("checkin_time", "timestamp", "time", "punched_at", "event_time"))
	checkin_dt = parse_checkin_timestamp(raw_time, target_timezone=target_timezone)
	checkin_time_str = checkin_dt.strftime("%Y-%m-%d %H:%M:%S")

	raw_log_type = _pick_first(payload, ("log_type", "direction", "event_type", "punch_type"))
	log_type = normalize_log_type(raw_log_type)
	if raw_log_type is not None and str(raw_log_type).strip() != "" and log_type is None:
		raise ValueError(f"Invalid log_type/direction value: {raw_log_type!r}")

	device_id = _pick_first(payload, ("device_id", "camera_id", "terminal_id", "kiosk_id"))
	location = _pick_first(payload, ("location", "gate", "zone", "site"))
	raw_confidence = _pick_first(payload, ("confidence", "match_score", "score"))
	confidence = float(raw_confidence) if raw_confidence is not None else None

	event_id = _pick_first(payload, ("event_id", "id", "checkin_id", "uuid"))
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
		"event_id": str(event_id),
		"employee_identifier": str(employee_identifier).strip(),
		"checkin_dt": checkin_dt,
		"checkin_time": checkin_time_str,
		"log_type": log_type,
		"device_id": str(device_id).strip() if device_id is not None else None,
		"location": str(location).strip() if location is not None else None,
		"confidence": confidence,
		"raw_payload": json.dumps(payload, indent=2, default=str),
	}
