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

# If HRMS uses Holiday List Assignment (v16/v17), ensure a submitted assignment exists
try {
    $hlaFilter = [Uri]::EscapeDataString('[["docstatus","=",1],["from_date","<=","2026-11-01"],["to_date",">=","2026-11-30"]]')
    $hlaExisting = (Invoke-RestMethod -Uri "$baseUrl/api/resource/Holiday%20List%20Assignment?filters=$hlaFilter" `
        -WebSession $wsSession).data
    if ($hlaExisting.Count -eq 0) {
        $hlaBody = @{
            applicable_for = "Company"
            assigned_to    = "AR software"
            holiday_list   = $hlName
            from_date      = "2026-01-01"
            to_date        = "2026-12-31"
            docstatus      = 1
        } | ConvertTo-Json
        try {
            Invoke-RestMethod -Uri "$baseUrl/api/resource/Holiday%20List%20Assignment" -Method Post `
                -WebSession $wsSession -ContentType "application/json" -Body $hlaBody | Out-Null
        } catch {
            # Fallback if field is named 'company' instead of 'assigned_to'
            $hlaBodyAlt = @{
                applicable_for = "Company"
                company        = "AR software"
                holiday_list   = $hlName
                from_date      = "2026-01-01"
                to_date        = "2026-12-31"
                docstatus      = 1
            } | ConvertTo-Json
            Invoke-RestMethod -Uri "$baseUrl/api/resource/Holiday%20List%20Assignment" -Method Post `
                -WebSession $wsSession -ContentType "application/json" -Body $hlaBodyAlt | Out-Null
        }
    }
} catch {
    # Holiday List Assignment DocType not present or already handled via Company/Employee
}

# 2. Create or load Salary Slip for Nov 2026
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
