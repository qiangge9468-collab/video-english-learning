param(
    [Parameter(Mandatory = $true)][string]$VideoPath,
    [Parameter(Mandatory = $true)][string]$PortraitVideoPath,
    [string]$Serial = "emulator-5554",
    [string]$Adb = "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe",
    [switch]$SkipBuild
)
$ErrorActionPreference = "Stop"
if ($Serial -notmatch '^emulator-\d+$') { throw "Use a dedicated emulator: this suite changes test-app settings and wordbook entries." }
foreach ($path in @($VideoPath, $PortraitVideoPath, $Adb)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing file: $path" }
}
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "../../..")).Path
function Invoke-TestAdb {
    param([string[]]$Arguments)
    & $Adb -s $Serial @Arguments
    if ($LASTEXITCODE -ne 0) { throw "adb failed: $($Arguments -join ' ')" }
}
Push-Location $projectRoot
try {
    if (-not $SkipBuild) {
        & .\gradlew.bat :app:assembleDebug :app:assembleDebugAndroidTest :app:testDebugUnitTest --console=plain
        if ($LASTEXITCODE -ne 0) { throw "Gradle failed" }
    }
    Invoke-TestAdb -Arguments @("install", "-r", "app/build/outputs/apk/debug/app-debug.apk")
    Invoke-TestAdb -Arguments @("install", "-r", "app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk")
    # These are fixed fixture names on the dedicated test emulator, not production video paths.
    Invoke-TestAdb -Arguments @("push", $VideoPath, "/sdcard/Download/Full Gear List for Solo Backpacking.mp4")
    Invoke-TestAdb -Arguments @("push", $PortraitVideoPath, "/sdcard/Download/fullscreen-portrait-fixture.mp4")
    Invoke-TestAdb -Arguments @("shell", "pm", "grant", "com.codex.videolearnenglish.remote", "android.permission.READ_MEDIA_VIDEO")
    $result = Invoke-TestAdb -Arguments @("shell", "am", "instrument", "-w", "com.codex.videolearnenglish.remote.test/com.codex.videolearnenglish.FullscreenInstrumentation")
    $result
    if (($result -join "`n") -notmatch 'Tests: \d+, failures: 0' -or ($result -join "`n") -match 'Process crashed|SETUP FAILED') {
        throw "Fullscreen emulator regression failed; see instrumentation output above."
    }
    $evidence = Join-Path $projectRoot "tools/runtime/v2.2.0/fullscreen-validation"
    New-Item -ItemType Directory -Path $evidence -Force | Out-Null
    Invoke-TestAdb -Arguments @("pull", "/sdcard/Android/data/com.codex.videolearnenglish.remote/files/fullscreen-validation/.", $evidence)
    Write-Host "PASS. Inspect screenshots in $evidence. This is UI/player validation, not an ASR accuracy test."
} finally {
    Pop-Location
}
