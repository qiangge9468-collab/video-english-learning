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

Write-Host "Starting Whisper LAN service from $projectRoot"
if ($env:WHISPER_AUTH_TOKEN) {
    Write-Host "Auth token: $env:WHISPER_AUTH_TOKEN"
} else {
    Write-Host "Auth token: disabled. Use this only on a trusted local network."
    Write-Host "To require a token, set WHISPER_AUTH_TOKEN and start with: tools/start_lan_whisper_service.ps1 -UseAuth"
}
Write-Host "Local ping: http://127.0.0.1:$listenPort/ping"

$lanIps = ipconfig | Select-String -Pattern "IPv4" | ForEach-Object {
    if ($_.Line -match "(\d{1,3}(?:\.\d{1,3}){3})") { $Matches[1] }
} | Where-Object {
    $_ -notlike "127.*" -and $_ -notlike "169.254.*" -and $_ -notlike "192.168.64.*" -and $_ -notlike "192.168.153.*"
} | Select-Object -Unique

if ($lanIps) {
    Write-Host "Use one of these URLs in the app after long-pressing Generate:"
    foreach ($ip in $lanIps) {
        $url = "http://${ip}:$listenPort/transcribe"
        if ($env:WHISPER_AUTH_TOKEN) {
            $url = "${url}?token=$env:WHISPER_AUTH_TOKEN"
        }
        Write-Host "  $url"
    }
} else {
    Write-Host "No LAN IPv4 address found. Run ipconfig and use the computer's Wi-Fi IPv4 address."
}
Write-Host "If the app test fails, allow Python through Windows Firewall for private networks."

python tools\local_whisper_service.py
