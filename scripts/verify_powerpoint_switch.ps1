[CmdletBinding()]
param([switch]$AllowVisibleWindow)

$ErrorActionPreference = "Stop"
if (-not $AllowVisibleWindow) {
    throw "Pass -AllowVisibleWindow because PowerPoint will briefly be visible."
}
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "SmartDesk .venv is missing. Run SETUP_PYTHON.bat first."
}
$env:PYTHONUTF8 = "1"
& $python (Join-Path $PSScriptRoot "check_python_runtime.py")
if ($LASTEXITCODE -ne 0) { throw "SmartDesk requires Python 3.11." }
$agentRoot = Join-Path $repoRoot (
    "new_coding_desk\host_services\display_agent"
)
$reportRoot = Join-Path $repoRoot "logs\verification"
New-Item -ItemType Directory -Force -Path $reportRoot | Out-Null
$powerPointCandidates = @(
    "C:\Program Files\Microsoft Office\root\Office16\POWERPNT.EXE",
    "C:\Program Files (x86)\Microsoft Office\root\Office16\POWERPNT.EXE"
)
$powerPoint = $powerPointCandidates | Where-Object {
    Test-Path -LiteralPath $_
} | Select-Object -First 1
if (-not $powerPoint) { throw "PowerPoint is not installed." }

$existingPowerPoint = @(Get-Process POWERPNT -ErrorAction SilentlyContinue)
$existingPowerPointIds = @($existingPowerPoint | ForEach-Object Id)
$powerPointCom = $null
$testPresentation = $null
$agent = Start-Process -FilePath $python -ArgumentList @("agent.py") `
    -WorkingDirectory $agentRoot -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $reportRoot "display-agent.out.log") `
    -RedirectStandardError (Join-Path $reportRoot "display-agent.err.log")
try {
    if ($existingPowerPoint.Count -eq 0) {
        $powerPointCom = New-Object -ComObject PowerPoint.Application
        $powerPointCom.Visible = -1
        $testPresentation = $powerPointCom.Presentations.Add()
    }
    $deadline = (Get-Date).AddSeconds(30)
    do {
        Start-Sleep -Milliseconds 500
        try {
            $health = Invoke-RestMethod "http://127.0.0.1:8766/health" `
                -TimeoutSec 2
        }
        catch { $health = $null }
    } while (-not $health -and (Get-Date) -lt $deadline)
    if (-not $health) { throw "Display Agent did not become healthy." }
    $powerPointDeadline = (Get-Date).AddSeconds(20)
    do {
        Start-Sleep -Milliseconds 500
        $powerPointWindows = @(
            Get-Process POWERPNT -ErrorAction SilentlyContinue |
            Where-Object { $_.MainWindowHandle -ne 0 }
        )
    } while (
        $powerPointWindows.Count -eq 0 -and
        (Get-Date) -lt $powerPointDeadline
    )
    if ($powerPointWindows.Count -eq 0) {
        throw "PowerPoint did not create a visible window."
    }
    $response = Invoke-RestMethod -Method Post `
        -Uri "http://127.0.0.1:8766/activate" `
        -ContentType "application/json" -Body '{"app":"powerpoint"}' `
        -TimeoutSec 15
    if (-not $response.ok) {
        throw (
            "Display Agent could not activate PowerPoint: " +
            "$($response.action); $($response.detail)"
        )
    }
    [PSCustomObject]@{
        schemaVersion = 1
        generatedAt = [DateTimeOffset]::Now.ToString("o")
        application = "powerpoint"
        status = "PASS"
        action = $response.action
    } | ConvertTo-Json | Set-Content -LiteralPath (
        Join-Path $reportRoot "powerpoint-switch.json"
    ) -Encoding UTF8
    Write-Host "POWERPOINT_SWITCH_PASS: $($response.action)"
}
finally {
    Stop-Process -Id $agent.Id -Force -ErrorAction SilentlyContinue
    if ($testPresentation) {
        try { $testPresentation.Close() } catch {}
    }
    if ($powerPointCom) {
        try { $powerPointCom.Quit() } catch {}
    }
    @(Get-Process POWERPNT -ErrorAction SilentlyContinue) |
        Where-Object { $_.Id -notin $existingPowerPointIds } |
        Stop-Process -Force -ErrorAction SilentlyContinue
}
