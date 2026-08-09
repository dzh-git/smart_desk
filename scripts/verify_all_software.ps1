[CmdletBinding()]
param(
    [ValidateSet("Full", "CI", "Fast")]
    [string]$Profile = "Full",
    [ValidateRange(-1, 1440)]
    [int]$NineSeatSoakMinutes = -1
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "SmartDesk .venv is missing. Run SETUP_PYTHON.bat first."
}
$env:PYTHONUTF8 = "1"
& $python (Join-Path $PSScriptRoot "check_python_runtime.py")
if ($LASTEXITCODE -ne 0) {
    throw "SmartDesk requires the repository Python 3.11 environment."
}
$env:Path = "$(Split-Path -Parent $python);$env:Path"
$platformioScripts = Join-Path $repoRoot ".tools\platformio-venv\Scripts"
if (Test-Path -LiteralPath $platformioScripts) {
    $env:Path = "$(Split-Path -Parent $python);$platformioScripts;$env:Path"
}
$results = [System.Collections.Generic.List[object]]::new()
$reportRoot = Join-Path $repoRoot "logs\verification"
New-Item -ItemType Directory -Force -Path $reportRoot | Out-Null
$transcriptPath = Join-Path $reportRoot "verify-all-software.log"
$jsonPath = Join-Path $reportRoot "verify-all-software.json"
$htmlPath = Join-Path $reportRoot "verify-all-software.html"

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
    Invoke-Check "Tracked secrets/models/build artifacts" "REQUIRED" $repoRoot {
        python scripts\check_repository_hygiene.py
    }
    Invoke-Check "Repository config/contracts" "REQUIRED" $repoRoot {
        python scripts\validate_repository_contracts.py
    }
    Invoke-Check "Portable internal-demo package contracts" "REQUIRED" $repoRoot {
        python scripts\validate_portable_package.py
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
                --ignore=tests/test_bidirectional_translation.py `
                --ignore=tests/test_translation_model_service.py `
                --ignore=tests/test_speech_model_smoke.py `
                --ignore=tests/test_speech_real_dataset_benchmark.py `
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
    $actualSoakMinutes = if ($NineSeatSoakMinutes -ge 0) {
        $NineSeatSoakMinutes
    }
    elseif ($Profile -eq "Full") { 30 }
    else { 0 }
    Invoke-Check "Nine-seat burst/restart/recovery simulation" "REQUIRED" $repoRoot {
        & (Join-Path $repoRoot "scripts\run_nine_seat_simulation.ps1") `
            -DurationMinutes $actualSoakMinutes
    }
    Invoke-Check "Database backup/migration/rollback" "REQUIRED" $deskRoot {
        python -m pytest -q tests/test_database_maintenance.py
    }
    Invoke-Check "Windows/Arduino compatibility and ESP32 rejection" `
        "REQUIRED" $deskRoot {
            python -m pytest -q `
                tests/test_esp32_websocket.py `
                tests/test_lighting_state_resolver.py `
                tests/test_display_agent.py `
                tests/test_display_agent_review_contract.py
    }
    if ($Profile -eq "Full") {
        Invoke-Check "PCM long-speech and seat-routing tests" `
            "REQUIRED" $deskRoot {
                python -m pytest -q `
                    tests/test_long_speech_rollover.py `
                    tests/test_speech_lifecycle_stability.py `
                    tests/test_live_asr_routing.py
        }
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

    $debugApk = Join-Path $androidRoot (
        "app\build\outputs\apk\debug\app-debug.apk"
    )
    if (Test-Path -LiteralPath $debugApk) {
        $packageCommit = (& git -C $repoRoot rev-parse --short=12 HEAD).Trim()
        $portableOutput = Join-Path $repoRoot (
            "artifacts\SmartDesk-$packageCommit"
        )
        Invoke-Check "Portable package build" "REQUIRED" $repoRoot {
            & (Join-Path $repoRoot (
                "deployment\portable\build-portable.ps1"
            )) -SkipBuild
        }
        Invoke-Check "Install/upgrade/rollback/uninstall lifecycle" `
            "REQUIRED" $repoRoot {
                & (Join-Path $repoRoot (
                    "scripts\test_portable_lifecycle.ps1"
                )) -PackageRoot $portableOutput
        }
    }
    else {
        Add-Skip `
            "Portable package lifecycle" `
            "OPTIONAL_ENVIRONMENT" `
            "Android debug APK is unavailable; build it first."
    }

    $adbCommand = Get-Command adb -ErrorAction SilentlyContinue
    $adbExecutable = if ($adbCommand) { $adbCommand.Source } elseif (
        $env:ANDROID_HOME -and (
            Test-Path -LiteralPath (
                Join-Path $env:ANDROID_HOME "platform-tools\adb.exe"
            )
        )
    ) {
        Join-Path $env:ANDROID_HOME "platform-tools\adb.exe"
    } else { $null }
    if ($adbExecutable) {
        $connectedDevices = @(
            (& $adbExecutable devices) |
            Select-String "^\S+\s+device$"
        )
        if ($connectedDevices.Count -eq 1) {
            Invoke-Check "Connected Android install/start smoke" `
                "OPTIONAL_ENVIRONMENT" $repoRoot {
                    & (Join-Path $repoRoot (
                        "scripts\verify_android_device.ps1"
                    ))
            }
        }
        else {
            Add-Skip `
                "Connected Android install/start smoke" `
                "HARDWARE_REQUIRED" `
                "Connect exactly one unlocked Android device."
        }
    }
    else {
        Add-Skip `
            "Connected Android install/start smoke" `
            "HARDWARE_REQUIRED" `
            "ADB is unavailable."
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

    $screenFfmpeg = Join-Path $deskRoot "tools\ffmpeg\bin\ffmpeg.exe"
    $screenMediaMtx = Join-Path $deskRoot "tools\mediamtx\mediamtx.exe"
    if (
        $Profile -eq "Full" -and
        (Test-Path -LiteralPath $screenFfmpeg) -and
        (Test-Path -LiteralPath $screenMediaMtx) -and
        (Test-Path -LiteralPath (
            Join-Path $frontendRoot "node_modules\playwright"
        ))
    ) {
        Invoke-Check "Screen stream 10 clients and FFmpeg recovery" `
            "OPTIONAL_ENVIRONMENT" $repoRoot {
                & (Join-Path $repoRoot (
                    "scripts\verify_screen_stream_live.ps1"
                ))
        }
    }
    else {
        Add-Skip `
            "Screen stream 10 clients and FFmpeg recovery" `
            "OPTIONAL_ENVIRONMENT" `
            "Full profile requires local FFmpeg, MediaMTX and Playwright."
    }
    if ($env:SMARTDESK_RUN_POWERPOINT_GUI -eq "true") {
        Invoke-Check "PowerPoint Display Agent switch" `
            "OPTIONAL_ENVIRONMENT" $repoRoot {
                & (Join-Path $repoRoot (
                    "scripts\verify_powerpoint_switch.ps1"
                )) -AllowVisibleWindow
        }
    }
    else {
        Add-Skip `
            "PowerPoint Display Agent switch" `
            "OPTIONAL_ENVIRONMENT" `
            "Set SMARTDESK_RUN_POWERPOINT_GUI=true; a window will be visible."
    }

    @(
        "Redmi K60 permissions/camera/microphone/WebView",
        "75-run face calibration and stranger false-accept check",
        "ESP32/PIR/VL53L0X/WS2812B wiring and power",
        "Real LAN recovery, real microphone, physical one-seat/nine-seat soak"
    ) | ForEach-Object {
        Add-Skip $_ "HARDWARE_REQUIRED" `
            "See docs/integration/HUMAN_VALIDATION_REQUIRED.md."
    }
}
finally {
    Stop-Transcript | Out-Null
}

$summary = [PSCustomObject]@{
    schemaVersion = 2
    generatedAt = [DateTimeOffset]::Now.ToString("o")
    profile = $Profile
    commit = (& git -C $repoRoot rev-parse HEAD).Trim()
    nineSeatSoakMinutes = $actualSoakMinutes
    results = $results
}
$summary | ConvertTo-Json -Depth 5 | Set-Content `
    -LiteralPath $jsonPath -Encoding UTF8

$rows = foreach ($result in $results) {
    $name = [Net.WebUtility]::HtmlEncode($result.name)
    $category = [Net.WebUtility]::HtmlEncode($result.category)
    $status = [Net.WebUtility]::HtmlEncode($result.status)
    $detail = [Net.WebUtility]::HtmlEncode($result.detail)
    "<tr><td>$name</td><td>$category</td><td>$status</td><td>$detail</td></tr>"
}
@"
<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>SmartDesk 软件验证</title>
<style>
body{font-family:Segoe UI,sans-serif;margin:2rem;color:#17202a}
table{border-collapse:collapse;width:100%}th,td{border:1px solid #ccd1d1;
padding:.45rem;text-align:left}th{background:#eef2f3}
</style></head><body>
<h1>SmartDesk 软件验证</h1>
<p>Profile: $Profile · Commit: $($summary.commit) · Generated:
$($summary.generatedAt)</p>
<table><thead><tr><th>检查</th><th>类别</th><th>结果</th><th>说明</th></tr>
</thead><tbody>$($rows -join "`n")</tbody></table>
<p>报告不包含令牌、人脸照片、embedding、原始语音或真实数据库。</p>
</body></html>
"@ | Set-Content -LiteralPath $htmlPath -Encoding UTF8

$archivePath = Join-Path $reportRoot (
    "smartdesk-validation-$($summary.commit.Substring(0, 12)).zip"
)
if (Test-Path -LiteralPath $archivePath) {
    Remove-Item -LiteralPath $archivePath -Force
}
Compress-Archive -Path $jsonPath, $htmlPath, $transcriptPath `
    -DestinationPath $archivePath -CompressionLevel Optimal

Write-Host ""
Write-Host "SmartDesk software verification summary"
$results | Format-Table name, category, status, exitCode -AutoSize
Write-Host "Transcript: $transcriptPath"
Write-Host "JSON report: $jsonPath"
Write-Host "HTML report: $htmlPath"
Write-Host "Artifact: $archivePath"

$failures = @($results | Where-Object { $_.status -eq "FAIL" })
if ($failures.Count -gt 0) {
    exit 1
}
exit 0
