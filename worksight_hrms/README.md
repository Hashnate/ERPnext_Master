# WorkSight HRMS (`worksight_hrms`)

Frappe custom app connecting **WorkSight API 1.0.0** (`https://worksight.hashnate.com/api/v1`) with **ERPNext + Frappe HRMS**:

```text
WorkSight Face Recognition & Cloud API (https://worksight.hashnate.com/api/v1)
   │
   ├──► Live Webhooks: POST /api/method/worksight_hrms.api.webhook.receive_checkin
   │       • Events: employee.arrived (IN), employee.came_back (IN),
   │                 employee.went_away (OUT), webhook.test
   │       • Signature: X-WorkSight-Signature: t=<unix>,v1=<hmac_sha256>
   │
   └──► Hourly / On-Demand API Sync (worksight_client.py):
           • GET /departments & /work-schedules ──► Department & Shift Type
           • GET /employees                     ──► Employee (matched by employeeCode)
           • GET /attendance                    ──► Employee Checkin (cursor + updatedSince)
           • GET /timesheets                    ──► WorkSight Daily Timesheet (insideMinutes, awayMinutes)
           • GET /presence/now                  ──► Live office board (IN_OFFICE / AWAY / NOT_SEEN_TODAY)
           • PUT /employees/{employeeCode}      ──► Push / deactivate Employee in WorkSight
           • POST /employees/{code}/enrolment-link ──► Phone face-enrolment link
           • POST /attendance/check-in|out      ──► Manual off-site punches (+offset ISO 8601)
   │
   ▼  (Submitted Attendance)
[2] Attendance.before_submit / on_submit
       • Applies WorkSight /timesheets inside_hours (excluding time away) for payroll hours
       • Creates WorkSight Late Record & WorkSight Overtime Record
   │
   ▼  (Approved / Submitted)
[3] Payroll Sync ──► HRMS Additional Salary (Deduction / Earning)
```

> Face photos, face data, and camera video remain inside WorkSight; this app consumes attendance, timesheet, and organization APIs only.

## Installation (Frappe Bench)

```bash
bench get-app --soft-link /path/to/ERPnext_Master/worksight_hrms
bench --site <your-site> install-app worksight_hrms
bench --site <your-site> migrate
```

**Prerequisites:** `erpnext` and `hrms` must be installed on the site.

## Configuration (`WorkSight Settings`)

1. Open **WorkSight Settings** in Desk (`/desk/worksight-settings`).
2. Under **WorkSight API Connection**:
   - **WorkSight API Base URL**: `https://worksight.hashnate.com/api/v1` (HTTPS required)
   - **WorkSight API Key**: `ws_live_...`
   - **Default Company**: e.g. `Hashnate`
   - **Away Threshold (Minutes)**: `15` (used for `/timesheets`, `/presence/now`, and webhooks)
   - Enable **Enable Hourly WorkSight API Sync**, **Auto-Create Missing Employees from WorkSight**, and **Use WorkSight Timesheets for Payroll Hours**.
3. Under **Webhook Security & Deduplication**:
   - **Webhook Secret**: `whsec_...` (automatically stored by `register_worksight_webhook`)
   - **Default Office Timezone**: `Asia/Colombo`
4. Under **Late Arrival Policy** & **Overtime Policy**:
   - Link **Late Deduction Salary Component** (`Late Deduction`) and **Overtime Salary Component** (`Overtime`).

## Connecting Real WorkSight & Removing Dummy Data

From `ERPnext_Master/worksight_hrms`:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\connect_real_worksight.ps1
```

## Running Tests

```bash
python -m unittest discover -s worksight_hrms/tests -v
```
