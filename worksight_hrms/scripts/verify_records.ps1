Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$baseUrl = "http://localhost:8000"
$secret = "worksight-dev3-secret"

$pwdSecure = Read-Host "Enter ERPNext Administrator password" -AsSecureString
$pwdPlain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($pwdSecure)
)

# 1. Log in to ERPNext Desk session
Invoke-RestMethod -Uri "$baseUrl/api/method/login" -Method Post -SessionVariable wsSession `
    -Body @{ usr = "Administrator"; pwd = $pwdPlain } | Out-Null

# 2. Ensure Day Shift sync window covers 2026-11-27
$shiftBody = @{
    last_sync_of_checkin = "2026-11-28 23:59:59"
} | ConvertTo-Json
Invoke-RestMethod -Uri "$baseUrl/api/resource/Shift%20Type/Day%20Shift" -Method Put `
    -WebSession $wsSession -ContentType "application/json" -Body $shiftBody | Out-Null

# 3. Ensure Employee HR-EMP-00001 has WS-1001 and Day Shift
$empBody = @{
    attendance_device_id = "WS-1001"
    default_shift        = "Day Shift"
} | ConvertTo-Json
Invoke-RestMethod -Uri "$baseUrl/api/resource/Employee/HR-EMP-00001" -Method Put `
    -WebSession $wsSession -ContentType "application/json" -Body $empBody | Out-Null

function Send-WorkSightPunch($eventId, $time, $logType) {
    $body = @{
        event_id             = $eventId
        attendance_device_id = "WS-1001"
        checkin_time         = $time
        log_type             = $logType
        device_id            = "FACE-GATE-1"
    } | ConvertTo-Json -Compress
    $hmac = [System.Security.Cryptography.HMACSHA256]::new([Text.Encoding]::UTF8.GetBytes($secret))
    $hash = ($hmac.ComputeHash([Text.Encoding]::UTF8.GetBytes($body)) | ForEach-Object { $_.ToString("x2") }) -join ""
    Invoke-RestMethod -Uri "$baseUrl/api/method/worksight_hrms.api.webhook.receive_checkin" `
        -Method Post -ContentType "application/json" `
        -Headers @{ "X-WorkSight-Signature" = "sha256=$hash" } -Body $body
}

function Get-FrappeList($doctype, $fieldsJson, $filtersJson) {
    $dt = [Uri]::EscapeDataString($doctype)
    $fields = [Uri]::EscapeDataString($fieldsJson)
    $filters = [Uri]::EscapeDataString($filtersJson)
    (Invoke-RestMethod -Uri "$baseUrl/api/resource/$dt`?fields=$fields&filters=$filters&order_by=creation%20desc&limit_page_length=20" `
        -WebSession $wsSession).data
}

# 4. Send fresh Late (09:45) + Overtime (18:40) punches on 2026-11-27 + Duplicate replay check
$tag = Get-Date -Format "yyyyMMddHHmmss"
$inEvt = "ws-late-in-$tag"
$outEvt = "ws-ot-out-$tag"

Write-Host "`n--- Sending Late IN (09:45) & Overtime OUT (18:40) on 2026-11-27 ---" -ForegroundColor Cyan
(Send-WorkSightPunch $inEvt  "2026-11-27T09:45:00+05:30" "IN").message  | ConvertTo-Json -Depth 5
(Send-WorkSightPunch $outEvt "2026-11-27T18:40:00+05:30" "OUT").message | ConvertTo-Json -Depth 5

Write-Host "`n--- Testing Duplicate Event Replay (expect duplicates = 1) ---" -ForegroundColor Cyan
(Send-WorkSightPunch $inEvt  "2026-11-27T09:45:00+05:30" "IN").message  | ConvertTo-Json -Depth 5

# 5. Inspect HR-EMP-00001 pipeline records
$empFilter = '[["employee","=","HR-EMP-00001"]]'

Write-Host "`n--- Employee Checkins ---" -ForegroundColor Green
Get-FrappeList "Employee Checkin" '["name","time","log_type","shift","attendance"]' $empFilter | Format-Table -AutoSize

Write-Host "`n--- Attendance ---" -ForegroundColor Green
Get-FrappeList "Attendance" '["name","attendance_date","status","working_hours","late_entry","docstatus"]' $empFilter | Format-Table -AutoSize

Write-Host "`n--- WorkSight Late Records ---" -ForegroundColor Green
Get-FrappeList "WorkSight Late Record" '["name","attendance_date","late_minutes","billable_late_minutes","deduction_amount","status","additional_salary"]' $empFilter | Format-Table -AutoSize

Write-Host "`n--- WorkSight Overtime Records ---" -ForegroundColor Green
Get-FrappeList "WorkSight Overtime Record" '["name","attendance_date","overtime_minutes","overtime_hours","overtime_amount","status","additional_salary"]' $empFilter | Format-Table -AutoSize

Write-Host "`n--- Additional Salary (Payroll Inputs) ---" -ForegroundColor Green
Get-FrappeList "Additional Salary" '["name","payroll_date","salary_component","amount","docstatus","ref_doctype","ref_docname"]' $empFilter | Format-Table -AutoSize

Write-Host "`nNEXT: Open http://erpnext.localhost:8000/desk/shift-type/Day%20Shift and click 'Mark Attendance', then re-run this script or check Desk." -ForegroundColor Yellow
