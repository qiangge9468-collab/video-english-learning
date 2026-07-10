$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $projectRoot

if (-not $env:WHISPER_AUTH_TOKEN) {
    Write-Host "WHISPER_AUTH_TOKEN is not set in this PowerShell window."
    Write-Host "Start tools/start_remote_whisper_service.ps1 first, copy its Auth token, then run:"
    Write-Host '  $env:WHISPER_AUTH_TOKEN="PASTE_TOKEN_HERE"'
    exit 1
}
if (-not $env:WHISPER_PORT) {
    $env:WHISPER_PORT = "8765"
}

$listenPort = [int]$env:WHISPER_PORT

$cloudflared = $null
$localCloudflared = Join-Path $projectRoot "tools\cloudflared.exe"
if (Test-Path $localCloudflared) {
    $cloudflared = $localCloudflared
} else {
    $cmd = Get-Command cloudflared -ErrorAction SilentlyContinue
    if ($cmd) {
        $cloudflared = $cmd.Source
    }
}

if (-not $cloudflared) {
    Write-Host "cloudflared.exe was not found."
    Write-Host "Install one of these ways, then run this script again:"
    Write-Host "  winget install --id Cloudflare.cloudflared"
    Write-Host "or download cloudflared-windows-amd64.exe and save it as:"
    Write-Host "  $localCloudflared"
    exit 1
}

Write-Host "Starting Cloudflare Tunnel for http://127.0.0.1:$listenPort"
Write-Host "When a trycloudflare.com URL appears, set the app service URL to:"
Write-Host "  https://xxxxx.trycloudflare.com/transcribe?token=$env:WHISPER_AUTH_TOKEN"
Write-Host ""
Write-Host "Keep this PowerShell window open while testing from 5G or another network."
& $cloudflared tunnel --protocol http2 --url http://127.0.0.1:$listenPort
