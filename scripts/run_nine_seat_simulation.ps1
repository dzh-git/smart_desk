[CmdletBinding()]
param(
    [ValidateRange(0, 1440)]
    [int]$DurationMinutes = 0
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$deskRoot = Join-Path $repoRoot "new_coding_desk"
$previousDuration = $env:SMARTDESK_NINE_SEAT_SOAK_SECONDS
try {
    if ($DurationMinutes -gt 0) {
        $env:SMARTDESK_NINE_SEAT_SOAK_SECONDS = [string](
            $DurationMinutes * 60
        )
    }
    elseif (-not $env:SMARTDESK_NINE_SEAT_SOAK_SECONDS) {
        $env:SMARTDESK_NINE_SEAT_SOAK_SECONDS = "0.1"
    }
    Push-Location -LiteralPath $deskRoot
    try {
        python -m pytest -q tests/test_nine_seat_integration.py
        exit $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
}
finally {
    $env:SMARTDESK_NINE_SEAT_SOAK_SECONDS = $previousDuration
}
