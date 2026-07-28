[CmdletBinding()]
param(
    [ValidateSet("Full", "CI", "Fast")]
    [string]$Profile = "Full"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$results = [System.Collections.Generic.List[object]]::new()
$reportRoot = Join-Path $repoRoot "logs\verification"
New-Item -ItemType Directory -Force -Path $reportRoot | Out-Null
$transcriptPath = Join-Path $reportRoot "verify-all-software.log"
$jsonPath = Join-Path $reportRoot "verify-all-software.json"

function Add-Result {
    param(
        [string]$Name,
        [string]$Category,
        [string]$Status,
        [int]$ExitCode,
        [string]$Detail = ""
    )
    $results.Add([PSCustomObject]@{
        name = $Name
        category = $Category
        status = $Status
        exitCode = $ExitCode
        detail = $Detail
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
        $global:LASTEXITCODE = 0
        & $Action
        $code = if ($null -eq $LASTEXITCODE) { 0 } else { $LASTEXITCODE }
        if ($code -eq 0) {
            Add-Result $Name $Category "PASS" 0
        }
        else {
            Add-Result $Name $Category "FAIL" $code
        }
    }
    catch {
        Add-Result $Name $Category "FAIL" 1 $_.Exception.Message
    }
    finally {
        Pop-Location
    }
}

function Add-Skip {
    param(
        [string]$Name,
        [string]$Category,
        [string]$Detail
    )
    Write-Host ""
    Write-Host "[$Category] $Name - SKIP: $Detail"
    Add-Result $Name $Category "SKIP" 0 $Detail
}

function Test-CommandAvailable {
    param([string]$Name)
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

$deskRoot = Join-Path $repoRoot "new_coding_desk"
$frontendRoot = Join-Path $deskRoot "frontend"
$gestureRoot = Join-Path $repoRoot "smartdesk_gesture_controller"
$androidRoot = Join-Path $repoRoot "android_tablet\android-app"
$diagnosticRoot = Join-Path $repoRoot "android_tablet\diagnostic-web"
$faceModelPath = Join-Path $androidRoot `
    "app\src\main\assets\models\se_mobilefacenet_emb256_fp32.tflite"
$gradle = Join-Path $androidRoot "gradlew.bat"

if (-not $env:JAVA_HOME) {
    $javaCandidates = @(
        "D:\Program Files\Android\Android Studio\jbr",
        (Join-Path $env:ProgramFiles "Android\Android Studio\jbr")
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
    $javaHome = $javaCandidates | Select-Object -First 1
    if ($javaHome) {
        $env:JAVA_HOME = $javaHome
    }
}
if (-not $env:ANDROID_HOME) {
    $androidCandidates = @(
        (Join-Path $env:LOCALAPPDATA "Android\Sdk"),
        "D:\Android\Sdk"
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
    $androidHome = $androidCandidates | Select-Object -First 1
    if ($androidHome) {
        $env:ANDROID_HOME = $androidHome
    }
}
if ($env:ANDROID_HOME) {
    $env:ANDROID_SDK_ROOT = $env:ANDROID_HOME
}
$env:GRADLE_USER_HOME = Join-Path $repoRoot ".gradle-user-home"
$env:ANDROID_USER_HOME = Join-Path $repoRoot ".android-user-home"
$env:npm_config_cache = Join-Path $repoRoot ".npm-cache"
$env:PLATFORMIO_CORE_DIR = Join-Path $repoRoot ".tools\platformio-core"

Start-Transcript -Path $transcriptPath -Force | Out-Null
try {
    Invoke-Check "Python static compile" "REQUIRED" $repoRoot {
        python scripts\check_python_sources.py
    }
    Invoke-Check "Repository config/contracts" "REQUIRED" $repoRoot {
        python scripts\validate_repository_contracts.py
    }
    Invoke-Check "Prototype model-license declaration" "REQUIRED" $repoRoot {
        python scripts\check_model_license_gate.py --mode prototype
    }
    Invoke-Check "Release model-license block" "REQUIRED" $repoRoot {
        $previousErrorAction = $ErrorActionPreference
        try {
            # Windows PowerShell 5 wraps native stderr as NativeCommandError
            # when the caller uses Stop. This command is expected to write a
            # blocking reason to stderr, so capture its exit/output explicitly.
            $ErrorActionPreference = "Continue"
            $output = & python scripts\check_model_license_gate.py `
                --mode release 2>&1
            $releaseCode = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $previousErrorAction
        }
        $output | Write-Host
        if (
            $releaseCode -eq 0 -or
            ($output -join "`n") -notmatch "MODEL_LICENSE_GATE_BLOCKED"
        ) {
            throw "Current non-commercial model was not blocked."
        }
        $global:LASTEXITCODE = 0
    }

    if ($Profile -eq "CI") {
        Invoke-Check "Backend tests (model-independent)" "REQUIRED" $deskRoot {
            python -m pytest -q `
                --ignore=tests/test_translation_model_safety.py `
                --ignore=tests/test_speech_model_smoke.py `
                --ignore=tests/test_speech_stream_service.py `
                --ignore=tests/test_speech_websocket_blackbox.py
        }
        Add-Skip `
            "Backend real-model/runtime tests" `
            "OPTIONAL_ENVIRONMENT" `
            "CI profile omits Torch/FunASR/Transformers model runtimes."
    }
    elseif ($Profile -eq "Fast") {
        Invoke-Check "Backend core integration tests" "REQUIRED" $deskRoot {
            python -m pytest -q `
                tests/test_identity_checkin.py `
                tests/test_tablet_devices.py `
                tests/test_esp32_protocol.py `
                tests/test_esp32_websocket.py `
                tests/test_security_controls.py `
                tests/test_one_seat_integration.py
        }
        Add-Skip `
            "Backend remaining tests" `
            "OPTIONAL_ENVIRONMENT" `
            "Fast profile selected explicitly; use default Full profile."
    }
    else {
        Invoke-Check "Backend full non-soak pytest" "REQUIRED" $deskRoot {
            python -m pytest -q `
                --ignore=tests/test_speech_stream_service.py `
                --ignore=tests/test_speech_websocket_blackbox.py
        }
    }

    if ($Profile -ne "Fast") {
        if ($env:SMARTDESK_RUN_SLOW_SPEECH_TESTS -eq "true") {
            Invoke-Check `
                "Backend long-duration speech stream/WebSocket tests" `
                "OPTIONAL_ENVIRONMENT" `
                $deskRoot {
                    python -m pytest -q `
                        tests/test_speech_stream_service.py `
                        tests/test_speech_websocket_blackbox.py
                }
        }
        else {
            Add-Skip `
                "Backend long-duration speech stream/WebSocket tests" `
                "OPTIONAL_ENVIRONMENT" `
                (
                    "Known to exceed 20 minutes in this environment; set " +
                    "SMARTDESK_RUN_SLOW_SPEECH_TESTS=true to run explicitly."
                )
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
    Invoke-Check "Android diagnostic web build" "REQUIRED" $diagnosticRoot {
        npm run build
    }
    Invoke-Check "Gesture controller tests" "REQUIRED" $gestureRoot {
        python -m pytest -q
    }
    Invoke-Check "ESP32 protocol simulator tests" "REQUIRED" $repoRoot {
        python -m pytest -q esp32_seat_controller\simulator\tests
    }
    Invoke-Check "Seat 1 twenty-round core flow" "REQUIRED" $repoRoot {
        & (Join-Path $repoRoot "scripts\run_seat1_integration_test.ps1")
    }

    if (
        (Test-Path -LiteralPath $gradle) -and
        $env:JAVA_HOME -and
        ($env:ANDROID_HOME -or $env:ANDROID_SDK_ROOT)
    ) {
        Invoke-Check "Android JVM tests" "OPTIONAL_ENVIRONMENT" $androidRoot {
            & $gradle testDebugUnitTest --no-daemon `
                --no-configuration-cache --console=plain
        }
        Invoke-Check "Android Lint" "OPTIONAL_ENVIRONMENT" $androidRoot {
            & $gradle lintDebug --no-daemon `
                --no-configuration-cache --console=plain
        }
        Invoke-Check "Android debug APK compile" "OPTIONAL_ENVIRONMENT" $androidRoot {
            & $gradle assembleDebug --no-daemon `
                --no-configuration-cache --console=plain
        }
    }
    else {
        Add-Skip `
            "Android JVM/Lint/APK" `
            "OPTIONAL_ENVIRONMENT" `
            "Gradle wrapper, JAVA_HOME or Android SDK environment is missing."
    }

    if (Test-Path -LiteralPath $faceModelPath) {
        Add-Skip `
            "Android face-model packaging" `
            "OPTIONAL_ENVIRONMENT" `
            "Local research weight exists, but Release use is license-blocked."
    }
    else {
        Add-Skip `
            "Android face-model packaging" `
            "OPTIONAL_ENVIRONMENT" `
            "Private non-commercial research weight is intentionally absent."
    }

    if (Test-CommandAvailable "pio") {
        Invoke-Check "ESP32 firmware compile" "OPTIONAL_ENVIRONMENT" $repoRoot {
            $firmwareInclude = Join-Path $repoRoot `
                "esp32_seat_controller\firmware\include"
            $deviceConfig = Join-Path $firmwareInclude "DeviceConfig.h"
            $exampleConfig = Join-Path $firmwareInclude `
                "DeviceConfig.example.h"
            $temporaryConfig = $false
            try {
                if (-not (Test-Path -LiteralPath $deviceConfig)) {
                    Copy-Item -LiteralPath $exampleConfig `
                        -Destination $deviceConfig
                    $temporaryConfig = $true
                }
                pio run -d esp32_seat_controller\firmware --target clean
                if ($LASTEXITCODE -ne 0) {
                    throw "PlatformIO clean failed."
                }
                pio run -d esp32_seat_controller\firmware
            }
            finally {
                if ($temporaryConfig) {
                    Remove-Item -LiteralPath $deviceConfig -Force
                }
            }
        }
    }
    else {
        Add-Skip `
            "ESP32 firmware compile" `
            "OPTIONAL_ENVIRONMENT" `
            "PlatformIO CLI is not installed."
    }

    if ($env:SMARTDESK_RUN_SPEECH_E2E -eq "true") {
        Invoke-Check "Browser speech E2E" "OPTIONAL_ENVIRONMENT" $frontendRoot {
            npm run e2e:speech
        }
    }
    else {
        Add-Skip `
            "Browser speech E2E" `
            "OPTIONAL_ENVIRONMENT" `
            "Set SMARTDESK_RUN_SPEECH_E2E=true with backend and Chromium ready."
    }

    @(
        "Redmi K60 permissions/camera/microphone/WebView",
        "75-run face calibration and stranger false-accept check",
        "ESP32/PIR/VL53L0X/WS2812B wiring and power",
        "Real LAN recovery, 30-minute speech, one-seat and nine-seat soak"
    ) | ForEach-Object {
        Add-Skip $_ "HARDWARE_REQUIRED" `
            "See docs/integration/HUMAN_VALIDATION_REQUIRED.md."
    }
}
finally {
    Stop-Transcript | Out-Null
}

$summary = [PSCustomObject]@{
    schemaVersion = 1
    generatedAt = [DateTimeOffset]::Now.ToString("o")
    profile = $Profile
    results = $results
}
$summary | ConvertTo-Json -Depth 5 | Set-Content `
    -LiteralPath $jsonPath -Encoding UTF8

Write-Host ""
Write-Host "SmartDesk software verification summary"
$results | Format-Table name, category, status, exitCode -AutoSize
Write-Host "Transcript: $transcriptPath"
Write-Host "JSON report: $jsonPath"

$failures = @($results | Where-Object { $_.status -eq "FAIL" })
if ($failures.Count -gt 0) {
    exit 1
}
exit 0
