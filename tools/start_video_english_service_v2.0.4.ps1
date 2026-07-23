param(
    [int]$Port = 8766,
    [switch]$NoPublicTunnel,
    [switch]$NoAuth
)

$ErrorActionPreference = "Stop"

function Set-Utf8Console {
    try {
        $utf8NoBom = New-Object System.Text.UTF8Encoding $false
        [Console]::InputEncoding = $utf8NoBom
        [Console]::OutputEncoding = $utf8NoBom
        $OutputEncoding = $utf8NoBom
        & chcp.com 65001 > $null 2>$null
    } catch {
        # Keep running even if the host does not allow changing code page.
    }
}

Set-Utf8Console

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$pythonExe = "D:\Anaconda\python.exe"
if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw "Subtitle Python environment was not found: $pythonExe"
}
Set-Location $projectRoot

function Add-ExistingPathPrefix {
    param([string[]]$Paths)
    $existing = New-Object System.Collections.Generic.List[string]
    foreach ($path in $Paths) {
        if ($path -and (Test-Path $path)) {
            $existing.Add($path)
        }
    }
    if ($existing.Count -gt 0) {
        $env:PATH = (($existing | Select-Object -Unique) -join ";") + ";" + $env:PATH
    }
}

function Add-PythonGpuRuntimePaths {
    $pythonRoot = Split-Path -Parent (Split-Path -Parent $pythonExe)
    $sitePackages = Join-Path $pythonRoot "Lib\site-packages"
    Add-ExistingPathPrefix @(
        (Join-Path $sitePackages "ctranslate2"),
        (Join-Path $sitePackages "nvidia\cuda_runtime\bin"),
        (Join-Path $sitePackages "nvidia\cuda_nvrtc\bin"),
        (Join-Path $sitePackages "nvidia\cublas\bin"),
        (Join-Path $sitePackages "nvidia\cudnn\bin"),
        (Join-Path $sitePackages "torch\lib"),
        (Join-Path $sitePackages "av.libs")
    )
}

Add-PythonGpuRuntimePaths

if (-not $env:WHISPER_DEVICE) {
    $env:WHISPER_DEVICE = "auto"
}
if (-not $env:WHISPER_COMPUTE_TYPE) {
    $env:WHISPER_COMPUTE_TYPE = "auto"
}
if (-not $env:WHISPER_ENGLISH_MODEL) {
    $env:WHISPER_ENGLISH_MODEL = "large-v3"
}
if (-not $env:WHISPER_HOTWORDS) {
    $env:WHISPER_HOTWORDS = "as the crow flies, long way around Africa, coast to coast, Google Maps, serious planning"
}
if (-not $env:WHISPER_INITIAL_PROMPT) {
    $env:WHISPER_INITIAL_PROMPT = "Clear English travel, hiking, backpacking, motorcycle and route-planning captions."
}
if (-not $env:TRANSLATION_PROVIDER) {
    $env:TRANSLATION_PROVIDER = "transformers"
}
if (-not $env:TRANSLATION_MODEL) {
    $localNllbModel = Join-Path $projectRoot "models\nllb-200-distilled-600M"
    $env:TRANSLATION_MODEL = if (Test-Path (Join-Path $localNllbModel "config.json")) {
        $localNllbModel
    } else {
        "facebook/nllb-200-distilled-600M"
    }
}
if (-not $env:TRANSLATION_DEVICE) {
    $env:TRANSLATION_DEVICE = "auto"
}
if (-not $env:TRANSLATION_SOURCE_LANGUAGE) {
    $env:TRANSLATION_SOURCE_LANGUAGE = "eng_Latn"
}
if (-not $env:TRANSLATION_TARGET_LANGUAGE) {
    $env:TRANSLATION_TARGET_LANGUAGE = "zho_Hans"
}
if (-not $env:TRANSLATION_STYLE) {
    $env:TRANSLATION_STYLE = "subtitle"
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

$runtimeConfig = Join-Path $projectRoot "tools\runtime_service_config_v2.0.4.json"
$runtimeStatus = Join-Path $projectRoot "tools\runtime_status_v2.0.4.json"
$latestUrlsFile = Join-Path $projectRoot "tools\latest_service_urls_v2.0.4.txt"
$env:WHISPER_RUNTIME_CONFIG = $runtimeConfig
$env:WHISPER_RUNTIME_STATUS = $runtimeStatus

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

function Write-TextFileAtomic {
    param(
        [string]$Path,
        [string[]]$Lines
    )
    if ([string]::IsNullOrWhiteSpace($Path)) { return }
    $dir = Split-Path -Parent $Path
    if ($dir -and -not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    $tmp = "$Path.tmp.$PID"
    try {
        $Lines | Set-Content -LiteralPath $tmp -Encoding UTF8
        Move-Item -LiteralPath $tmp -Destination $Path -Force
    } catch {
        Remove-Item -LiteralPath $tmp -ErrorAction SilentlyContinue
        Write-Host "Warning: failed to update ${Path}: $($_.Exception.Message)" -ForegroundColor Yellow
    }
}

function Write-RuntimeConfig([string]$PublicBase = "") {
    $lanUrls = @()
    foreach ($ip in Get-LanIps) {
        $lanUrls += New-ServiceUrl "http://${ip}:$Port"
    }
    $urls = @()
    $urls += New-ServiceUrl "http://127.0.0.1:8766"
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
    Write-TextFileAtomic -Path $runtimeConfig -Lines @($config | ConvertTo-Json -Depth 5)
}

function Get-ServiceUrlSummary {
    param([string]$PublicBase = "")
    $lanUrls = @(Get-LanIps | ForEach-Object { New-ServiceUrl "http://${_}:$Port" })
    $usbUrl = New-ServiceUrl "http://127.0.0.1:8766"
    $publicUrl = if ($PublicBase) { New-ServiceUrl $PublicBase.TrimEnd("/") } else { "公网地址生成中，等待 Cloudflare Tunnel..." }
    return [ordered]@{
        usb = $usbUrl
        lan = $lanUrls
        public = $publicUrl
    }
}

function Write-LatestServiceUrls {
    param([string]$PublicBase = "")
    $summary = Get-ServiceUrlSummary $PublicBase
    $lines = New-Object System.Collections.Generic.List[string]
    $lines.Add("看视频学英语 - 最新电脑端服务地址")
    $lines.Add("生成时间: $((Get-Date).ToString('yyyy-MM-dd HH:mm:ss'))")
    $lines.Add("")
    $lines.Add("USB/模拟器:")
    $lines.Add("  $($summary.usb)")
    $lines.Add("")
    $lines.Add("局域网:")
    if ($summary.lan.Count -gt 0) {
        foreach ($url in $summary.lan) { $lines.Add("  $url") }
    } else {
        $lines.Add("  未检测到可用 IPv4")
    }
    $lines.Add("")
    $lines.Add("公网/手机流量:")
    $lines.Add("  $($summary.public)")
    $lines.Add("")
    $lines.Add("手机使用流量时，请复制上面的公网 https://...trycloudflare.com/transcribe?token=... 地址。")
    Write-TextFileAtomic -Path $latestUrlsFile -Lines $lines
}

function Write-PublicUrlReady {
    param([string]$PublicBase)
    if (-not $PublicBase) { return }
    $publicUrl = New-ServiceUrl $PublicBase.TrimEnd("/")
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host "公网地址已就绪，手机用流量时复制这一行：" -ForegroundColor Green
    Write-Host "  $publicUrl" -ForegroundColor Green
    Write-Host "地址也已保存到：$latestUrlsFile" -ForegroundColor Green
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host ""
}

function Add-RecentLog {
    param(
        [System.Collections.Generic.Queue[string]]$Queue,
        [string]$Line
    )
    if ([string]::IsNullOrWhiteSpace($Line)) { return }
    $Queue.Enqueue($Line.Trim())
    while ($Queue.Count -gt 10) { [void]$Queue.Dequeue() }
}

function Read-RuntimeStatus {
    if ([string]::IsNullOrWhiteSpace($runtimeStatus)) { return $null }
    if (-not (Test-Path -LiteralPath $runtimeStatus)) { return $null }
    try {
        return Get-Content -Path $runtimeStatus -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        return $null
    }
}

function Get-GpuStatus {
    $cmd = Get-Command nvidia-smi -ErrorAction SilentlyContinue
    if (-not $cmd) { return "GPU: nvidia-smi not found" }
    try {
        $line = & $cmd.Source --query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu --format=csv,noheader,nounits 2>$null | Select-Object -First 1
        if (-not $line) { return "GPU: no NVIDIA GPU data" }
        $parts = @($line -split "," | ForEach-Object { $_.Trim() })
        if ($parts.Count -lt 4) { return "GPU: $line" }
        return "GPU: $($parts[0])% | VRAM $($parts[1])/$($parts[2]) MB | $($parts[3]) C"
    } catch {
        return "GPU: $($_.Exception.Message)"
    }
}

function Get-DisplayValue {
    param($Value, [string]$Fallback = "-")
    if ($null -eq $Value) { return $Fallback }
    $text = [string]$Value
    if ([string]::IsNullOrWhiteSpace($text)) { return $Fallback }
    return $text
}


$script:dashboardHeaderPrinted = $false
$script:lastDashboardSignature = ""
$script:lastDashboardHeartbeat = [datetime]::MinValue

function Write-ServiceDashboard {
    param(
        $Status,
        [System.Collections.Generic.Queue[string]]$RecentLogs,
        [string]$PublicBase
    )

    $urlSummary = Get-ServiceUrlSummary $PublicBase
    $lanUrls = @($urlSummary.lan)
    $usbUrl = $urlSummary.usb
    $publicUrl = $urlSummary.public

    $jobStatus = if ($Status) { Get-DisplayValue $Status.job_status } else { "starting" }
    $stage = if ($Status) { Get-DisplayValue $Status.stage } else { "starting" }
    $progress = if ($Status -and $null -ne $Status.progress) { [int]$Status.progress } else { 0 }
    $message = if ($Status) { Get-DisplayValue $Status.message } else { "Starting Python service" }
    $detectorModel = if ($Status) { Get-DisplayValue $Status.detector_model "not loaded" } else { "not loaded" }
    $subtitleModel = if ($Status) { Get-DisplayValue $Status.subtitle_model (Get-DisplayValue $Status.configured_english_model "large-v3") } else { $env:WHISPER_ENGLISH_MODEL }
    $whisperDevice = if ($Status) { Get-DisplayValue $Status.whisper_device (Get-DisplayValue $Status.configured_whisper_device "auto") } else { $env:WHISPER_DEVICE }
    $whisperCompute = if ($Status) { Get-DisplayValue $Status.whisper_compute_type (Get-DisplayValue $Status.configured_whisper_compute_type "auto") } else { $env:WHISPER_COMPUTE_TYPE }
    $translationProvider = if ($Status) { Get-DisplayValue $Status.translation_provider $env:TRANSLATION_PROVIDER } else { $env:TRANSLATION_PROVIDER }
    $translationModel = if ($Status) { Get-DisplayValue $Status.translation_model $env:TRANSLATION_MODEL } else { $env:TRANSLATION_MODEL }
    $translationDevice = if ($Status) { Get-DisplayValue $Status.translation_device $env:TRANSLATION_DEVICE } else { $env:TRANSLATION_DEVICE }
    $translationDone = if ($Status -and $null -ne $Status.translation_done) { [int]$Status.translation_done } else { 0 }
    $translationTotal = if ($Status -and $null -ne $Status.translation_total) { [int]$Status.translation_total } else { 0 }
    $translationBatch = if ($Status) { Get-DisplayValue $Status.translation_batch "-" } else { "-" }
    $language = if ($Status) { Get-DisplayValue $Status.detected_language "unknown" } else { "unknown" }
    $subtitleCount = if ($Status -and $null -ne $Status.subtitle_count) { [int]$Status.subtitle_count } else { 0 }

    if (-not $script:dashboardHeaderPrinted) {
        Write-Host ""
        Write-Host "看视频学英语 v2.0.4 - 电脑端服务已启动" -ForegroundColor Cyan
        Write-Host "============================================================"
        Write-Host "连接地址"
        Write-Host "  USB/模拟器: $usbUrl"
        if ($lanUrls.Count -gt 0) {
            foreach ($url in $lanUrls) { Write-Host "  局域网:     $url" }
        } else {
            Write-Host "  局域网:     未检测到可用 IPv4"
        }
        Write-Host "  公网备用:   $publicUrl"
        Write-Host ""
        Write-Host "模型配置"
        Write-Host "  语言检测:   $detectorModel"
        Write-Host "  字幕识别:   $subtitleModel on $whisperDevice/$whisperCompute"
        Write-Host "  中文翻译:   $translationProvider / $translationModel on $translationDevice"
        Write-Host ""
        Write-Host "后续只在状态变化时追加一行日志，不会清屏闪烁；按 Ctrl+C 停止服务。" -ForegroundColor Yellow
        Write-Host ""
        $script:dashboardHeaderPrinted = $true
    }

    $gpuStatus = Get-GpuStatus
    $signature = "$jobStatus|$stage|$progress|$message|$subtitleCount|$translationDone|$translationTotal|$translationBatch|$language|$publicUrl"
    $now = Get-Date
    $heartbeatDue = (($now - $script:lastDashboardHeartbeat).TotalSeconds -ge 60)
    $shouldPrint = ($signature -ne $script:lastDashboardSignature) -or $heartbeatDue
    if ($jobStatus -eq "idle" -and $stage -eq "idle" -and $signature -eq $script:lastDashboardSignature -and -not $heartbeatDue) {
        $shouldPrint = $false
    }
    if ($shouldPrint) {
        $line = "[{0}] 状态={1} 阶段={2} 进度={3}% 信息={4} 字幕={5} 翻译={6}/{7} 批次={8} 语言={9} | {10}" -f `
            $now.ToString("HH:mm:ss"), $jobStatus, $stage, $progress, $message, $subtitleCount, $translationDone, $translationTotal, $translationBatch, $language, $gpuStatus
        Write-Host $line
        $script:lastDashboardSignature = $signature
        $script:lastDashboardHeartbeat = $now
    }

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
    Write-Host "  powershell -ExecutionPolicy Bypass -File tools/start_video_english_service_v2.0.4.ps1 -Port 8767"
    exit 1
}

Write-RuntimeConfig
Write-LatestServiceUrls

$adb = Get-AdbPath
$adbJob = $null
if ($adb) {
    $adbJob = Start-Job -ArgumentList $adb, $Port -ScriptBlock {
        param($AdbExe, $ListenPort)
        while ($true) {
            try {
                $devices = & $AdbExe devices | Select-Object -Skip 1 | Where-Object { $_ -match "`tdevice$" }
                foreach ($device in $devices) {
                    $serial = ($device -split "`t")[0]
                    $reverseList = (& $AdbExe -s $serial reverse --list 2>$null) -join "`n"
                    $mappingPattern = "tcp:8766\s+tcp:$ListenPort"
                    if ($reverseList -notmatch $mappingPattern) {
                        & $AdbExe -s $serial reverse tcp:8766 tcp:$ListenPort | Out-Null
                        if ($LASTEXITCODE -eq 0) {
                            Write-Output "USB ready for ${serial}: phone 8766 -> computer $ListenPort"
                        } else {
                            Write-Output "USB reverse failed for ${serial}; will retry in 5 seconds"
                        }
                    }
                }
            } catch {
                Write-Output "adb reverse check failed: $($_.Exception.Message)"
            }
            Start-Sleep -Seconds 5
        }
    }
}

$serviceJob = Start-Job -ArgumentList $projectRoot, $Port, $token, $runtimeConfig, $runtimeStatus, $env:PATH, $env:TRANSLATION_PROVIDER, $env:TRANSLATION_MODEL, $env:TRANSLATION_DEVICE, $env:TRANSLATION_SOURCE_LANGUAGE, $env:TRANSLATION_TARGET_LANGUAGE, $env:TRANSLATION_STYLE, $env:WHISPER_DEVICE, $env:WHISPER_COMPUTE_TYPE, $env:WHISPER_ENGLISH_MODEL, $env:WHISPER_HOTWORDS, $env:WHISPER_INITIAL_PROMPT -ScriptBlock {
    param($Root, $ListenPort, $AuthToken, $ConfigPath, $StatusPath, $RuntimePath, $TranslationProvider, $TranslationModel, $TranslationDevice, $TranslationSourceLanguage, $TranslationTargetLanguage, $TranslationStyle, $WhisperDevice, $WhisperComputeType, $WhisperEnglishModel, $WhisperHotwords, $WhisperInitialPrompt)
    Set-Location $Root
    $env:PATH = $RuntimePath
    $env:WHISPER_PORT = "$ListenPort"
    $env:VIDEO_ENGLISH_DATA_DIR = Join-Path $Root "service_data_v2.0.4"
    $env:SAT_MODEL_DIR = Join-Path $Root "models\sat-12l-sm"
    $env:SAT_TOKENIZER_DIR = Join-Path $Root "models\xlm-roberta-base"
    $env:SPACY_MODEL = "en_core_web_trf"
    $env:SEMANTIC_PYTHON = "D:\anaconda\envs\subtitle\python.exe"
    $env:SUBTITLE_SEMANTIC_ENABLED = "1"
    $env:SUBTITLE_SEMANTIC_FALLBACK = "1"
    $env:HF_HUB_OFFLINE = "1"
    $env:TRANSFORMERS_OFFLINE = "1"
    $env:WHISPER_RUNTIME_CONFIG = $ConfigPath
    $env:WHISPER_RUNTIME_STATUS = $StatusPath
    $env:TRANSLATION_PROVIDER = $TranslationProvider
    $env:TRANSLATION_MODEL = $TranslationModel
    $env:TRANSLATION_DEVICE = $TranslationDevice
    $env:TRANSLATION_SOURCE_LANGUAGE = $TranslationSourceLanguage
    $env:TRANSLATION_TARGET_LANGUAGE = $TranslationTargetLanguage
    $env:TRANSLATION_STYLE = $TranslationStyle
    $env:WHISPER_DEVICE = $WhisperDevice
    $env:WHISPER_COMPUTE_TYPE = $WhisperComputeType
    $env:WHISPER_ENGLISH_MODEL = $WhisperEnglishModel
    $env:WHISPER_HOTWORDS = $WhisperHotwords
    $env:WHISPER_INITIAL_PROMPT = $WhisperInitialPrompt
    if ($AuthToken) {
        $env:WHISPER_AUTH_TOKEN = $AuthToken
    } else {
        Remove-Item Env:\WHISPER_AUTH_TOKEN -ErrorAction SilentlyContinue
    }
    $servicePythonExe = "D:\Anaconda\python.exe"
    if (-not (Test-Path -LiteralPath $servicePythonExe)) {
        throw "Subtitle Python environment was not found: $servicePythonExe"
    }
    & $servicePythonExe tools\local_whisper_service_v2.0.4.py
}

$cloudflared = if ($NoPublicTunnel) { $null } else { Get-CloudflaredPath }
$cloudJob = $null
$recentLogs = New-Object 'System.Collections.Generic.Queue[string]'
$publicBase = ""
$printedPublicBase = ""

try {
    Start-Sleep -Seconds 2
    if ($cloudflared) {
        Add-RecentLog $recentLogs "Starting Cloudflare tunnel for data/mobile-network fallback..."
        $cloudJob = Start-Job -ArgumentList $cloudflared, $Port -ScriptBlock {
            param($CloudflaredExe, $ListenPort)
            & $CloudflaredExe tunnel --protocol http2 --url "http://127.0.0.1:$ListenPort" 2>&1 | ForEach-Object { [string]$_ }
        }
    } elseif (-not $NoPublicTunnel) {
        Add-RecentLog $recentLogs "cloudflared was not found; USB/LAN only. Install with: winget install --id Cloudflare.cloudflared"
    }

    while ($true) {
        foreach ($line in Receive-Job -Job $serviceJob -ErrorAction SilentlyContinue) {
            Add-RecentLog $recentLogs ([string]$line)
        }
        if ($adbJob) {
            foreach ($line in Receive-Job -Job $adbJob -ErrorAction SilentlyContinue) {
                Add-RecentLog $recentLogs ([string]$line)
            }
        }
        if ($cloudJob) {
            foreach ($line in Receive-Job -Job $cloudJob -ErrorAction SilentlyContinue) {
                $textLine = [string]$line
                Add-RecentLog $recentLogs $textLine
                if ($textLine -match "https://[A-Za-z0-9-]+\.trycloudflare\.com") {
                    $newPublicBase = $Matches[0]
                    if ($newPublicBase -ne $publicBase) {
                        $publicBase = $newPublicBase
                        Write-LatestServiceUrls $publicBase
                        if ($publicBase -ne $printedPublicBase) {
                            Write-PublicUrlReady $publicBase
                            $printedPublicBase = $publicBase
                        }
                    }
                }
            }
            if ($cloudJob.State -in @("Failed", "Stopped", "Completed")) {
                Add-RecentLog $recentLogs "cloudflared stopped: $($cloudJob.State)"
            }
        }

        Write-RuntimeConfig $publicBase
        Write-LatestServiceUrls $publicBase
        $status = Read-RuntimeStatus
        Write-ServiceDashboard -Status $status -RecentLogs $recentLogs -PublicBase $publicBase
        Start-Sleep -Seconds 2
    }
} finally {
    if ($cloudJob) {
        Stop-Job -Job $cloudJob -ErrorAction SilentlyContinue
        Remove-Job -Job $cloudJob -Force -ErrorAction SilentlyContinue
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
