param(
    [string]$Token = $env:WHISPER_AUTH_TOKEN,
    [int]$Port = 8765
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $projectRoot

if (-not $Token -or $Token -eq "你的token" -or $Token -match "[^A-Za-z0-9._~-]") {
    $Token = [guid]::NewGuid().ToString("N")
}

$env:WHISPER_AUTH_TOKEN = $Token
$env:WHISPER_PORT = "$Port"
$encodedToken = [System.Uri]::EscapeDataString($Token)

$cloudflared = $null
$cloudflaredCandidates = @(
    (Join-Path $projectRoot "tools\cloudflared.exe"),
    "$env:ProgramFiles\cloudflared\cloudflared.exe",
    "${env:ProgramFiles(x86)}\cloudflared\cloudflared.exe",
    "$env:LOCALAPPDATA\cloudflared\cloudflared.exe"
)
$cloudflared = $cloudflaredCandidates |
    Where-Object { $_ -and (Test-Path $_) } |
    Select-Object -First 1

if (-not $cloudflared) {
    $cmd = Get-Command cloudflared -ErrorAction SilentlyContinue
    if ($cmd) {
        $cloudflared = $cmd.Source
    }
}

if (-not $cloudflared) {
    Write-Host "cloudflared.exe was not found."
    Write-Host "Install it with:"
    Write-Host "  winget install --id Cloudflare.cloudflared"
    Write-Host "or download cloudflared-windows-amd64.exe and save it as:"
    Write-Host "  $(Join-Path $projectRoot "tools\cloudflared.exe")"
    exit 1
}

Write-Host "Starting public Whisper service from $projectRoot"
Write-Host "Auth token: $Token"
Write-Host "Local ping: http://127.0.0.1:$Port/ping?token=$encodedToken"
Write-Host ""
Write-Host "After cloudflared prints an https://xxxxx.trycloudflare.com URL, use this in the Android app:"
Write-Host "  https://xxxxx.trycloudflare.com/transcribe?token=$encodedToken"
Write-Host ""
Write-Host "Keep this PowerShell window open. Press Ctrl+C to stop both the tunnel and the Whisper service."
Write-Host ""

$portBusy = $false
$client = New-Object System.Net.Sockets.TcpClient
try {
    $async = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
    $portBusy = $async.AsyncWaitHandle.WaitOne(500, $false) -and $client.Connected
} catch {
    $portBusy = $false
} finally {
    $client.Close()
}
if ($portBusy) {
    Write-Host "Port $Port is already in use."
    Write-Host "Do not expose an old or unauthenticated Whisper service to the public internet."
    Write-Host "Close the existing Whisper service window, or choose another port:"
    Write-Host "  powershell -ExecutionPolicy Bypass -File tools/start_public_whisper_service.ps1 -Port 8766"
    exit 1
}

$service = Start-Job -ArgumentList $projectRoot, $Token, $Port -ScriptBlock {
    param($Root, $AuthToken, $ListenPort)
    $env:WHISPER_AUTH_TOKEN = $AuthToken
    $env:WHISPER_PORT = "$ListenPort"
    Set-Location $Root
    python tools\local_whisper_service.py
}

try {
    Start-Sleep -Seconds 3
    & $cloudflared tunnel --protocol http2 --url "http://127.0.0.1:$Port"
} finally {
    if ($service) {
        Stop-Job -Job $service -ErrorAction SilentlyContinue
        Remove-Job -Job $service -Force -ErrorAction SilentlyContinue
    }
}
