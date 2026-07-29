[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$deskRoot = Join-Path $repoRoot "new_coding_desk"
$streamRoot = Join-Path $deskRoot "host_services\screen_stream"
$runtimeRoot = Join-Path $deskRoot ".smartdesk-runtime\screen-stream"
$reportRoot = Join-Path $repoRoot "logs\verification"
New-Item -ItemType Directory -Force -Path $reportRoot | Out-Null
$supervisor = Start-Process -FilePath python `
    -ArgumentList @("supervisor.py") -WorkingDirectory $streamRoot `
    -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $reportRoot "screen-stream.out.log") `
    -RedirectStandardError (Join-Path $reportRoot "screen-stream.err.log")
try {
    $deadline = (Get-Date).AddSeconds(45)
    $ready = $false
    do {
        Start-Sleep -Milliseconds 750
        try {
            $response = Invoke-WebRequest -UseBasicParsing `
                "http://127.0.0.1:8889/screen" -TimeoutSec 2
            $ready = $response.StatusCode -eq 200
        }
        catch {}
    } while (-not $ready -and (Get-Date) -lt $deadline)
    if (-not $ready) { throw "MediaMTX stream page did not become ready." }
    Push-Location (Join-Path $deskRoot "frontend")
    try {
        npx playwright test e2e/screen-stream-live.spec.ts `
            --config=playwright.live.config.ts
        if ($LASTEXITCODE -ne 0) {
            throw "10-client Playwright stream test failed."
        }
    }
    finally { Pop-Location }
}
finally {
    $pidPaths = @(
        (Join-Path $runtimeRoot "ffmpeg.pid"),
        (Join-Path $runtimeRoot "mediamtx.pid")
    )
    foreach ($pidPath in $pidPaths) {
        if (Test-Path -LiteralPath $pidPath) {
            $childPid = [int](
                Get-Content -LiteralPath $pidPath -Encoding ASCII -Raw
            )
            Stop-Process -Id $childPid -Force -ErrorAction SilentlyContinue
        }
    }
    Stop-Process -Id $supervisor.Id -Force -ErrorAction SilentlyContinue
}
