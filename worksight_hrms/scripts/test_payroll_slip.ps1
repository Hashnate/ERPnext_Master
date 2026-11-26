param(
    [switch]$Submit
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$baseUrl = "http://localhost:8000"
$pwdSecure = Read-Host "Enter ERPNext Administrator password" -AsSecureString
$pwdPlain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($pwdSecure)
)

Invoke-RestMethod -Uri "$baseUrl/api/method/login" -Method Post -SessionVariable wsSession `
    -Body @{ usr = "Administrator"; pwd = $pwdPlain } | Out-Null

# 1. Ensure a Holiday List covering Nov 2026 exists and is assigned
$hlFilter = [Uri]::EscapeDataString('[["from_date","<=","2026-11-01"],["to_date",">=","2026-11-30"]]')
$hlList = (Invoke-RestMethod -Uri "$baseUrl/api/resource/Holiday%20List?filters=$hlFilter" `
    -WebSession $wsSession).data

if ($hlList.Count -gt 0) {
    $hlName = $hlList[0].name
} else {
    $hlBody = @{
        holiday_list_name = "WS 2026 Holiday List"
        from_date         = "2026-01-01"
        to_date           = "2026-12-31"
    } | ConvertTo-Json
    $hlName = (Invoke-RestMethod -Uri "$baseUrl/api/resource/Holiday%20List" -Method Post `
        -WebSession $wsSession -ContentType "application/json" -Body $hlBody).data.name
}

Invoke-RestMethod -Uri "$baseUrl/api/resource/Company/AR%20software" -Method Put `
    -WebSession $wsSession -ContentType "application/json" `
    -Body (@{ default_holiday_list = $hlName } | ConvertTo-Json) | Out-Null

Invoke-RestMethod -Uri "$baseUrl/api/resource/Employee/HR-EMP-00001" -Method Put `
    -WebSession $wsSession -ContentType "application/json" `
    -Body (@{ holiday_list = $hlName } | ConvertTo-Json) | Out-Null

# 2. Inspect Holiday List Assignment schema and create assignment for HR-EMP-00001 / AR software
$hlaMeta = (Invoke-RestMethod -Uri "$baseUrl/api/resource/DocType/Holiday%20List%20Assignment" `
    -WebSession $wsSession).data
$fieldNames = @($hlaMeta.fields | ForEach-Object { $_.fieldname })

$hlaList = (Invoke-RestMethod -Uri "$baseUrl/api/resource/Holiday%20List%20Assignment?limit_page_length=20" `
    -WebSession $wsSession).data

if ($hlaList.Count -eq 0) {
    $hlaBody = @{ holiday_list = $hlName }
    if ($fieldNames -contains "from_date") { $hlaBody["from_date"] = "2026-01-01" }
    if ($fieldNames -contains "to_date") { $hlaBody["to_date"] = "2026-12-31" }
    if ($fieldNames -contains "applicable_for") { $hlaBody["applicable_for"] = "Company" }
    if ($fieldNames -contains "assigned_to") { $hlaBody["assigned_to"] = "AR software" }
    if ($fieldNames -contains "company") { $hlaBody["company"] = "AR software" }
    if ($hlaMeta.is_submittable -eq 1) { $hlaBody["docstatus"] = 1 }

    $createdHla = Invoke-RestMethod -Uri "$baseUrl/api/resource/Holiday%20List%20Assignment" -Method Post `
        -WebSession $wsSession -ContentType "application/json" -Body ($hlaBody | ConvertTo-Json)
    Write-Host "Created Holiday List Assignment: $($createdHla.data.name)" -ForegroundColor Yellow
}

# 3. Create or load Salary Slip for Nov 2026
$slipFilter = [Uri]::EscapeDataString('[["employee","=","HR-EMP-00001"],["start_date","=","2026-11-01"],["end_date","=","2026-11-30"],["docstatus","!=",2]]')
$existing = (Invoke-RestMethod -Uri "$baseUrl/api/resource/Salary%20Slip?filters=$slipFilter" `
    -WebSession $wsSession).data

if ($existing.Count -gt 0) {
    $slipName = $existing[0].name
    $slip = (Invoke-RestMethod -Uri "$baseUrl/api/resource/Salary%20Slip/$([Uri]::EscapeDataString($slipName))" `
        -WebSession $wsSession).data
} else {
    $body = @{
        employee          = "HR-EMP-00001"
        company           = "AR software"
        payroll_frequency = "Monthly"
        posting_date      = "2026-11-30"
        start_date        = "2026-11-01"
        end_date          = "2026-11-30"
        docstatus         = $(if ($Submit) { 1 } else { 0 })
    } | ConvertTo-Json
    $slip = (Invoke-RestMethod -Uri "$baseUrl/api/resource/Salary%20Slip" -Method Post `
        -WebSession $wsSession -ContentType "application/json" -Body $body).data
}

if ($Submit -and $slip.docstatus -eq 0) {
    $slip = (Invoke-RestMethod -Uri "$baseUrl/api/resource/Salary%20Slip/$([Uri]::EscapeDataString($slip.name))" `
        -Method Put -WebSession $wsSession -ContentType "application/json" -Body (@{ docstatus = 1 } | ConvertTo-Json)).data
}

Write-Host "`nSalary Slip: $($slip.name) | Status: $($slip.status) | DocStatus: $($slip.docstatus)" -ForegroundColor Cyan
Write-Host "Gross Pay: $($slip.gross_pay) | Total Deduction: $($slip.total_deduction) | Net Pay: $($slip.net_pay)" -ForegroundColor Green

Write-Host "`n--- Earnings ---" -ForegroundColor Green
$slip.earnings | Select-Object salary_component, amount | Format-Table -AutoSize

Write-Host "`n--- Deductions ---" -ForegroundColor Green
$slip.deductions | Select-Object salary_component, amount | Format-Table -AutoSize
