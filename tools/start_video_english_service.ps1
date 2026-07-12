param(
    [int]$Port = 8765,
    [switch]$NoPublicTunnel,
    [switch]$NoAuth
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
if (-not $env:TRANSLATION_PROVIDER) {
    $env:TRANSLATION_PROVIDER = "transformers"
}
if (-not $env:TRANSLATION_MODEL) {
    $env:TRANSLATION_MODEL = "Helsinki-NLP/opus-mt-en-zh"
}

function Repair-LocalProxyEnv {
    $names = @("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")
    foreach ($name in $names) {
        $item = Get-Item "Env:\$name" -ErrorAction SilentlyContinue
        if (-not $item) { continue }
        $value = [string]$item.Value
        if ($value -match "^https://(127\.0\.0\.1|localhost)(:\d+)?(/.*)?$") {
            $fixed = "http://" + $value.Substring("https://".Length)
            Set-Item "Env:\$name" $fixed
            Write-Host "Adjusted $name for local proxy compatibility: $fixed"
        }
    }
}

Repair-LocalProxyEnv

$token = $env:WHISPER_AUTH_TOKEN
if (-not $NoAuth) {
    if (-not $token -or $token -eq "你的token" -or $token -match "[^A-Za-z0-9._~-]") {
        $token = [guid]::NewGuid().ToString("N")
    }
    $env:WHISPER_AUTH_TOKEN = $token
} else {
    $token = ""
    Remove-Item Env:\WHISPER_AUTH_TOKEN -ErrorAction SilentlyContinue
}
$env:WHISPER_PORT = "$Port"

$runtimeConfig = Join-Path $projectRoot "tools\runtime_service_config.json"
$env:WHISPER_RUNTIME_CONFIG = $runtimeConfig

function Get-AdbPath {
    $candidates = @()
    if ($env:ANDROID_HOME) {
        $candidates += Join-Path $env:ANDROID_HOME "platform-tools\adb.exe"
    }
    if ($env:LOCALAPPDATA) {
        $candidates += Join-Path $env:LOCALAPPDATA "Android\Sdk\platform-tools\adb.exe"
    }
    $candidates += "adb"
    foreach ($candidate in $candidates) {
        if ($candidate -eq "adb") {
            $cmd = Get-Command adb -ErrorAction SilentlyContinue
            if ($cmd) { return $cmd.Source }
        } elseif (Test-Path $candidate) {
            return $candidate
        }
    }
    return $null
}

function Get-LanIps {
    ipconfig | Select-String -Pattern "IPv4" | ForEach-Object {
        if ($_.Line -match "(\d{1,3}(?:\.\d{1,3}){3})") { $Matches[1] }
    } | Where-Object {
        $_ -notlike "127.*" -and
        $_ -notlike "169.254.*" -and
        $_ -notlike "192.168.64.*" -and
        $_ -notlike "192.168.153.*"
    } | Select-Object -Unique
}

function New-ServiceUrl([string]$HostPrefix) {
    $url = "$HostPrefix/transcribe"
    if ($token) {
        $encoded = [System.Uri]::EscapeDataString($token)
        $url = "${url}?token=$encoded"
    }
    return $url
}

function Write-RuntimeConfig([string]$PublicBase = "") {
    $lanUrls = @()
    foreach ($ip in Get-LanIps) {
        $lanUrls += New-ServiceUrl "http://${ip}:$Port"
    }
    $urls = @()
    $urls += New-ServiceUrl "http://127.0.0.1:8765"
    $urls += New-ServiceUrl "http://10.0.2.2:$Port"
    $urls += $lanUrls
    if ($PublicBase) {
        $urls += New-ServiceUrl $PublicBase.TrimEnd("/")
    }
    $config = [ordered]@{
        updated_at = (Get-Date).ToString("s")
        port = $Port
        token_required = [bool]$token
        transcribe_urls = @($urls | Where-Object { $_ } | Select-Object -Unique)
        lan_urls = @($lanUrls | Select-Object -Unique)
        public_url = $(if ($PublicBase) { New-ServiceUrl $PublicBase.TrimEnd("/") } else { "" })
    }
    $config | ConvertTo-Json -Depth 5 | Set-Content -Path $runtimeConfig -Encoding UTF8
}

function Test-PortBusy([int]$ListenPort) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $async = $client.BeginConnect("127.0.0.1", $ListenPort, $null, $null)
        return $async.AsyncWaitHandle.WaitOne(500, $false) -and $client.Connected
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

function Get-CloudflaredPath {
    $candidates = @(
        (Join-Path $projectRoot "tools\cloudflared.exe"),
        "$env:ProgramFiles\cloudflared\cloudflared.exe",
        "${env:ProgramFiles(x86)}\cloudflared\cloudflared.exe",
        "$env:LOCALAPPDATA\cloudflared\cloudflared.exe"
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path $candidate)) { return $candidate }
    }
    $cmd = Get-Command cloudflared -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

if (Test-PortBusy $Port) {
    Write-Host "Port $Port is already in use. Close the old service window or run with another port, for example:"
    Write-Host "  powershell -ExecutionPolicy Bypass -File tools/start_video_english_service.ps1 -Port 8767"
    exit 1
}

Write-RuntimeConfig

$adb = Get-AdbPath
$adbJob = $null
if ($adb) {
    $adbJob = Start-Job -ArgumentList $adb, $Port -ScriptBlock {
        param($AdbExe, $ListenPort)
        $configured = @{}
        while ($true) {
            try {
                $devices = & $AdbExe devices | Select-Object -Skip 1 | Where-Object { $_ -match "`tdevice$" }
                foreach ($device in $devices) {
                    $serial = ($device -split "`t")[0]
                    if (-not $configured.ContainsKey($serial)) {
                        & $AdbExe -s $serial reverse tcp:8765 tcp:$ListenPort | Out-Null
                        $configured[$serial] = $true
                        Write-Output "USB ready for ${serial}: phone 8765 -> computer $ListenPort"
                    }
                }
            } catch {
                Write-Output "adb reverse check failed: $($_.Exception.Message)"
            }
            Start-Sleep -Seconds 5
        }
    }
}

$serviceJob = Start-Job -ArgumentList $projectRoot, $Port, $token, $runtimeConfig, $env:TRANSLATION_PROVIDER, $env:TRANSLATION_MODEL, $env:WHISPER_DEVICE, $env:WHISPER_COMPUTE_TYPE -ScriptBlock {
    param($Root, $ListenPort, $AuthToken, $ConfigPath, $TranslationProvider, $TranslationModel, $WhisperDevice, $WhisperComputeType)
    Set-Location $Root
    $env:WHISPER_PORT = "$ListenPort"
    $env:WHISPER_RUNTIME_CONFIG = $ConfigPath
    $env:TRANSLATION_PROVIDER = $TranslationProvider
    $env:TRANSLATION_MODEL = $TranslationModel
    $env:WHISPER_DEVICE = $WhisperDevice
    $env:WHISPER_COMPUTE_TYPE = $WhisperComputeType
    if ($AuthToken) {
        $env:WHISPER_AUTH_TOKEN = $AuthToken
    } else {
        Remove-Item Env:\WHISPER_AUTH_TOKEN -ErrorAction SilentlyContinue
    }
    python tools\local_whisper_service.py
}

$cloudflared = if ($NoPublicTunnel) { $null } else { Get-CloudflaredPath }
$cloudProcess = $null

Write-Host "Video English service is starting from $projectRoot"
Write-Host "Whisper + translation: http://127.0.0.1:$Port"
Write-Host "Translation provider: $env:TRANSLATION_PROVIDER"
Write-Host "Translation model:    $env:TRANSLATION_MODEL"
if ($token) {
    Write-Host "Auth token: $token"
} else {
    Write-Host "Auth token: disabled"
}
Write-Host ""
Write-Host "In the Android app, long-press Generate and use Auto/USB default when the phone is USB-connected:"
Write-Host "  $(New-ServiceUrl "http://127.0.0.1:8765")"
Write-Host "LAN fallback URLs:"
foreach ($ip in Get-LanIps) {
    Write-Host "  $(New-ServiceUrl "http://${ip}:$Port")"
}
Write-Host ""
Write-Host "Keep this PowerShell window open. Press Ctrl+C to stop everything."
Write-Host ""

try {
    Start-Sleep -Seconds 2
    if ($cloudflared) {
        Write-Host "Starting Cloudflare tunnel for data/mobile-network fallback..."
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = $cloudflared
        $psi.Arguments = "tunnel --protocol http2 --url http://127.0.0.1:$Port"
        $psi.UseShellExecute = $false
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        $cloudProcess = New-Object System.Diagnostics.Process
        $cloudProcess.StartInfo = $psi
        [void]$cloudProcess.Start()
        while (-not $cloudProcess.HasExited) {
            $line = $cloudProcess.StandardError.ReadLine()
            if ($null -eq $line) { Start-Sleep -Milliseconds 200; continue }
            Write-Host $line
            if ($line -match "https://[A-Za-z0-9-]+\.trycloudflare\.com") {
                $publicBase = $Matches[0]
                Write-RuntimeConfig $publicBase
                Write-Host ""
                Write-Host "Public/mobile data fallback URL:"
                Write-Host "  $(New-ServiceUrl $publicBase)"
                Write-Host ""
            }
        }
    } else {
        if (-not $NoPublicTunnel) {
            Write-Host "cloudflared was not found, so only USB/LAN are enabled."
            Write-Host "Install it later with: winget install --id Cloudflare.cloudflared"
        }
        while ($true) {
            Write-RuntimeConfig
            Start-Sleep -Seconds 10
        }
    }
} finally {
    if ($cloudProcess -and -not $cloudProcess.HasExited) {
        $cloudProcess.Kill()
    }
    if ($serviceJob) {
        Stop-Job -Job $serviceJob -ErrorAction SilentlyContinue
        Remove-Job -Job $serviceJob -Force -ErrorAction SilentlyContinue
    }
    if ($adbJob) {
        Stop-Job -Job $adbJob -ErrorAction SilentlyContinue
        Remove-Job -Job $adbJob -Force -ErrorAction SilentlyContinue
    }
}
