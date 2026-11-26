param(
    [string]$ApiKey,
    [string]$FromDate = "2026-11-23",
    [string]$ToDate = "2026-11-26"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$baseUrl = "http://localhost:8000"

$pwdSecure = Read-Host "Enter ERPNext Administrator password" -AsSecureString
$pwdPlain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($pwdSecure)
)

if (-not $ApiKey) {
    $keySecure = Read-Host "Enter WorkSight API Key (ws_live_...)" -AsSecureString
    $ApiKey = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($keySecure)
    )
}

# 1. Log in to ERPNext Desk session
Invoke-RestMethod -Uri "$baseUrl/api/method/login" -Method Post -SessionVariable wsSession `
    -Body @{ usr = "Administrator"; pwd = $pwdPlain } | Out-Null

function Get-FrappeDocs($doctype, $filtersJson, $fieldsJson = '["name","docstatus"]') {
    $dt = [Uri]::EscapeDataString($doctype)
    $filters = [Uri]::EscapeDataString($filtersJson)
    $fields = [Uri]::EscapeDataString($fieldsJson)
    (Invoke-RestMethod -Uri "$baseUrl/api/resource/$dt`?fields=$fields&filters=$filters&limit_page_length=200" `
        -WebSession $wsSession).data
}

function Cancel-And-Delete($doctype, $name, $docstatus) {
    $dt = [Uri]::EscapeDataString($doctype)
    $dn = [Uri]::EscapeDataString($name)
    if ($docstatus -eq 1) {
        Invoke-RestMethod -Uri "$baseUrl/api/resource/$dt/$dn" -Method Put -WebSession $wsSession `
            -ContentType "application/json" -Body '{"docstatus":2}' | Out-Null
    }
    Invoke-RestMethod -Uri "$baseUrl/api/resource/$dt/$dn" -Method Delete -WebSession $wsSession | Out-Null
}

# 2. Remove dummy test records in reverse dependency order
Write-Host "`n--- Cleaning Dummy Test Data ---" -ForegroundColor Yellow

$dummyEmpFilter = '[["employee","=","HR-EMP-00001"]]'
foreach ($dt in @("Salary Slip", "Additional Salary", "WorkSight Late Record", "WorkSight Overtime Record", "Attendance")) {
    foreach ($doc in (Get-FrappeDocs $dt $dummyEmpFilter)) {
        Cancel-And-Delete $dt $doc.name $doc.docstatus
        Write-Host "Removed $dt $($doc.name)"
    }
}

foreach ($doc in (Get-FrappeDocs "Employee Checkin" $dummyEmpFilter '["name"]')) {
    Cancel-And-Delete "Employee Checkin" $doc.name 0
    Write-Host "Removed Employee Checkin $($doc.name)"
}

foreach ($doc in (Get-FrappeDocs "WorkSight Checkin Log" '[]' '["name","event_id"]')) {
    if ($doc.event_id -like "test-*" -or $doc.event_id -like "ws-*") {
        Cancel-And-Delete "WorkSight Checkin Log" $doc.name 0
        Write-Host "Removed WorkSight Checkin Log $($doc.name) ($($doc.event_id))"
    }
}

# Clear dummy WS-1001 device ID on HR-EMP-00001 if present
$emp01 = (Invoke-RestMethod -Uri "$baseUrl/api/resource/Employee/HR-EMP-00001" -WebSession $wsSession).data
if ($emp01.attendance_device_id -eq "WS-1001") {
    Invoke-RestMethod -Uri "$baseUrl/api/resource/Employee/HR-EMP-00001" -Method Put -WebSession $wsSession `
        -ContentType "application/json" -Body '{"attendance_device_id":"","default_shift":""}' | Out-Null
    Write-Host "Cleared dummy WS-1001 from HR-EMP-00001"
}

# Remove dummy test Salary Structure Assignment / Salary Structure if created by test scripts
foreach ($doc in (Get-FrappeDocs "Salary Structure Assignment" '[["employee","=","HR-EMP-00001"]]' '["name","docstatus","salary_structure"]')) {
    if ($doc.salary_structure -eq "WS Standard Structure") {
        Cancel-And-Delete "Salary Structure Assignment" $doc.name $doc.docstatus
        Write-Host "Removed dummy Salary Structure Assignment $($doc.name)"
    }
}
foreach ($doc in (Get-FrappeDocs "Salary Structure" '[["name","=","WS Standard Structure"]]')) {
    Cancel-And-Delete "Salary Structure" $doc.name $doc.docstatus
    Write-Host "Removed dummy Salary Structure $($doc.name)"
}

# 3. Configure WorkSight Settings for real WorkSight API
Write-Host "`n--- Updating WorkSight Settings ---" -ForegroundColor Cyan
$settingsBody = @{
    enabled                       = 1
    api_base_url                  = "https://worksight.hashnate.com/api/v1"
    api_key                       = $ApiKey
    default_company               = "AR software"
    enable_api_polling_sync       = 1
    auto_create_missing_employees = 1
    default_timezone              = "Asia/Colombo"
    employee_match_field          = "attendance_device_id"
    default_log_type_mode         = "Use Payload or Alternate"
    auto_trigger_shift_sync       = 1
    enable_late_tracking          = 1
    late_grace_minutes            = 0
    late_deduction_mode           = "Hourly Rate"
    late_salary_component         = "Late Deduction"
    require_approval_for_late     = 0
    enable_overtime_tracking      = 1
    overtime_threshold_minutes    = 30
    overtime_rounding_minutes     = 15
    overtime_rate_mode            = "From Base Salary Hourly Rate"
    overtime_multiplier           = 1.5
    holiday_overtime_multiplier   = 2.0
    overtime_salary_component     = "Overtime"
    require_approval_for_overtime = 1
    auto_submit_additional_salary = 0
} | ConvertTo-Json

Invoke-RestMethod -Uri "$baseUrl/api/resource/WorkSight%20Settings/WorkSight%20Settings" -Method Put `
    -WebSession $wsSession -ContentType "application/json" -Body $settingsBody | Out-Null
Write-Host "WorkSight Settings updated for https://worksight.hashnate.com/api/v1"

# 4. Pull real WorkSchedules, Employees, and Attendance from WorkSight API
Write-Host "`n--- Syncing Real Employees, Shifts, and Attendance ($FromDate to $ToDate) ---" -ForegroundColor Cyan
$syncRes = Invoke-RestMethod -Uri "$baseUrl/api/method/worksight_hrms.worksight_hrms.services.worksight_client.sync_all" `
    -Method Post -WebSession $wsSession -ContentType "application/json" `
    -Body (@{ from_date = $FromDate; to_date = $ToDate; process_auto_attendance = 1 } | ConvertTo-Json)

$syncRes.message | ConvertTo-Json -Depth 6

Write-Host "`n--- Active Employees Synced ---" -ForegroundColor Green
Get-FrappeDocs "Employee" '[["status","=","Active"]]' '["name","employee_name","attendance_device_id","default_shift","department"]' | Format-Table -AutoSize

Write-Host "`n--- Recent Employee Checkins ---" -ForegroundColor Green
Get-FrappeDocs "Employee Checkin" '[]' '["name","employee","employee_name","time","log_type","shift","attendance"]' | Select-Object -First 20 | Format-Table -AutoSize

Write-Host "`n--- Recent Attendance ---" -ForegroundColor Green
Get-FrappeDocs "Attendance" '[]' '["name","employee","employee_name","attendance_date","status","working_hours","late_entry"]' | Select-Object -First 20 | Format-Table -AutoSize

Write-Host "`n--- WorkSight Late & Overtime Records ---" -ForegroundColor Green
Get-FrappeDocs "WorkSight Late Record" '[]' '["name","employee_name","attendance_date","late_minutes","billable_late_minutes","deduction_amount","status"]' | Format-Table -AutoSize
Get-FrappeDocs "WorkSight Overtime Record" '[]' '["name","employee_name","attendance_date","overtime_minutes","overtime_hours","overtime_amount","status"]' | Format-Table -AutoSize
