[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "SmartDesk .venv is missing. Run SETUP_PYTHON.bat first."
}
$env:PYTHONUTF8 = "1"
& $python (Join-Path $PSScriptRoot "check_python_runtime.py")
if ($LASTEXITCODE -ne 0) { throw "SmartDesk requires Python 3.11." }
$deskRoot = Join-Path $repoRoot "new_coding_desk"
$frontendRoot = Join-Path $deskRoot "frontend"

Write-Host "[REQUIRED] Backend + ESP32 twenty-round seat 1 closure"
Push-Location -LiteralPath $deskRoot
try {
    & $python -m pytest -q `
        tests/test_one_seat_integration.py `
        tests/test_esp32_protocol.py `
        tests/test_esp32_websocket.py
    if ($LASTEXITCODE -ne 0) {
        throw "Backend/ESP32 seat 1 integration failed."
    }
}
finally {
    Pop-Location
}

Write-Host "[REQUIRED] Frontend Mock NativeBridge identity replay"
Push-Location -LiteralPath $frontendRoot
try {
    npm test -- --run src/__tests__/seat.test.tsx `
        -t "Android identity check-in"
    if ($LASTEXITCODE -ne 0) {
        throw "Frontend NativeBridge identity replay failed."
    }
}
finally {
    Pop-Location
}

Write-Host "Seat 1 software integration: PASS (20 rounds)"
