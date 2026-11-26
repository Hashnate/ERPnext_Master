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
