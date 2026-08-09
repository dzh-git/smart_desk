[CmdletBinding()]
param(
    [ValidateSet("Full", "CI")]
    [string]$Profile = "Full",
    [string]$BasePython = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$venvRoot = Join-Path $repoRoot ".venv"
$venvPython = Join-Path $venvRoot "Scripts\python.exe"
$platformioRoot = Join-Path $repoRoot ".tools\platformio-venv"
$platformioPython = Join-Path $platformioRoot "Scripts\python.exe"
$env:PYTHONUTF8 = "1"

function Get-Python311 {
    $candidates = [System.Collections.Generic.List[object]]::new()
    if ($BasePython) {
        $candidates.Add([PSCustomObject]@{
            FilePath = $BasePython
            PrefixArguments = @()
        })
    }
    $condaPython = Join-Path $env:USERPROFILE "miniconda3\python.exe"
    if (Test-Path -LiteralPath $condaPython) {
        $candidates.Add([PSCustomObject]@{
            FilePath = $condaPython
            PrefixArguments = @()
        })
    }
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) {
        $candidates.Add([PSCustomObject]@{
            FilePath = $launcher.Source
            PrefixArguments = @("-3.11")
        })
    }
    $pathPython = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($pathPython) {
        $candidates.Add([PSCustomObject]@{
            FilePath = $pathPython.Source
            PrefixArguments = @()
        })
    }

    foreach ($candidate in $candidates) {
        try {
            $prefixArguments = @($candidate.PrefixArguments)
            $candidatePath = $candidate.FilePath
            $version = & $candidatePath `
                $prefixArguments `
                -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" `
                2>$null
            if ($LASTEXITCODE -eq 0 -and $version.Trim() -eq "3.11") {
                return $candidate
            }
        }
        catch {}
    }
    throw (
        "Python 3.11 was not found. Install Python 3.11 x64 or pass " +
        "-BasePython C:\path\to\python.exe."
    )
}

if (Test-Path -LiteralPath $venvPython) {
    & $venvPython (Join-Path $PSScriptRoot "check_python_runtime.py")
    if ($LASTEXITCODE -ne 0) {
        throw "Existing .venv is not Python 3.11; remove it explicitly and rerun."
    }
}
else {
    $python311 = Get-Python311
    Write-Host "Creating .venv with $($python311.FilePath)"
    $prefixArguments = @($python311.PrefixArguments)
    $baseExecutable = $python311.FilePath
    & $baseExecutable $prefixArguments -m venv $venvRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Python virtual environment creation failed."
    }
}

$backendRequirements = if ($Profile -eq "CI") {
    "new_coding_desk\requirements-ci.txt"
}
else {
    "new_coding_desk\requirements.txt"
}
$requirements = @(
    $backendRequirements,
    "smartdesk_gesture_controller\requirements.txt",
    "esp32_seat_controller\simulator\requirements.txt"
)

& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed." }
foreach ($relativePath in $requirements) {
    & $venvPython -m pip install -r (Join-Path $repoRoot $relativePath)
    if ($LASTEXITCODE -ne 0) {
        throw "Dependency installation failed: $relativePath"
    }
}
& $venvPython -m pip uninstall -y platformio
if ($LASTEXITCODE -ne 0) { throw "Legacy PlatformIO removal failed." }
& $venvPython -m pip check
if ($LASTEXITCODE -ne 0) { throw "Python dependency check failed." }
& $venvPython (Join-Path $PSScriptRoot "check_python_runtime.py")
if ($LASTEXITCODE -ne 0) { throw "Python runtime check failed." }

# PlatformIO 6.x and the current Hugging Face stack require incompatible
# Click versions. Keep the firmware CLI isolated while still using Python 3.11.
if (-not (Test-Path -LiteralPath $platformioPython)) {
    & $venvPython -m venv $platformioRoot
    if ($LASTEXITCODE -ne 0) { throw "PlatformIO environment creation failed." }
}
& $platformioPython (Join-Path $PSScriptRoot "check_python_runtime.py")
if ($LASTEXITCODE -ne 0) { throw "PlatformIO must also use Python 3.11." }
& $platformioPython -m pip install --upgrade pip platformio
if ($LASTEXITCODE -ne 0) { throw "PlatformIO installation failed." }

Write-Host "SmartDesk Python environment is ready: $venvPython"
Write-Host "PlatformIO tool environment is ready: $platformioRoot"
