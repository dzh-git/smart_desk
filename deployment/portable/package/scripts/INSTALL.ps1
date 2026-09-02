[CmdletBinding()]
param(
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA "SmartDeskInternalDemo"),
    [string]$DataDir = (Join-Path $env:LOCALAPPDATA "SmartDeskData"),
    [switch]$SkipDependencies,
    [switch]$SkipFirewall,
    [switch]$SkipStartup
)

$ErrorActionPreference = "Stop"
$packageRoot = Split-Path -Parent $PSScriptRoot
$manifest = Get-Content -LiteralPath (
    Join-Path $packageRoot "package-manifest.json"
) -Encoding UTF8 | ConvertFrom-Json
if ($manifest.channel -ne "INTERNAL_DEMO") {
    throw "Only INTERNAL_DEMO packages are accepted."
}
$payload = Join-Path $packageRoot "payload"
if (-not (Test-Path -LiteralPath $payload)) {
    throw "Package payload is missing."
}

$installFull = [IO.Path]::GetFullPath($InstallDir)
$dataFull = [IO.Path]::GetFullPath($DataDir)
if ($installFull.Length -lt 10 -or $dataFull.Length -lt 10) {
    throw "InstallDir/DataDir is unsafe."
}
$versions = Join-Path $installFull "versions"
$target = Join-Path $versions $manifest.version
$currentFile = Join-Path $installFull "current.txt"
$previous = if (Test-Path -LiteralPath $currentFile) {
    Get-Content -LiteralPath $currentFile -Encoding UTF8 -Raw
} else { "" }
$env:PYTHONUTF8 = "1"

function Get-Python311 {
    param([string]$RuntimeGate)
    $candidates = [System.Collections.Generic.List[string]]::new()
    if ($env:SMARTDESK_BASE_PYTHON) {
        $candidates.Add($env:SMARTDESK_BASE_PYTHON)
    }
    $condaPython = Join-Path $env:USERPROFILE "miniconda3\python.exe"
    if (Test-Path -LiteralPath $condaPython) {
        $candidates.Add($condaPython)
    }
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) {
        try {
            $resolved = & $launcher.Source -3.11 -c (
                "import sys; print(sys.executable)"
            ) 2>$null
            if ($LASTEXITCODE -eq 0 -and $resolved) {
                $candidates.Add($resolved.Trim())
            }
        }
        catch {}
    }
    $pathPython = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($pathPython) { $candidates.Add($pathPython.Source) }

    foreach ($candidate in $candidates) {
        try {
            & $candidate $RuntimeGate | Out-Host
            if ($LASTEXITCODE -eq 0) { return $candidate }
        }
        catch {}
    }
    throw "Python 3.11 is required for SmartDesk."
}

try {
    New-Item -ItemType Directory -Force -Path $versions, $dataFull | Out-Null
    if (-not (Test-Path -LiteralPath $target)) {
        New-Item -ItemType Directory -Force -Path $target | Out-Null
        Copy-Item -Path (Join-Path $payload "*") `
            -Destination $target -Recurse -Force
    }
    foreach ($entry in @(
        "INSTALL.bat", "START.bat", "DOCTOR.bat",
        "UNINSTALL.bat", "INTERNAL_DEMO.txt"
    )) {
        Copy-Item -LiteralPath (Join-Path $packageRoot $entry) `
            -Destination (Join-Path $installFull $entry) -Force
    }
    $installedScripts = Join-Path $installFull "scripts"
    New-Item -ItemType Directory -Force -Path $installedScripts | Out-Null
    Copy-Item -Path (Join-Path $packageRoot "scripts\*") `
        -Destination $installedScripts -Recurse -Force

    $runtime = Join-Path $installFull "runtime"
    $venvPython = Join-Path $runtime ".venv\Scripts\python.exe"
    $runtimeGate = Join-Path $target "validation\check_python_runtime.py"
    $basePython = Get-Python311 -RuntimeGate $runtimeGate
    if (-not $SkipDependencies -and -not (Test-Path -LiteralPath $venvPython)) {
        New-Item -ItemType Directory -Force -Path $runtime | Out-Null
        & $basePython -m venv (Join-Path $runtime ".venv")
        if ($LASTEXITCODE -ne 0) { throw "Python virtual environment failed." }
    }
    if (-not $SkipDependencies) {
        $pipArgs = @(
            "-m", "pip", "install", "-r",
            (Join-Path $target "new_coding_desk\requirements.txt"),
            "-r",
            (Join-Path $target "smartdesk_gesture_controller\requirements.txt")
        )
        $wheelhouse = Join-Path $packageRoot "wheelhouse"
        if (Test-Path -LiteralPath $wheelhouse) {
            $pipArgs += @("--no-index", "--find-links", $wheelhouse)
        }
        & $venvPython @pipArgs
        if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }
    }
    elseif (-not (Test-Path -LiteralPath $venvPython)) {
        $venvPython = $basePython
    }
    & $venvPython $runtimeGate
    if ($LASTEXITCODE -ne 0) { throw "Python 3.11 runtime check failed." }

    $configDir = Join-Path $dataFull "config"
    New-Item -ItemType Directory -Force -Path (
        $configDir, (Join-Path $dataFull "logs"), (Join-Path $dataFull "backups")
    ) | Out-Null
    $configPath = Join-Path $configDir "smartdesk.integration.json"
    if (-not (Test-Path -LiteralPath $configPath)) {
        Copy-Item -LiteralPath (
            Join-Path $target "smartdesk.integration.example.json"
        ) -Destination $configPath
    }
    $tokensPath = Join-Path $configDir "esp32-device-tokens.json"
    if (-not (Test-Path -LiteralPath $tokensPath)) {
        $tokens = [ordered]@{}
        1..9 | ForEach-Object {
            $bytes = New-Object byte[] 32
            $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
            try { $rng.GetBytes($bytes) }
            finally { $rng.Dispose() }
            $tokens[("esp32-seat-{0:D2}" -f $_)] = [ordered]@{
                seatId = $_
                token = [Convert]::ToBase64String($bytes)
            }
        }
        $tokens | ConvertTo-Json -Depth 4 | Set-Content `
            -LiteralPath $tokensPath -Encoding UTF8
        & icacls $tokensPath /inheritance:r /grant:r "$env:USERNAME`:(M)" `
            | Out-Null
    }

    [PSCustomObject]@{
        installDir = $installFull
        dataDir = $dataFull
        currentVersionPath = $target
        python = $venvPython
        configPath = $configPath
        tokensPath = $tokensPath
    } | ConvertTo-Json | Set-Content -LiteralPath (
        Join-Path $installFull "install-settings.json"
    ) -Encoding UTF8
    Set-Content -LiteralPath $currentFile -Value $target -Encoding UTF8

    $env:SMARTDESK_CONFIG_PATH = $configPath
    $env:SMARTDESK_DATA_DIR = $dataFull
    $env:SMARTDESK_ESP32_DEVICE_TOKENS_FILE = $tokensPath
    Push-Location (Join-Path $target "new_coding_desk")
    try {
        & $venvPython migrate_database.py
        if ($LASTEXITCODE -ne 0) { throw "Database migration failed." }
    }
    finally { Pop-Location }

    if (-not $SkipStartup) {
        $startup = [Environment]::GetFolderPath("Startup")
        $shell = New-Object -ComObject WScript.Shell
        $shortcut = $shell.CreateShortcut(
            (Join-Path $startup "SmartDesk Internal Demo.lnk")
        )
        $shortcut.TargetPath = Join-Path $installFull "START.bat"
        $shortcut.WorkingDirectory = $installFull
        $shortcut.Save()
    }
    $isAdmin = (
        [Security.Principal.WindowsPrincipal](
            [Security.Principal.WindowsIdentity]::GetCurrent()
        )
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $SkipFirewall -and $isAdmin) {
        & netsh advfirewall firewall delete rule name="SmartDesk Internal Demo" `
            | Out-Null
        & netsh advfirewall firewall add rule name="SmartDesk Internal Demo" `
            dir=in action=allow protocol=TCP localport=5173,8000 | Out-Null
    }
    elseif (-not $SkipFirewall) {
        Write-Warning "Firewall rule skipped: rerun INSTALL.bat as administrator."
    }
    Write-Host "INSTALL PASS: $installFull"
    Write-Host "Database and backups: $dataFull"
}
catch {
    if ($previous) {
        Set-Content -LiteralPath $currentFile -Value $previous -Encoding UTF8
    }
    throw
}
