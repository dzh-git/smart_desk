[CmdletBinding()]
param(
    [switch]$SkipSlowBackend
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$results = [System.Collections.Generic.List[object]]::new()

function Add-Result {
    param(
        [string]$Name,
        [string]$Category,
        [string]$Status,
        [int]$ExitCode,
        [string]$Detail = ""
    )
    $results.Add([PSCustomObject]@{
        Name = $Name
        Category = $Category
        Status = $Status
        ExitCode = $ExitCode
        Detail = $Detail
    })
}

function Invoke-Check {
    param(
        [string]$Name,
        [string]$Category,
        [string]$WorkingDirectory,
        [scriptblock]$Action
    )

    Write-Host ""
    Write-Host "[$Category] $Name"
    Push-Location -LiteralPath $WorkingDirectory
    try {
        & $Action
        $code = $LASTEXITCODE
        if ($null -eq $code) {
            $code = 0
        }
        if ($code -eq 0) {
            Add-Result $Name $Category "PASS" 0
        } else {
            Add-Result $Name $Category "FAIL" $code
        }
    } catch {
        Add-Result $Name $Category "FAIL" 1 $_.Exception.Message
    } finally {
        Pop-Location
    }
}

$deskRoot = Join-Path $repoRoot "new_coding_desk"
$frontendRoot = Join-Path $deskRoot "frontend"
$gestureRoot = Join-Path $repoRoot "smartdesk_gesture_controller"
$androidRoot = Join-Path $repoRoot "android_tablet\android-app"
$diagnosticRoot = Join-Path $repoRoot "android_tablet\diagnostic-web"

if ($SkipSlowBackend) {
    Add-Result `
        "Backend full pytest" `
        "OPTIONAL_ENVIRONMENT" `
        "SKIP" `
        0 `
        "Explicitly skipped with -SkipSlowBackend"
} else {
    Invoke-Check "Backend full pytest" "REQUIRED" $deskRoot {
        python -m pytest -q
    }
}

Invoke-Check "Frontend typecheck" "REQUIRED" $frontendRoot {
    npm run typecheck
}
Invoke-Check "Frontend unit tests" "REQUIRED" $frontendRoot {
    npm test -- --run
}
Invoke-Check "Frontend production build" "REQUIRED" $frontendRoot {
    npm run build
}
Invoke-Check "Gesture controller tests" "REQUIRED" $gestureRoot {
    python -m pytest -q
}
Invoke-Check "Android diagnostic web build" "REQUIRED" $diagnosticRoot {
    npm run build
}

$gradle = Join-Path $androidRoot "gradlew.bat"
if (Test-Path -LiteralPath $gradle) {
    Invoke-Check "Android JVM tests" "OPTIONAL_ENVIRONMENT" $androidRoot {
        & $gradle testDebugUnitTest --no-daemon --no-configuration-cache --console=plain
    }
    Invoke-Check "Android lint" "OPTIONAL_ENVIRONMENT" $androidRoot {
        & $gradle lintDebug --no-daemon --no-configuration-cache --console=plain
    }
    Invoke-Check "Android debug APK compile" "OPTIONAL_ENVIRONMENT" $androidRoot {
        & $gradle assembleDebug --no-daemon --no-configuration-cache --console=plain
    }
} else {
    Add-Result `
        "Android Gradle checks" `
        "OPTIONAL_ENVIRONMENT" `
        "FAIL" `
        1 `
        "android_tablet/android-app/gradlew.bat is missing"
}

$protocolTests = Join-Path $repoRoot "esp32_seat_controller\simulator\tests"
if (Test-Path -LiteralPath $protocolTests) {
    Invoke-Check "ESP32 protocol simulator tests" "REQUIRED" $repoRoot {
        python -m pytest -q $protocolTests
    }
} else {
    Add-Result `
        "ESP32 protocol simulator tests" `
        "REQUIRED" `
        "FAIL" `
        1 `
        "Simulator has not been implemented yet"
}

Write-Host ""
Write-Host "Software baseline summary"
$results | Format-Table -AutoSize

$requiredFailures = @(
    $results | Where-Object {
        $_.Category -eq "REQUIRED" -and $_.Status -eq "FAIL"
    }
)
if ($requiredFailures.Count -gt 0) {
    exit 1
}
exit 0
