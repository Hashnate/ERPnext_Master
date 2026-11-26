# WorkSight HRMS (`worksight_hrms`)

Frappe custom app connecting **WorkSight** (`https://worksight.hashnate.com/api/v1`) into **ERPNext + Frappe HRMS**:

```text
WorkSight Face Recognition & Cloud API (external)
   │
   ├──► Live Webhooks: POST /api/method/worksight_hrms.api.webhook.receive_checkin
   │       • Events: employee.arrived (IN), employee.came_back (IN), employee.went_away (OUT), webhook.test
   │       • Signature: X-WorkSight-Signature: t=<unix>,v1=<hmac_sha256>
   │
   └──► Hourly / On-Demand API Sync: https://worksight.hashnate.com/api/v1
           • GET /work-schedules  ──► HRMS Shift Type
           • GET /employees       ──► HRMS Employee (matched via employeeCode / attendance_device_id)
           • GET /attendance      ──► HRMS Employee Checkin + Shift Auto Attendance
   │
   ▼  (Submitted Attendance)
[2] Attendance.on_submit   ──►  WorkSight Late Record & WorkSight Overtime Record
   │
   ▼  (Approved / Submitted)
[3] Payroll Sync           ──►  HRMS Additional Salary (Late Deduction / Overtime)
```

> Face recognition stays completely inside WorkSight; this app consumes check-in events and attendance APIs only.

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
   - **WorkSight API Base URL**: `https://worksight.hashnate.com/api/v1`
   - **WorkSight API Key**: `ws_live_...`
   - **Default Company**: e.g. `AR software`
   - Enable **Enable Hourly WorkSight API Sync** and **Auto-Create Missing Employees from WorkSight**.
3. Under **Webhook Security & Deduplication**:
   - **Webhook Secret**: `whsec_...` (automatically populated if you call `register_worksight_webhook` with a public `https://` URL).
   - **Default Webhook Timezone**: `Asia/Colombo`.
4. Under **Late Arrival Policy** & **Overtime Policy**:
   - Link **Late Deduction Salary Component** (`Late Deduction`) and **Overtime Salary Component** (`Overtime`).
   - Enable **Require Approval for Overtime Records** in production so HR reviews overtime before payroll sync.

## Real WorkSight Webhook Format

WorkSight signs deliveries with `X-WorkSight-Signature: t=<unix time>,v1=<hex>` over `<t>.<raw_body>`:

```json
{
  "id": "5b0c...",
  "event": "employee.arrived",
  "createdAt": "2026-11-26T09:03:10+05:30",
  "data": {
    "employeeCode": "EMP-010",
    "fullName": "Muhni",
    "date": "2026-11-26",
    "at": "2026-11-26T09:02:31+05:30"
  }
}
```

## Connecting Real WorkSight & Removing Dummy Data

From `ERPnext_Master/worksight_hrms`:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\connect_real_worksight.ps1
```

This removes dummy test records, updates `WorkSight Settings`, and runs `worksight_hrms.worksight_hrms.services.worksight_client.sync_all` against `https://worksight.hashnate.com/api/v1`.

## Running Tests

```bash
python -m unittest discover -s worksight_hrms/tests -v
```
