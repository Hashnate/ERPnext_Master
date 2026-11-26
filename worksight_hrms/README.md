# WorkSight HRMS (`worksight_hrms`)

Frappe custom app bridging **WorkSight** face-recognition attendance events into **ERPNext + Frappe HRMS**:

```text
WorkSight Face Recognition (external)
   │  POST /api/method/worksight_hrms.api.webhook.receive_checkin
   ▼
[1] WorkSight Checkin Log  ──►  HRMS Employee Checkin (idempotent + deduped)
   │
   ▼  (HRMS Shift Auto Attendance submits Attendance)
[2] Attendance.on_submit   ──►  WorkSight Late Record & WorkSight Overtime Record
   │
   ▼  (Approved / Auto-submitted)
[3] Payroll Sync           ──►  HRMS Additional Salary (Deduction / Earning)
```

> Face recognition stays completely inside WorkSight; this app consumes the resulting check-in webhook events only.

## Installation (Frappe Bench)

```bash
bench get-app /path/to/worksight_hrms
bench --site <your-site> install-app worksight_hrms
bench --site <your-site> migrate
```

**Prerequisites:** `erpnext` and `hrms` must be installed on the site.

## Configuration (`WorkSight Settings`)

1. Open **WorkSight Settings** in Desk.
2. Enable the integration and configure authentication:
   - **Webhook Secret**: shared secret for `X-WorkSight-Signature: sha256=<hex>` (HMAC-SHA256 of the raw request body).
   - **Bearer Token**: optional `Authorization: Bearer <token>` alternative.
   - **Timestamp Tolerance (Seconds)**: validates `X-WorkSight-Timestamp` against replay attacks.
   - **Deduplication Window (Seconds)**: ignores duplicate rapid scans for the same employee.
3. Configure **Employee Match Field** (defaults to `Employee.attendance_device_id`).
4. Configure **Late Arrival Policy** and **Overtime Policy** (`Late Deduction Salary Component` and `Overtime Salary Component` must match your HRMS `Salary Component` records).

## Webhook Contract

- **Single or Batch Endpoint**: `POST /api/method/worksight_hrms.api.webhook.receive_checkin` (or `receive_checkins`)
- **Accepted Payload**: single JSON object, JSON array, or `{"events": [...]}`

```json
{
  "event_id": "ws-evt-900",
  "attendance_device_id": "WS-1042",
  "checkin_time": "2026-11-26T09:18:00+05:00",
  "log_type": "IN",
  "device_id": "GATE-A",
  "location": "Main Lobby",
  "confidence": 0.985
}
```

- If `log_type` (`direction`) is omitted and **Log Type Resolution Mode** is `Use Payload or Alternate`, the receiver alternates `IN`/`OUT` based on the employee's previous check-in on that date.

## Running Tests

Standalone unit tests (with built-in Frappe stub when run outside a bench):

```bash
python -m unittest discover -s worksight_hrms/tests
```

Inside a Frappe bench:

```bash
bench --site <your-site> run-tests --app worksight_hrms
```
