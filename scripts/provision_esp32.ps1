[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = "Medium")]
param(
    [Parameter(Mandatory)]
    [ValidateRange(1, 9)]
    [int]$SeatId,

    [string]$DeviceConfigPath = "",

    [string]$CredentialStorePath = "",

    [switch]$SkipFlash,

    [switch]$SkipRestart,

    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$firmwareRoot = Join-Path $repoRoot "esp32_seat_controller\firmware"
$defaultConfigPath = Join-Path $firmwareRoot "include\DeviceConfig.h"
$pioLauncher = Join-Path $repoRoot "PIO.bat"
$smartDeskRoot = Join-Path $repoRoot "new_coding_desk"
$smartDeskStart = Join-Path $smartDeskRoot "start.bat"
$smartDeskStop = Join-Path $smartDeskRoot "kill.bat"
$pythonRuntime = Join-Path $repoRoot ".venv\Scripts\python.exe"
$pythonRuntimeCheck = Join-Path $repoRoot "scripts\check_python_runtime.py"
$credentialEnvironmentName = "SMARTDESK_ESP32_DEVICE_TOKENS_JSON"
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)

if ([string]::IsNullOrWhiteSpace($DeviceConfigPath)) {
    $DeviceConfigPath = $defaultConfigPath
}

function Get-SingleConfigValue {
    param(
        [Parameter(Mandatory)][string]$Content,
        [Parameter(Mandatory)][string]$Pattern,
        [Parameter(Mandatory)][string]$FieldName
    )

    $matches = [regex]::Matches($Content, $Pattern)
    if ($matches.Count -ne 1) {
        throw "DeviceConfig.h must define exactly one $FieldName value."
    }
    return $matches[0].Groups[1].Value
}

function Set-SingleConfigValue {
    param(
        [Parameter(Mandatory)][string]$Content,
        [Parameter(Mandatory)][string]$Pattern,
        [Parameter(Mandatory)][string]$Replacement,
        [Parameter(Mandatory)][string]$FieldName
    )

    $matches = [regex]::Matches($Content, $Pattern)
    if ($matches.Count -ne 1) {
        throw "DeviceConfig.h must define exactly one $FieldName value."
    }
    return [regex]::Replace(
        $Content,
        $Pattern,
        [System.Text.RegularExpressions.MatchEvaluator]{ param($match) $Replacement },
        1
    )
}

function New-DeviceToken {
    $bytes = [byte[]]::new(32)
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $generator.GetBytes($bytes)
    }
    finally {
        $generator.Dispose()
    }
    return ([System.BitConverter]::ToString($bytes)).Replace("-", "").ToLowerInvariant()
}

function ConvertTo-CredentialMap {
    param([AllowNull()][string]$Json)

    $result = [ordered]@{}
    if ([string]::IsNullOrWhiteSpace($Json)) {
        return $result
    }

    try {
        $parsed = $Json | ConvertFrom-Json -AsHashtable
    }
    catch {
        throw "$credentialEnvironmentName contains invalid JSON."
    }
    if ($parsed -isnot [System.Collections.IDictionary]) {
        throw "$credentialEnvironmentName must be a JSON object."
    }

    foreach ($deviceId in $parsed.Keys) {
        $entry = $parsed[$deviceId]
        if (
            $entry -isnot [System.Collections.IDictionary] -or
            -not $entry.Contains("seatId") -or
            -not $entry.Contains("token")
        ) {
            throw "$credentialEnvironmentName entry '$deviceId' is invalid."
        }
        $entrySeatId = 0
        if (-not [int]::TryParse([string]$entry["seatId"], [ref]$entrySeatId)) {
            throw "$credentialEnvironmentName entry '$deviceId' has an invalid seatId."
        }
        $entryToken = [string]$entry["token"]
        if ($entryToken.Length -lt 24) {
            throw "$credentialEnvironmentName entry '$deviceId' has a token shorter than 24 characters."
        }
        $result[[string]$deviceId] = [ordered]@{
            seatId = $entrySeatId
            token = $entryToken
        }
    }
    return $result
}

function Write-AtomicText {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][AllowEmptyString()][string]$Content
    )

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $directory = Split-Path -Parent $fullPath
    if (-not (Test-Path -LiteralPath $directory -PathType Container)) {
        [System.IO.Directory]::CreateDirectory($directory) | Out-Null
    }
    $temporaryPath = Join-Path $directory (
        ".{0}.{1}.tmp" -f [System.IO.Path]::GetFileName($fullPath), [guid]::NewGuid()
    )
    try {
        [System.IO.File]::WriteAllText($temporaryPath, $Content, $utf8NoBom)
        Move-Item -LiteralPath $temporaryPath -Destination $fullPath -Force
    }
    finally {
        Remove-Item -LiteralPath $temporaryPath -Force -ErrorAction SilentlyContinue
    }
}

function Get-CredentialStoreText {
    if (-not [string]::IsNullOrWhiteSpace($CredentialStorePath)) {
        if (Test-Path -LiteralPath $CredentialStorePath -PathType Leaf) {
            return [System.IO.File]::ReadAllText($CredentialStorePath)
        }
        return $null
    }
    return [System.Environment]::GetEnvironmentVariable(
        $credentialEnvironmentName,
        [System.EnvironmentVariableTarget]::User
    )
}

function Set-CredentialStoreText {
    param([AllowNull()][string]$Content)

    if (-not [string]::IsNullOrWhiteSpace($CredentialStorePath)) {
        Write-AtomicText -Path $CredentialStorePath -Content ([string]$Content)
        return
    }
    [System.Environment]::SetEnvironmentVariable(
        $credentialEnvironmentName,
        $Content,
        [System.EnvironmentVariableTarget]::User
    )
    Set-Item -Path "Env:$credentialEnvironmentName" -Value ([string]$Content)
}

function Assert-CommandSucceeded {
    param([Parameter(Mandatory)][string]$Description)

    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE."
    }
}

function Test-ProvisioningPrerequisites {
    if (-not $SkipFlash) {
        if (-not (Test-Path -LiteralPath $pioLauncher -PathType Leaf)) {
            throw "PIO.bat was not found: $pioLauncher"
        }
        & $pioLauncher --version | Out-Null
        Assert-CommandSucceeded -Description "PlatformIO preflight"
    }

    if (-not $SkipRestart) {
        foreach ($path in @(
            $smartDeskStart,
            $smartDeskStop,
            $pythonRuntime,
            $pythonRuntimeCheck
        )) {
            if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
                throw "SmartDesk restart prerequisite was not found: $path"
            }
        }
        & $pythonRuntime $pythonRuntimeCheck | Out-Null
        Assert-CommandSucceeded -Description "SmartDesk Python runtime preflight"
    }
}

function Invoke-FirmwareUpload {
    Write-Host "Building and uploading the shared ESP32 firmware..."
    & $pioLauncher run -d $firmwareRoot --target upload
    Assert-CommandSucceeded -Description "ESP32 firmware upload"
}

function Invoke-SmartDeskRestart {
    Write-Host "Restarting SmartDesk so the backend loads the new device mapping..."
    $previousSkipPause = $env:SKIP_PAUSE
    $previousControlMode = $env:SMARTDESK_CONTROL_MODE
    $previousSkipBrowser = $env:SMARTDESK_SKIP_BROWSER
    try {
        $env:SKIP_PAUSE = "1"
        & $env:ComSpec /d /c "call `"$smartDeskStop`""
        Assert-CommandSucceeded -Description "SmartDesk stop"

        $env:SMARTDESK_CONTROL_MODE = "true"
        $env:SMARTDESK_SKIP_BROWSER = "true"
        & $env:ComSpec /d /c "call `"$smartDeskStart`""
        Assert-CommandSucceeded -Description "SmartDesk start"
    }
    finally {
        $env:SKIP_PAUSE = $previousSkipPause
        $env:SMARTDESK_CONTROL_MODE = $previousControlMode
        $env:SMARTDESK_SKIP_BROWSER = $previousSkipBrowser
    }
}

function Wait-Esp32Online {
    param(
        [Parameter(Mandatory)][string]$ExpectedDeviceId,
        [Parameter(Mandatory)][int]$ExpectedSeatId
    )

    $deadline = [DateTimeOffset]::UtcNow.AddSeconds(90)
    do {
        try {
            $response = Invoke-RestMethod `
                -Uri "http://127.0.0.1:8000/api/hardware/status" `
                -Method Get `
                -TimeoutSec 3
            $seat = @($response.data.seats) | Where-Object {
                [int]$_.seat_id -eq $ExpectedSeatId
            } | Select-Object -First 1
            if (
                $null -ne $seat -and
                $seat.connected -eq $true -and
                [string]$seat.device_id -eq $ExpectedDeviceId
            ) {
                Write-Host "ESP32 Seat $ExpectedSeatId is online and authenticated."
                return
            }
        }
        catch {}
        Start-Sleep -Seconds 2
    } while ([DateTimeOffset]::UtcNow -lt $deadline)

    throw (
        "ESP32 did not become online as $ExpectedDeviceId on Seat " +
        "$ExpectedSeatId within 90 seconds. Check Wi-Fi, SERVER_HOST, and USB upload."
    )
}

if (-not (Test-Path -LiteralPath $DeviceConfigPath -PathType Leaf)) {
    throw "DeviceConfig.h was not found: $DeviceConfigPath"
}

$originalConfig = [System.IO.File]::ReadAllText($DeviceConfigPath)
$seatPattern = 'constexpr\s+uint8_t\s+SEAT_ID\s*=\s*(\d+)\s*;'
$deviceIdPattern = 'constexpr\s+char\s+DEVICE_ID\[\]\s*=\s*"([^"]+)"\s*;'
$deviceTokenPattern = 'constexpr\s+char\s+DEVICE_TOKEN\[\]\s*=\s*"([^"]+)"\s*;'
$oldSeatId = [int](Get-SingleConfigValue `
    -Content $originalConfig `
    -Pattern $seatPattern `
    -FieldName "SEAT_ID")
$oldDeviceId = Get-SingleConfigValue `
    -Content $originalConfig `
    -Pattern $deviceIdPattern `
    -FieldName "DEVICE_ID"
$null = Get-SingleConfigValue `
    -Content $originalConfig `
    -Pattern $deviceTokenPattern `
    -FieldName "DEVICE_TOKEN"

$targetDeviceId = "esp32-seat-{0:D2}" -f $SeatId
$newToken = New-DeviceToken
$originalCredentialText = Get-CredentialStoreText
$credentials = ConvertTo-CredentialMap -Json $originalCredentialText

$seatConflicts = @($credentials.Keys | Where-Object {
    $candidateDeviceId = [string]$_
    $candidateDeviceId -ne $oldDeviceId -and
    $candidateDeviceId -ne $targetDeviceId -and
    [int]$credentials[$candidateDeviceId]["seatId"] -eq $SeatId
})
if ($seatConflicts.Count -gt 0 -and -not $Force) {
    throw (
        "Seat $SeatId is already assigned to $($seatConflicts -join ', '). " +
        "Use -Force only after confirming that device is being replaced."
    )
}

if ($Force) {
    foreach ($conflictingDeviceId in $seatConflicts) {
        $credentials.Remove([string]$conflictingDeviceId)
    }
}
if ($oldDeviceId -ne $targetDeviceId) {
    $credentials.Remove($oldDeviceId)
}
$credentials[$targetDeviceId] = [ordered]@{
    seatId = $SeatId
    token = $newToken
}
$newCredentialText = $credentials | ConvertTo-Json -Depth 4

$newConfig = Set-SingleConfigValue `
    -Content $originalConfig `
    -Pattern $seatPattern `
    -Replacement "constexpr uint8_t SEAT_ID = $SeatId;" `
    -FieldName "SEAT_ID"
$newConfig = Set-SingleConfigValue `
    -Content $newConfig `
    -Pattern $deviceIdPattern `
    -Replacement "constexpr char DEVICE_ID[] = `"$targetDeviceId`";" `
    -FieldName "DEVICE_ID"
$newConfig = Set-SingleConfigValue `
    -Content $newConfig `
    -Pattern $deviceTokenPattern `
    -Replacement "constexpr char DEVICE_TOKEN[] = `"$newToken`";" `
    -FieldName "DEVICE_TOKEN"

Write-Host "Provisioning plan: $oldDeviceId -> $targetDeviceId (Seat $oldSeatId -> Seat $SeatId)"
if (-not $PSCmdlet.ShouldProcess(
    "ESP32 Seat $SeatId",
    "update local firmware credentials, Windows authorization, firmware, and SmartDesk"
)) {
    Write-Host "No configuration was changed."
    exit 0
}

Test-ProvisioningPrerequisites

$configWritten = $false
$credentialsWritten = $false
try {
    Write-AtomicText -Path $DeviceConfigPath -Content $newConfig
    $configWritten = $true
    Set-CredentialStoreText -Content $newCredentialText
    $credentialsWritten = $true
}
catch {
    if ($credentialsWritten) {
        Set-CredentialStoreText -Content $originalCredentialText
    }
    if ($configWritten) {
        Write-AtomicText -Path $DeviceConfigPath -Content $originalConfig
    }
    throw
}

Write-Host "Local configuration and device authorization now target Seat $SeatId."
if (-not $SkipFlash) {
    Invoke-FirmwareUpload
}
if (-not $SkipRestart) {
    Invoke-SmartDeskRestart
}
if (-not $SkipFlash -and -not $SkipRestart) {
    Wait-Esp32Online -ExpectedDeviceId $targetDeviceId -ExpectedSeatId $SeatId
}

Write-Host "ESP32 provisioning completed for Seat $SeatId. Device token was not printed."
