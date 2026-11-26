from __future__ import annotations

import hashlib
import hmac
import json
import sys
import types
import unittest
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


class TestSecurityAndWebhook(unittest.TestCase):
	def setUp(self):
		if not HAS_REAL_FRAPPE:
			self.db = install_frappe_stub()
			import frappe

			self.db.set_single("System Settings", {"time_zone": "UTC"})
			self.settings = self.db.set_single(
				"WorkSight Settings",
				{
					"enabled": 1,
					"webhook_secret": "super-secret-key",
					"bearer_token": "bearer-123",
					"signature_header": "X-WorkSight-Signature",
					"timestamp_tolerance_seconds": 300,
					"deduplication_window_seconds": 60,
					"default_timezone": "Asia/Karachi",
					"employee_match_field": "attendance_device_id",
					"default_log_type_mode": "Use Payload or Alternate",
					"auto_trigger_shift_sync": 1,
				},
			)
			self.db.insert_doc(
				frappe.get_doc(
					{
						"doctype": "Employee",
						"name": "HR-EMP-00001",
						"employee_name": "Ayesha Khan",
						"company": "Hasnet Tech",
						"attendance_device_id": "WS-1042",
						"status": "Active",
					}
				)
			)

	def test_hmac_and_bearer_verification(self):
		from worksight_hrms.worksight_hrms.services.security import (
			verify_bearer_token,
			verify_hmac_signature,
			verify_timestamp_tolerance,
		)

		body = b'{"employee_id":"WS-1042"}'
		sig = hmac.new(b"super-secret-key", body, hashlib.sha256).hexdigest()

		self.assertTrue(verify_hmac_signature(body, f"sha256={sig}", "super-secret-key"))
		self.assertTrue(verify_hmac_signature(body, sig, "super-secret-key"))
		self.assertFalse(verify_hmac_signature(body, "sha256=deadbeef", "super-secret-key"))

		self.assertTrue(verify_bearer_token("Bearer bearer-123", "bearer-123"))
		self.assertFalse(verify_bearer_token("Basic bearer-123", "bearer-123"))

		self.assertTrue(verify_timestamp_tolerance("1700000100", 300, now_ts=1700000200))
		self.assertFalse(verify_timestamp_tolerance("1700000000", 300, now_ts=1700001000))

	def test_payload_normalization_converts_timezone(self):
		from worksight_hrms.worksight_hrms.services.security import normalize_checkin_payload

		norm = normalize_checkin_payload(
			{
				"event_id": "evt-001",
				"face_id": "WS-1042",
				"timestamp": "2026-11-26T04:18:00Z",
				"direction": "check_in",
				"camera_id": "CAM-LOBBY-1",
				"confidence": 0.985,
			},
			target_timezone="Asia/Karachi",
		)
		self.assertEqual(norm["event_id"], "evt-001")
		self.assertEqual(norm["employee_identifier"], "WS-1042")
		self.assertEqual(norm["checkin_time"], "2026-11-26 09:18:00")
		self.assertEqual(norm["log_type"], "IN")
		self.assertEqual(norm["device_id"], "CAM-LOBBY-1")

	def test_webhook_creates_employee_checkin_and_deduplicates(self):
		if HAS_REAL_FRAPPE:
			self.skipTest("Runs with standalone in-memory stub")

		import frappe
		from worksight_hrms.api.webhook import receive_checkin

		payload = {
			"event_id": "ws-evt-900",
			"attendance_device_id": "WS-1042",
			"checkin_time": "2026-11-26T09:18:00+05:00",
			"device_id": "GATE-A",
		}
		raw_bytes = json.dumps(payload).encode("utf-8")
		sig = hmac.new(b"super-secret-key", raw_bytes, hashlib.sha256).hexdigest()

		req = types.SimpleNamespace(
			headers={"X-WorkSight-Signature": f"sha256={sig}"},
			get_data=lambda as_text=False: raw_bytes.decode("utf-8") if as_text else raw_bytes,
		)
		frappe.request = req

		first = receive_checkin()
		self.assertTrue(first["ok"])
		self.assertEqual(first["processed"], 1)
		self.assertEqual(first["results"][0]["log_type"], "IN")

		checkins = self.db.get_all("Employee Checkin")
		self.assertEqual(len(checkins), 1)
		self.assertEqual(checkins[0]["employee"], "HR-EMP-00001")
		self.assertEqual(checkins[0]["skip_auto_attendance"], 0)

		# Replay same event_id -> duplicate
		second = receive_checkin()
		self.assertEqual(second["duplicates"], 1)
		self.assertEqual(len(self.db.get_all("Employee Checkin")), 1)

		# Different event_id within 60s window -> rapid duplicate ignored
		rapid_payload = {
			"event_id": "ws-evt-901",
			"attendance_device_id": "WS-1042",
			"checkin_time": "2026-11-26T09:18:25+05:00",
		}
		rapid_bytes = json.dumps(rapid_payload).encode("utf-8")
		rapid_sig = hmac.new(b"super-secret-key", rapid_bytes, hashlib.sha256).hexdigest()
		frappe.request = types.SimpleNamespace(
			headers={"X-WorkSight-Signature": f"sha256={rapid_sig}"},
			get_data=lambda as_text=False: rapid_bytes.decode("utf-8") if as_text else rapid_bytes,
		)
		third = receive_checkin()
		self.assertEqual(third["duplicates"], 1)
		self.assertEqual(len(self.db.get_all("Employee Checkin")), 1)

		# Evening punch without explicit log_type -> alternates to OUT
		out_payload = {
			"event_id": "ws-evt-902",
			"attendance_device_id": "WS-1042",
			"checkin_time": "2026-11-26T18:35:00+05:00",
		}
		out_bytes = json.dumps(out_payload).encode("utf-8")
		out_sig = hmac.new(b"super-secret-key", out_bytes, hashlib.sha256).hexdigest()
		frappe.request = types.SimpleNamespace(
			headers={"X-WorkSight-Signature": f"sha256={out_sig}"},
			get_data=lambda as_text=False: out_bytes.decode("utf-8") if as_text else out_bytes,
		)
		fourth = receive_checkin()
		self.assertEqual(fourth["processed"], 1)
		self.assertEqual(fourth["results"][0]["log_type"], "OUT")
		self.assertEqual(len(self.db.get_all("Employee Checkin")), 2)

	def test_webhook_rejects_bad_signature(self):
		if HAS_REAL_FRAPPE:
			self.skipTest("Runs with standalone in-memory stub")

		import frappe
		from worksight_hrms.api.webhook import receive_checkin

		raw_bytes = json.dumps({"attendance_device_id": "WS-1042", "checkin_time": "2026-11-26T09:00:00Z"}).encode(
			"utf-8"
		)
		frappe.request = types.SimpleNamespace(
			headers={"X-WorkSight-Signature": "sha256=invalid"},
			get_data=lambda as_text=False: raw_bytes.decode("utf-8") if as_text else raw_bytes,
		)
		with self.assertRaises(frappe.AuthenticationError) as ctx:
			receive_checkin()
		self.assertIn("Invalid WorkSight webhook credentials", str(ctx.exception))


if __name__ == "__main__":
	unittest.main()
