$ErrorActionPreference = "Continue"

if (-not $env:WHISPER_PORT) {
    $env:WHISPER_PORT = "8765"
}

$listenPort = [int]$env:WHISPER_PORT

$lanIps = ipconfig | Select-String -Pattern "IPv4" | ForEach-Object {
    if ($_.Line -match "(\d{1,3}(?:\.\d{1,3}){3})") { $Matches[1] }
} | Where-Object {
    $_ -notlike "127.*" -and $_ -notlike "169.254.*" -and $_ -notlike "192.168.64.*" -and $_ -notlike "192.168.153.*"
} | Select-Object -Unique

Write-Host "Testing local Whisper service..."
$localPing = "http://127.0.0.1:$listenPort/ping"
try {
    $response = Invoke-WebRequest -UseBasicParsing $localPing -TimeoutSec 5
    Write-Host "  OK: $localPing -> $($response.Content)"
} catch {
    Write-Host "  FAILED: $localPing"
    Write-Host "  Start the service first:"
    Write-Host "    powershell -ExecutionPolicy Bypass -File tools/start_lan_whisper_service.ps1"
    Write-Host "  Error: $($_.Exception.Message)"
}

if (-not $lanIps) {
    Write-Host "No LAN IPv4 address found. Run ipconfig and use the Wi-Fi IPv4 address."
    exit 0
}

Write-Host ""
Write-Host "LAN URLs for the Android app:"
foreach ($ip in $lanIps) {
    $pingUrl = "http://${ip}:$listenPort/ping"
    $appUrl = "http://${ip}:$listenPort/transcribe"
    Write-Host "  App URL: $appUrl"
    try {
        $response = Invoke-WebRequest -UseBasicParsing $pingUrl -TimeoutSec 5
        Write-Host "  PC can reach: $pingUrl -> $($response.Content)"
    } catch {
        Write-Host "  PC cannot reach: $pingUrl"
        Write-Host "  Error: $($_.Exception.Message)"
    }
}

Write-Host ""
Write-Host "If the phone test fails:"
Write-Host "  1. Keep phone and computer on the same Wi-Fi."
Write-Host "  2. Disable guest-network/AP isolation on the router."
Write-Host "  3. Allow Python through Windows Firewall for Private networks."
Write-Host "  4. Use the Wi-Fi IPv4 above, not 127.0.0.1, 10.0.2.2, VMware, or virtual adapter IPs."
