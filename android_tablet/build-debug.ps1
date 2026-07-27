$ErrorActionPreference = "Stop"

$projectRoot = $PSScriptRoot
$androidRoot = Join-Path $projectRoot "android-app"
$diagnosticWebRoot = Join-Path $projectRoot "diagnostic-web"
$workspaceRoot = Split-Path $projectRoot -Parent

if (-not $env:JAVA_HOME) {
    $bundledJdk = "D:\Program Files\Android\Android Studio\jbr"
    if (Test-Path -LiteralPath $bundledJdk) {
        $env:JAVA_HOME = $bundledJdk
    }
    else {
        throw "JAVA_HOME is not set and Android Studio JBR was not found."
    }
}
$env:GRADLE_USER_HOME = Join-Path $workspaceRoot ".gradle-user-home"
$env:ANDROID_USER_HOME = Join-Path $workspaceRoot ".android-user-home"
$env:npm_config_cache = Join-Path $workspaceRoot ".npm-cache"

$modelPath = Join-Path $androidRoot "app\src\main\assets\models\se_mobilefacenet_emb256_fp32.tflite"
if (-not (Test-Path -LiteralPath $modelPath)) {
    throw "Missing local face model: $modelPath. Reproduce it with model-tools\convert_se_mobilefacenet.py before building."
}

Push-Location $diagnosticWebRoot
try {
    npm run build:android
    if ($LASTEXITCODE -ne 0) {
        throw "Diagnostic web build failed with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}

Push-Location $androidRoot
try {
    .\gradlew.bat assembleDebug
    if ($LASTEXITCODE -ne 0) {
        throw "Android build failed with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}

$apk = Join-Path $androidRoot "app\build\outputs\apk\debug\app-debug.apk"
Write-Host "Debug APK: $apk"
