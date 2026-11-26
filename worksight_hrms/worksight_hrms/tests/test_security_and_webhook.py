from __future__ import annotations

import hashlib
import hmac
import json
import sys
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

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
					"default_timezone": "Asia/Colombo",
					"employee_match_field": "attendance_device_id",
					"default_log_type_mode": "Use Payload or Alternate",
					"auto_trigger_shift_sync": 1,
				},
			)
			self.db.insert_doc(
				frappe.get_doc(
					{
						"doctype": "Employee",
						"name": "HR-EMP-00009",
						"employee_name": "Afham Sathath",
						"company": "Hashnate",
						"attendance_device_id": "EMP-009",
						"employee_number": "EMP-009",
						"status": "Active",
					}
				)
			)

	def test_hmac_and_bearer_verification(self):
		from worksight_hrms.worksight_hrms.services.security import (
			format_office_iso_timestamp,
			verify_bearer_token,
			verify_hmac_signature,
			verify_timestamp_tolerance,
		)

		body = b'{"event":"employee.arrived","data":{"employeeCode":"EMP-009"}}'
		sig = hmac.new(b"super-secret-key", body, hashlib.sha256).hexdigest()

		self.assertTrue(verify_hmac_signature(body, f"sha256={sig}", "super-secret-key"))
		self.assertTrue(verify_hmac_signature(body, sig, "super-secret-key"))
		self.assertFalse(verify_hmac_signature(body, "sha256=deadbeef", "super-secret-key"))

		self.assertTrue(verify_bearer_token("Bearer bearer-123", "bearer-123"))
		self.assertFalse(verify_bearer_token("Basic bearer-123", "bearer-123"))

		self.assertTrue(verify_timestamp_tolerance("1700000100", 300, now_ts=1700000200))
		self.assertFalse(verify_timestamp_tolerance("1700000000", 300, now_ts=1700001000))

		iso_colombo = format_office_iso_timestamp("2026-11-26 09:02:00", office_timezone="Asia/Colombo")
		self.assertEqual(iso_colombo, "2026-11-26T09:02:00+05:30")

	def test_payload_normalization_converts_timezone(self):
		from worksight_hrms.worksight_hrms.services.security import normalize_checkin_payload

		norm = normalize_checkin_payload(
			{
				"id": "evt-001",
				"event": "employee.arrived",
				"createdAt": "2026-11-26T09:03:10+05:30",
				"data": {
					"employeeCode": "EMP-009",
					"fullName": "Afham Sathath",
					"date": "2026-11-26",
					"at": "2026-11-26T03:32:31Z",
				},
			},
			target_timezone="Asia/Colombo",
		)
		self.assertEqual(norm["event_id"], "evt-001")
		self.assertEqual(norm["employee_identifier"], "EMP-009")
		self.assertEqual(norm["checkin_time"], "2026-11-26 09:02:31")
		self.assertEqual(norm["log_type"], "IN")

	def test_worksight_v1_webhook_events_and_deduplication(self):
		if HAS_REAL_FRAPPE:
			self.skipTest("Runs with standalone in-memory stub")

		import frappe
		from worksight_hrms.api.webhook import receive_checkin
		from worksight_hrms.worksight_hrms.services.security import (
			normalize_checkin_payload,
			parse_checkin_timestamp,
			verify_hmac_signature,
		)

		dt_ms = parse_checkin_timestamp(1795668000000, target_timezone="UTC")
		self.assertEqual(dt_ms.year, 2026)

		now_ts = int(time.time())

		def signed_request(payload_dict):
			raw = json.dumps(payload_dict).encode("utf-8")
			sig = hmac.new(
				b"super-secret-key",
				f"{now_ts}.".encode("utf-8") + raw,
				hashlib.sha256,
			).hexdigest()
			return (
				types.SimpleNamespace(
					headers={"X-WorkSight-Signature": f"t={now_ts},v1={sig}"},
					get_data=lambda as_text=False: raw.decode("utf-8") if as_text else raw,
				),
				raw,
				sig,
			)

		arrived_payload = {
			"id": "5b0c-arrived-1",
			"event": "employee.arrived",
			"createdAt": "2026-11-26T09:03:10+05:30",
			"data": {
				"employeeCode": "EMP-009",
				"fullName": "Afham Sathath",
				"date": "2026-11-26",
				"at": "2026-11-26T09:02:31+05:30",
			},
		}
		req, raw_arrived, signed_v1 = signed_request(arrived_payload)
		self.assertTrue(
			verify_hmac_signature(
				raw_arrived,
				f"t={now_ts},v1={signed_v1}",
				"super-secret-key",
				tolerance_seconds=300,
				now_ts=now_ts,
			)
		)
		self.assertFalse(
			verify_hmac_signature(
				raw_arrived,
				f"t={now_ts - 600},v1={signed_v1}",
				"super-secret-key",
				tolerance_seconds=300,
				now_ts=now_ts,
			)
		)

		frappe.request = req
		first = receive_checkin()
		self.assertTrue(first["ok"])
		self.assertEqual(first["processed"], 1)
		self.assertEqual(first["results"][0]["employee"], "HR-EMP-00009")
		self.assertEqual(first["results"][0]["log_type"], "IN")

		# Replay same event id -> duplicate
		second = receive_checkin()
		self.assertEqual(second["duplicates"], 1)
		self.assertEqual(len(self.db.get_all("Employee Checkin")), 1)

		# Different event id of same direction within 60s window -> rapid duplicate
		req_rapid, _, _ = signed_request(
			{
				"id": "5b0c-arrived-dup",
				"event": "employee.arrived",
				"data": {"employeeCode": "EMP-009", "at": "2026-11-26T09:02:55+05:30"},
			}
		)
		frappe.request = req_rapid
		third = receive_checkin()
		self.assertEqual(third["duplicates"], 1)
		self.assertEqual(len(self.db.get_all("Employee Checkin")), 1)

		# employee.went_away shortly after arrival (opposite direction) MUST still be recorded as OUT
		req_away, _, _ = signed_request(
			{
				"id": "5b0c-away-1",
				"event": "employee.went_away",
				"data": {"employeeCode": "EMP-009", "at": "2026-11-26T09:03:00+05:30"},
			}
		)
		frappe.request = req_away
		fourth = receive_checkin()
		self.assertEqual(fourth["processed"], 1)
		self.assertEqual(fourth["results"][0]["log_type"], "OUT")
		self.assertEqual(len(self.db.get_all("Employee Checkin")), 2)

		# employee.came_back -> IN
		norm_back = normalize_checkin_payload(
			{
				"id": "5b0c-back-1",
				"event": "employee.came_back",
				"data": {"employeeCode": "EMP-009", "at": "2026-11-26T10:15:00+05:30"},
			},
			target_timezone="Asia/Colombo",
		)
		self.assertEqual(norm_back["log_type"], "IN")

		# webhook.test acknowledged without employee
		req_test, _, _ = signed_request({"id": "wh-test-1", "event": "webhook.test", "data": {}})
		frappe.request = req_test
		res_test = receive_checkin()
		self.assertTrue(res_test["ok"])
		self.assertEqual(res_test["results"][0]["status"], "test_acknowledged")

	def test_webhook_rejects_bad_signature(self):
		if HAS_REAL_FRAPPE:
			self.skipTest("Runs with standalone in-memory stub")

		import frappe
		from worksight_hrms.api.webhook import receive_checkin

		raw_bytes = json.dumps(
			{"id": "bad-1", "event": "employee.arrived", "data": {"employeeCode": "EMP-009", "at": "2026-11-26T09:00:00+05:30"}}
		).encode("utf-8")
		frappe.request = types.SimpleNamespace(
			headers={"X-WorkSight-Signature": "t=1700000000,v1=invalid"},
			get_data=lambda as_text=False: raw_bytes.decode("utf-8") if as_text else raw_bytes,
		)
		with self.assertRaises(frappe.AuthenticationError) as ctx:
			receive_checkin()
		self.assertIn("Invalid WorkSight webhook credentials", str(ctx.exception))

	def test_worksight_client_pagination_and_timesheet_chunking(self):
		from worksight_hrms.worksight_hrms.services.worksight_client import WorkSightAPIError, WorkSightClient

		with self.assertRaises(WorkSightAPIError):
			WorkSightClient("http://insecure.example.com/api/v1", "ws_live_test")

		emp_pages = [
			{"success": True, "data": [{"employeeCode": "EMP-001"}], "page": {"nextCursor": "c2"}},
			{"success": True, "data": [{"employeeCode": "EMP-009"}], "page": {"nextCursor": None}},
		]
		ts_chunks = [
			{
				"success": True,
				"data": [{"employeeCode": "EMP-009", "days": [{"date": "2026-08-01", "insideMinutes": 480}]}],
			},
			{
				"success": True,
				"data": [{"employeeCode": "EMP-009", "days": [{"date": "2026-11-05", "insideMinutes": 510}]}],
			},
		]

		class FakeResp:
			def __init__(self, payload):
				self.payload = payload

			def read(self):
				return json.dumps(self.payload).encode("utf-8")

			def __enter__(self):
				return self

			def __exit__(self, *args):
				return False

		with patch("urllib.request.urlopen", side_effect=[FakeResp(emp_pages[0]), FakeResp(emp_pages[1])]):
			client = WorkSightClient("https://worksight.hashnate.com/api/v1", "ws_live_test")
			rows = client.list_employees()
			self.assertEqual([r["employeeCode"] for r in rows], ["EMP-001", "EMP-009"])

		with patch("urllib.request.urlopen", side_effect=[FakeResp(ts_chunks[0]), FakeResp(ts_chunks[1])]) as mock_open:
			client = WorkSightClient("https://worksight.hashnate.com/api/v1", "ws_live_test")
			ts_rows = client.list_timesheets("2026-08-01", "2026-11-15")
			self.assertEqual(mock_open.call_count, 2)
			self.assertEqual(len(ts_rows[0]["days"]), 2)


if __name__ == "__main__":
	unittest.main()
