param(
    [switch]$UseAuth
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $projectRoot

if (-not $env:WHISPER_DEVICE) {
    $env:WHISPER_DEVICE = "cpu"
}
if (-not $env:WHISPER_COMPUTE_TYPE) {
    $env:WHISPER_COMPUTE_TYPE = "int8"
}
if (-not $env:WHISPER_PORT) {
    $env:WHISPER_PORT = "8765"
}
if (-not $UseAuth) {
    Remove-Item Env:\WHISPER_AUTH_TOKEN -ErrorAction SilentlyContinue
}

$listenPort = [int]$env:WHISPER_PORT

Write-Host "Starting Whisper service from $projectRoot"
if ($env:WHISPER_AUTH_TOKEN) {
    Write-Host "Auth token: $env:WHISPER_AUTH_TOKEN"
} else {
    Write-Host "Auth token: disabled for local USB/LAN use."
    Write-Host "To require a token, set WHISPER_AUTH_TOKEN and start with: tools/start_remote_whisper_service.ps1 -UseAuth"
}
Write-Host "Auto model selection:"
Write-Host "  language detection: models\faster-whisper-small, then multilingual medium"
Write-Host "  English captions:   models\faster-whisper-small, then models\faster-whisper-medium"
Write-Host "  Other languages:    models\faster-whisper-medium (Multilingual model)"
Write-Host "Ping: http://127.0.0.1:$listenPort/ping"
Write-Host "LAN phone debug:"
$lanIps = ipconfig | Select-String -Pattern "IPv4" | ForEach-Object {
    if ($_.Line -match "(\d{1,3}(?:\.\d{1,3}){3})") { $Matches[1] }
} | Where-Object {
    $_ -notlike "127.*" -and $_ -notlike "169.254.*" -and $_ -notlike "192.168.64.*" -and $_ -notlike "192.168.153.*"
} | Select-Object -Unique
if ($lanIps) {
    foreach ($ip in $lanIps) {
        $appUrl = "http://${ip}:$listenPort/transcribe"
        $pingUrl = "http://${ip}:$listenPort/ping"
        if ($env:WHISPER_AUTH_TOKEN) {
            $appUrl = "${appUrl}?token=$env:WHISPER_AUTH_TOKEN"
            $pingUrl = "${pingUrl}?token=$env:WHISPER_AUTH_TOKEN"
        }
        Write-Host "  App URL: $appUrl"
        Write-Host "  Ping:    $pingUrl"
    }
    Write-Host "  Keep phone and computer on the same Wi-Fi. Allow Python through Windows Firewall if the phone cannot connect."
} else {
    Write-Host "  No LAN IPv4 address found. Run ipconfig and use the computer's Wi-Fi IPv4 address."
}
Write-Host "USB phone debug:"
Write-Host "  adb reverse --remove tcp:8765"
Write-Host "  adb reverse tcp:8765 tcp:$listenPort"
Write-Host "  then use http://127.0.0.1:8765/transcribe in the app."
Write-Host "Remote use: run tools/start_cloudflare_tunnel.ps1 in another PowerShell window."

$adbCandidates = @()
if ($env:ANDROID_HOME) {
    $adbCandidates += Join-Path $env:ANDROID_HOME "platform-tools\adb.exe"
}
if ($env:LOCALAPPDATA) {
    $adbCandidates += Join-Path $env:LOCALAPPDATA "Android\Sdk\platform-tools\adb.exe"
}
$adbCandidates += "adb"
$adb = $adbCandidates | Where-Object {
    if ($_ -eq "adb") {
        return [bool](Get-Command adb -ErrorAction SilentlyContinue)
    }
    Test-Path $_
} | Select-Object -First 1

if ($adb) {
    $devices = & $adb devices | Select-Object -Skip 1 | Where-Object { $_ -match "`tdevice$" }
    foreach ($device in $devices) {
        $serial = ($device -split "`t")[0]
        Write-Host "Configuring adb reverse for ${serial}: phone 8765 -> computer $listenPort"
        & $adb -s $serial reverse tcp:8765 tcp:$listenPort
    }
    if (-not $devices) {
        Write-Host "No adb device found now. Connect the phone and run: adb reverse tcp:8765 tcp:$listenPort"
    }
} else {
    Write-Host "adb was not found. If using a real phone, run adb reverse tcp:8765 tcp:$listenPort manually."
}

python tools\local_whisper_service.py
