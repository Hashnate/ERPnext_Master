Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$baseUrl = "http://localhost:8000"
$pwdSecure = Read-Host "Enter ERPNext Administrator password" -AsSecureString
$pwdPlain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($pwdSecure)
)

# 1. Log in to ERPNext Desk session
Invoke-RestMethod -Uri "$baseUrl/api/method/login" -Method Post -SessionVariable wsSession `
    -Body @{ usr = "Administrator"; pwd = $pwdPlain } | Out-Null

# 2. Configure Day Shift for Auto Attendance
$shiftBody = @{
    enable_auto_attendance                 = 1
    determine_check_in_and_check_out       = "Alternating entries as IN and OUT during the same shift"
    working_hours_calculation_based_on     = "First Check-in and Last Check-out"
    begin_check_in_before_shift_start_time = 60
    allow_check_out_after_shift_end_time   = 240
    process_attendance_after               = "2026-11-24"
    last_sync_of_checkin                   = "2026-11-26 23:59:59"
    enable_late_entry_marking              = 1
    late_entry_grace_period                = 15
} | ConvertTo-Json
Invoke-RestMethod -Uri "$baseUrl/api/resource/Shift%20Type/Day%20Shift" -Method Put `
    -WebSession $wsSession -ContentType "application/json" -Body $shiftBody | Out-Null

# 3. Link Employee HR-EMP-00001 to WS-1001 and Day Shift
$empBody = @{
    attendance_device_id = "WS-1001"
    default_shift        = "Day Shift"
} | ConvertTo-Json
Invoke-RestMethod -Uri "$baseUrl/api/resource/Employee/HR-EMP-00001" -Method Put `
    -WebSession $wsSession -ContentType "application/json" -Body $empBody | Out-Null

# 4. Ensure Salary Structure & Salary Structure Assignment exist
$ssFilter = [Uri]::EscapeDataString('[["company","=","AR software"],["docstatus","=",1]]')
$ssList = (Invoke-RestMethod -Uri "$baseUrl/api/resource/Salary%20Structure?filters=$ssFilter" `
    -WebSession $wsSession).data
if ($ssList.Count -eq 0) {
    $ssBody = @{
        __newname         = "WS Standard Structure"
        company           = "AR software"
        currency          = "LKR"
        is_active         = "Yes"
        payroll_frequency = "Monthly"
        docstatus         = 1
        earnings          = @(@{ salary_component = "Basic"; amount_based_on_formula = 1; formula = "base" })
    } | ConvertTo-Json -Depth 4
    $ssName = (Invoke-RestMethod -Uri "$baseUrl/api/resource/Salary%20Structure" -Method Post `
        -WebSession $wsSession -ContentType "application/json" -Body $ssBody).data.name
} else {
    $ssName = $ssList[0].name
}

$ssaFilter = [Uri]::EscapeDataString('[["employee","=","HR-EMP-00001"],["docstatus","=",1]]')
$ssaList = (Invoke-RestMethod -Uri "$baseUrl/api/resource/Salary%20Structure%20Assignment?filters=$ssaFilter" `
    -WebSession $wsSession).data
if ($ssaList.Count -eq 0) {
    $ssaBody = @{
        employee         = "HR-EMP-00001"
        salary_structure = $ssName
        company          = "AR software"
        currency         = "LKR"
        from_date        = "2026-01-01"
        base             = 208000
        docstatus        = 1
    } | ConvertTo-Json
    Invoke-RestMethod -Uri "$baseUrl/api/resource/Salary%20Structure%20Assignment" -Method Post `
        -WebSession $wsSession -ContentType "application/json" -Body $ssaBody | Out-Null
}

# 5. Send fresh signed WorkSight IN + OUT webhooks
$secret = "worksight-dev3-secret"
$tag = Get-Date -Format "yyyyMMddHHmmss"

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
        -Headers @{ "X-WorkSight-Signature" = "sha256=$hash" } -Body $body | ConvertTo-Json -Depth 5
}

Send-WorkSightPunch "ws-in-$tag"  "2026-11-25T09:45:00+05:30" "IN"
Send-WorkSightPunch "ws-out-$tag" "2026-11-25T18:40:00+05:30" "OUT"
