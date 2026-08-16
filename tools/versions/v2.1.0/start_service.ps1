param(
    [int]$Port = 8766,
    [switch]$EnablePublicTunnel,
    [switch]$NoPublicTunnel,
    [switch]$NoAuth,
    [switch]$NoDashboard,
    [switch]$NoTailscale
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

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $scriptDir "..\..\.."))
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
    $env:WHISPER_INITIAL_PROMPT = "Clear English captions."
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

$whisperXPython = if ($env:WHISPERX_PYTHON) {
    $env:WHISPERX_PYTHON
} else {
    "D:\Anaconda\envs\video-english-whisperx\python.exe"
}
$whisperXModelDir = if ($env:WHISPERX_MODEL_DIR) {
    $env:WHISPERX_MODEL_DIR
} else {
    Join-Path $projectRoot "models\whisperx"
}
if (-not (Test-Path -LiteralPath $whisperXPython)) {
    throw "Required WhisperX environment was not found: $whisperXPython"
}
$whisperXCudaCheck = & $whisperXPython -c "import importlib.metadata as m, torch; assert m.version('whisperx') == '3.8.6'; assert torch.cuda.is_available(); print(torch.cuda.get_device_name(0))"
if ($LASTEXITCODE -ne 0) {
    throw "WhisperX 3.8.6 CUDA preflight failed. v2.1.0 requires GPU alignment."
}
Write-Host "WhisperX CUDA ready: $whisperXCudaCheck" -ForegroundColor Green

$dataDir = Join-Path $projectRoot "service_data_v2.1.0"
$tokenFile = Join-Path $dataDir "service_auth_token.txt"
$token = [string]$env:WHISPER_AUTH_TOKEN
if (-not $NoAuth) {
    $validToken = $token -and $token -ne "你的token" -and $token -notmatch "[^A-Za-z0-9._~-]"
    if (-not $validToken -and (Test-Path -LiteralPath $tokenFile)) {
        $token = (Get-Content -LiteralPath $tokenFile -Raw -Encoding utf8).Trim()
        $validToken = $token -and $token -notmatch "[^A-Za-z0-9._~-]"
    }
    if (-not $validToken) {
        $token = ([guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N"))
    }
    if (-not (Test-Path -LiteralPath $dataDir)) { New-Item -ItemType Directory -Path $dataDir -Force | Out-Null }
    [System.IO.File]::WriteAllText($tokenFile, $token, (New-Object System.Text.UTF8Encoding($false)))
    $env:WHISPER_AUTH_TOKEN = $token
} else {
    $token = ""
    Remove-Item Env:\WHISPER_AUTH_TOKEN -ErrorAction SilentlyContinue
    Write-Host "WARNING: authentication is disabled; use only for isolated diagnostics." -ForegroundColor Red
}
$env:WHISPER_PORT = "$Port"

$runtimeConfig = Join-Path $projectRoot "tools\runtime\v2.1.0\config.json"
$runtimeStatus = Join-Path $projectRoot "tools\runtime\v2.1.0\status.json"
$latestUrlsFile = Join-Path $projectRoot "tools\runtime\v2.1.0\latest_service_urls.txt"
$githubConfigStateFile = Join-Path $dataDir "github_service_config_state.json"
$githubConfigPayloadFile = Join-Path $dataDir "service-config.json"
$githubApiRequestFile = Join-Path $dataDir "github_service_config_request.json"
$githubApiErrorFile = Join-Path $dataDir "github_service_config_error.log"
$officialDiscoveryLogin = "qiangge9468-collab"
$officialDiscoveryGistId = "b3f5221fbc3e95270951695b92aaa84c"
$runtimeDir = Split-Path -Parent $runtimeConfig
$serviceLogFile = Join-Path $runtimeDir "service.log"
if (-not (Test-Path -LiteralPath $runtimeDir)) { New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null }
$env:WHISPER_RUNTIME_CONFIG = $runtimeConfig
$env:WHISPER_RUNTIME_STATUS = $runtimeStatus

function New-DashboardUrl {
    $url = "http://127.0.0.1:$Port/dashboard"
    if ($token) {
        $encoded = [System.Uri]::EscapeDataString($token)
        $url = "${url}?token=$encoded"
    }
    return $url
}

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

function Get-GhPath {
    $cmd = Get-Command gh -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

function Read-GitHubConfigState {
    if (-not (Test-Path -LiteralPath $githubConfigStateFile)) { return $null }
    try { return Get-Content -LiteralPath $githubConfigStateFile -Raw -Encoding utf8 | ConvertFrom-Json } catch { return $null }
}

function Get-GitHubConfigUrl {
    $state = Read-GitHubConfigState
    if ($state -and $state.discovery_url) { return [string]$state.discovery_url }
    return ""
}

function Invoke-GhApiJson {
    param(
        [string]$Gh,
        [string]$Method,
        [string]$Endpoint,
        [string]$BodyFile = ""
    )
    Remove-Item -LiteralPath $githubApiErrorFile -ErrorAction SilentlyContinue
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        if ($BodyFile) {
            $output = & $Gh api --method $Method $Endpoint --input $BodyFile 2>$githubApiErrorFile
        } else {
            $output = & $Gh api --method $Method $Endpoint 2>$githubApiErrorFile
        }
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($exitCode -ne 0) {
        $details = if (Test-Path -LiteralPath $githubApiErrorFile) {
            (Get-Content -LiteralPath $githubApiErrorFile -Raw -ErrorAction SilentlyContinue).Trim()
        } else { "" }
        if (-not $details) { $details = "gh api exited with code $exitCode" }
        throw $details
    }
    $jsonText = (@($output) -join "`n").Trim()
    if (-not $jsonText) { throw "GitHub API returned an empty response" }
    try {
        return $jsonText | ConvertFrom-Json
    } catch {
        throw "GitHub API returned invalid JSON: $($_.Exception.Message)"
    }
}

function Publish-GitHubServiceConfig {
    param([string]$PublicBase)
    if (-not $PublicBase) { return Get-GitHubConfigUrl }
    $gh = Get-GhPath
    if (-not $gh) {
        Write-Host "GitHub CLI was not found; public URL cannot be auto-published. Install gh or enter the URL manually." -ForegroundColor Yellow
        return Get-GitHubConfigUrl
    }
    try {
        $user = Invoke-GhApiJson -Gh $gh -Method "GET" -Endpoint "user"
        $login = [string]$user.login
        if (-not $login) { throw "GitHub login could not be resolved" }

        $payload = [ordered]@{
            schema_version = 1
            service_version = "2.1.0"
            updated_at = (Get-Date).ToUniversalTime().ToString("o")
            expires_at = (Get-Date).ToUniversalTime().AddHours(24).ToString("o")
            public_base_url = $PublicBase.TrimEnd([char]47)
        }
        [string]$payloadJson = $payload | ConvertTo-Json -Depth 4
        [System.IO.File]::WriteAllText(
            $githubConfigPayloadFile,
            $payloadJson,
            (New-Object System.Text.UTF8Encoding($false))
        )

        $state = Read-GitHubConfigState
        $gistId = if ($state -and $state.gist_id) { [string]$state.gist_id } else { "" }
        if (-not $gistId -and $login -ieq $officialDiscoveryLogin) {
            $gistId = $officialDiscoveryGistId
        }

        $request = [ordered]@{
            files = [ordered]@{
                "service-config.json" = [ordered]@{ content = $payloadJson }
            }
        }
        if (-not $gistId) {
            $request["description"] = "Video English Learning v2.1.0 service discovery (base URL only; no token)"
            $request["public"] = $false
        }
        [string]$requestJson = $request | ConvertTo-Json -Depth 8
        [System.IO.File]::WriteAllText(
            $githubApiRequestFile,
            $requestJson,
            (New-Object System.Text.UTF8Encoding($false))
        )

        if ($gistId) {
            $response = Invoke-GhApiJson -Gh $gh -Method "PATCH" -Endpoint "gists/$gistId" -BodyFile $githubApiRequestFile
        } else {
            $response = Invoke-GhApiJson -Gh $gh -Method "POST" -Endpoint "gists" -BodyFile $githubApiRequestFile
            $gistId = [string]$response.id
        }
        if (-not $gistId) { throw "GitHub API returned no gist id" }

        $discoveryUrl = "https://gist.githubusercontent.com/$login/$gistId/raw/service-config.json"
        $newState = [ordered]@{
            gist_id = $gistId
            discovery_url = $discoveryUrl
            updated_at = (Get-Date).ToString("s")
        }
        Write-TextFileAtomic -Path $githubConfigStateFile -Lines @($newState | ConvertTo-Json -Depth 3)
        Write-Host "GitHub no-USB discovery updated: $discoveryUrl" -ForegroundColor Green
        return $discoveryUrl
    } catch {
        Write-Host "GitHub discovery update failed: $($_.Exception.Message). Public URL is still available for manual entry." -ForegroundColor Yellow
        return Get-GitHubConfigUrl
    } finally {
        Remove-Item -LiteralPath $githubApiErrorFile -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $githubApiRequestFile -ErrorAction SilentlyContinue
    }
}

function Get-TailscalePath {
    $candidates = @(
        "$env:ProgramFiles\Tailscale\tailscale.exe",
        "$env:LOCALAPPDATA\Tailscale\tailscale.exe"
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) { return $candidate }
    }
    $cmd = Get-Command tailscale -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

function Enable-TailscalePrivateServe {
    param([string]$TailscaleExe)
    if (-not $TailscaleExe) { return "" }
    try {
        $statusText = (& $TailscaleExe status --json 2>$null) -join "`n"
        if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($statusText)) { return "" }
        $status = $statusText | ConvertFrom-Json
        if ([string]$status.BackendState -ne "Running") { return "" }
        $dnsName = ([string]$status.Self.DNSName).Trim().TrimEnd(".")
        if (-not $dnsName) { return "" }
        $serveOutput = (& $TailscaleExe serve --bg $Port 2>&1) -join "`n"
        if ($LASTEXITCODE -ne 0) {
            Write-Host "Tailscale Serve configuration failed: $serveOutput" -ForegroundColor Yellow
            return ""
        }
        return "https://$dnsName"
    } catch {
        Write-Host "Tailscale is unavailable: $($_.Exception.Message)" -ForegroundColor Yellow
        return ""
    }
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

function Write-RuntimeConfig([string]$PublicBase = "", [string]$TailscaleBase = "", [string]$GitHubConfigUrl = "") {
    $lanUrls = @()
    foreach ($ip in Get-LanIps) {
        $lanUrls += New-ServiceUrl "http://${ip}:$Port"
    }
    $urls = @()
    $urls += New-ServiceUrl "http://127.0.0.1:8766"
    $urls += New-ServiceUrl "http://10.0.2.2:$Port"
    $urls += $lanUrls
    if ($TailscaleBase) {
        $urls += New-ServiceUrl ($TailscaleBase.TrimEnd([char]47))
    }
    if ($PublicBase) {
        $urls += New-ServiceUrl ($PublicBase.TrimEnd([char]47))
    }
    $config = [ordered]@{
        schema_version = 1
        service_version = "2.1.0"
        updated_at = (Get-Date).ToString("s")
        port = $Port
        token_required = [bool]$token
        privacy_mode = $(if ($PublicBase) { "public_auto_token_protected" } else { "private" })
        dashboard_url = New-DashboardUrl
        transcribe_urls = @($urls | Where-Object { $_ } | Select-Object -Unique)
        lan_urls = @($lanUrls | Select-Object -Unique)
        tailscale_url = $(if ($TailscaleBase) { New-ServiceUrl ($TailscaleBase.TrimEnd([char]47)) } else { "" })
        public_url = $(if ($PublicBase) { New-ServiceUrl ($PublicBase.TrimEnd([char]47)) } else { "" })
        github_config_url = $GitHubConfigUrl
    }
    Write-TextFileAtomic -Path $runtimeConfig -Lines @($config | ConvertTo-Json -Depth 5)
}

function Get-ServiceUrlSummary {
    param([string]$PublicBase = "", [string]$TailscaleBase = "")
    $lanUrls = @(Get-LanIps | ForEach-Object { New-ServiceUrl "http://${_}:$Port" })
    $usbUrl = New-ServiceUrl "http://127.0.0.1:8766"
    $tailscaleUrl = if ($TailscaleBase) { New-ServiceUrl ($TailscaleBase.TrimEnd([char]47)) } else { "未启用（USB/局域网仍可用）" }
    $publicUrl = if ($PublicBase) { New-ServiceUrl ($PublicBase.TrimEnd([char]47)) } else { "等待 Cloudflare 临时地址" }
    return [ordered]@{
        usb = $usbUrl
        lan = $lanUrls
        tailscale = $tailscaleUrl
        public = $publicUrl
    }
}

function Write-LatestServiceUrls {
    param([string]$PublicBase = "", [string]$TailscaleBase = "", [string]$GitHubConfigUrl = "")
    $summary = Get-ServiceUrlSummary $PublicBase $TailscaleBase
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
    $lines.Add("Tailscale 私有固定地址:")
    $lines.Add("  $($summary.tailscale)")
    $lines.Add("")
    $lines.Add("公网/手机流量:")
    $lines.Add("  $($summary.public)")
    $lines.Add("")
    $lines.Add("GitHub 无 USB 地址发现:")
    $lines.Add("  $(if ($GitHubConfigUrl) { $GitHubConfigUrl } else { '等待公网地址或 GitHub 登录' })")
    $lines.Add("")
    $lines.Add("公网地址默认生成并发布到个人 secret Gist；配置只含基础地址，不含 token。使用 -NoPublicTunnel 可关闭。")
    Write-TextFileAtomic -Path $latestUrlsFile -Lines $lines
}

function Write-PublicUrlReady {
    param([string]$PublicBase)
    if (-not $PublicBase) { return }
    $publicUrl = New-ServiceUrl ($PublicBase.TrimEnd([char]47))
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host "公网地址已就绪；GitHub 登录可让已配对手机在无 USB 时自动发现：" -ForegroundColor Green
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

function Add-ServiceRuntimeLog {
    param(
        [System.Collections.Generic.Queue[string]]$Queue,
        [string]$Line
    )
    if ([string]::IsNullOrWhiteSpace($Line)) { return }
    Add-RecentLog $Queue $Line
    try {
        $timestamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
        Add-Content -LiteralPath $serviceLogFile -Value "[$timestamp] $($Line.Trim())" -Encoding UTF8
    } catch {
    }
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
        [string]$PublicBase,
        [string]$TailscaleBase
    )

    $urlSummary = Get-ServiceUrlSummary $PublicBase $TailscaleBase
    $lanUrls = @($urlSummary.lan)
    $usbUrl = $urlSummary.usb
    $tailscaleUrl = $urlSummary.tailscale
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
        Write-Host "看视频学英语 v2.1.0 - 电脑端服务已启动" -ForegroundColor Cyan
        Write-Host "============================================================"
        Write-Host "连接地址"
        Write-Host "  USB/模拟器: $usbUrl"
        if ($lanUrls.Count -gt 0) {
            foreach ($url in $lanUrls) { Write-Host "  局域网:     $url" }
        } else {
            Write-Host "  局域网:     未检测到可用 IPv4"
        }
        Write-Host "  Tailscale:  $tailscaleUrl"
        Write-Host "  公网备用:   $publicUrl"
        Write-Host ""
        Write-Host "模型配置"
        Write-Host "  语言检测:   $detectorModel"
        Write-Host "  字幕识别:   $subtitleModel on $whisperDevice/$whisperCompute"
        Write-Host "  中文翻译:   $translationProvider / $translationModel on $translationDevice"
        Write-Host ""
        Write-Host "本地网页仪表盘: $(New-DashboardUrl)" -ForegroundColor Green
        Write-Host "网页每 2 秒自动刷新；关闭网页不会停止任务。按 Ctrl+C 停止服务。" -ForegroundColor Yellow
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
        $videoTitle = if ($Status) { Get-DisplayValue $Status.video_title "等待任务" } else { "等待任务" }
        $line = "[{0}] {1}% · {2} · {3} · {4}" -f `
            $now.ToString("HH:mm:ss"), $progress, $stage, $videoTitle, $gpuStatus
        Write-Host $line
        $script:lastDashboardSignature = $signature
        $script:lastDashboardHeartbeat = $now
    }

}

function Test-PortAvailable([int]$ListenPort) {
    $listener = $null
    try {
        $listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Any, $ListenPort)
        $listener.Start()
        return $true
    } catch {
        return $false
    } finally {
        if ($listener) { $listener.Stop() }
    }
}

function Get-CloudflaredPath {
    $candidates = @(
        (Join-Path $projectRoot "tools\network\cloudflared.exe"),
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

if (-not (Test-PortAvailable $Port)) {
    $requestedPort = $Port
    $fallbackPort = $null
    foreach ($candidate in 18766..18785) {
        if (Test-PortAvailable $candidate) {
            $fallbackPort = $candidate
            break
        }
    }
    if ($null -eq $fallbackPort) {
        throw "Port $requestedPort is unavailable and no fallback port in 18766-18785 could be opened."
    }
    $Port = [int]$fallbackPort
    $env:WHISPER_PORT = "$Port"
    Write-Host "Port $requestedPort is bound by another Windows process; using computer port $Port instead." -ForegroundColor Yellow
    Write-Host "USB phones still use 127.0.0.1:8766; adb reverse maps it to computer port $Port." -ForegroundColor Yellow
}

$tailscale = if ($NoTailscale) { $null } else { Get-TailscalePath }
$tailscaleBase = if ($tailscale) { Enable-TailscalePrivateServe $tailscale } else { "" }
$githubConfigUrl = Get-GitHubConfigUrl
if (-not $tailscaleBase -and -not $NoTailscale) {
    Write-Host "Tailscale private address unavailable; install/sign in to Tailscale for a stable remote address." -ForegroundColor Yellow
}
Write-RuntimeConfig "" $tailscaleBase $githubConfigUrl
Write-LatestServiceUrls "" $tailscaleBase $githubConfigUrl

$adb = Get-AdbPath
$adbJob = $null
if ($adb) {
    $adbJob = Start-Job -ArgumentList $adb, $Port, $runtimeConfig -ScriptBlock {
        param($AdbExe, $ListenPort, $ConfigPath)
        $sentConfig = @{}
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
                    if (Test-Path -LiteralPath $ConfigPath) {
                        $configJson = Get-Content -LiteralPath $ConfigPath -Raw -Encoding utf8
                        $configObject = $configJson | ConvertFrom-Json
                        $fingerprintSource = (@($configObject.transcribe_urls) -join "|") + "|" + [string]$configObject.tailscale_url + "|" + [string]$configObject.public_url + "|" + [string]$configObject.github_config_url
                        $fingerprint = [Convert]::ToBase64String([Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($fingerprintSource)))
                        if ($sentConfig[$serial] -ne $fingerprint) {
                            $encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($configJson))
                            $broadcast = (& $AdbExe -s $serial shell am broadcast `
                                -a com.codex.videolearnenglish.APPLY_SERVICE_CONFIG `
                                -n com.codex.videolearnenglish.remote/com.codex.videolearnenglish.ServiceConfigReceiver `
                                --es config_base64 $encoded 2>&1) -join "`n"
                            if ($LASTEXITCODE -eq 0 -and $broadcast -match "Broadcast completed") {
                                $sentConfig[$serial] = $fingerprint
                                Write-Output "Phone service addresses updated for ${serial} (USB/LAN/Tailscale/GitHub discovery)."
                            } else {
                                Write-Output "Phone pairing pending for ${serial}; install/open v2.1.0 and keep USB debugging allowed."
                            }
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

$serviceJobScript = {
    param($Root, $ListenPort, $AuthToken, $ConfigPath, $StatusPath, $RuntimePath, $TranslationProvider, $TranslationModel, $TranslationDevice, $TranslationSourceLanguage, $TranslationTargetLanguage, $TranslationStyle, $WhisperDevice, $WhisperComputeType, $WhisperEnglishModel, $WhisperHotwords, $WhisperInitialPrompt)
    Set-Location $Root
    $env:PATH = $RuntimePath
    $env:WHISPER_PORT = "$ListenPort"
    $env:VIDEO_ENGLISH_DATA_DIR = Join-Path $Root "service_data_v2.1.0"
    $env:SAT_MODEL_DIR = Join-Path $Root "models\sat-12l-sm"
    $env:SAT_TOKENIZER_DIR = Join-Path $Root "models\xlm-roberta-base"
    $env:SPACY_MODEL = "en_core_web_trf"
    $env:SEMANTIC_PYTHON = "D:\anaconda\envs\subtitle\python.exe"
    $env:SUBTITLE_SEMANTIC_ENABLED = "1"
    $env:SUBTITLE_SEMANTIC_FALLBACK = "1"
    $env:WHISPERX_PYTHON = "D:\Anaconda\envs\video-english-whisperx\python.exe"
    $env:WHISPERX_MODEL_DIR = Join-Path $Root "models\whisperx"
    $env:WHISPERX_DEVICE = "cuda"
    $env:WHISPERX_REQUIRED = "1"
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
    & $servicePythonExe tools\versions\v2.1.0\service.py 2>&1 | ForEach-Object { [string]$_ }
    $exitCode = $LASTEXITCODE
    throw "Python service exited unexpectedly with code $exitCode"
}
$serviceJobArguments = @(
    $projectRoot, $Port, $token, $runtimeConfig, $runtimeStatus, $env:PATH,
    $env:TRANSLATION_PROVIDER, $env:TRANSLATION_MODEL, $env:TRANSLATION_DEVICE,
    $env:TRANSLATION_SOURCE_LANGUAGE, $env:TRANSLATION_TARGET_LANGUAGE,
    $env:TRANSLATION_STYLE, $env:WHISPER_DEVICE, $env:WHISPER_COMPUTE_TYPE,
    $env:WHISPER_ENGLISH_MODEL, $env:WHISPER_HOTWORDS, $env:WHISPER_INITIAL_PROMPT
)
function Start-ServiceBackgroundJob {
    return Start-Job -ArgumentList $serviceJobArguments -ScriptBlock $serviceJobScript
}

function Test-LocalServiceHealth {
    try {
        $probeUrl = "http://127.0.0.1:$Port/ping"
        if ($token) {
            $probeUrl += "?token=$([System.Uri]::EscapeDataString($token))"
        }
        $probe = Invoke-WebRequest -UseBasicParsing -Uri $probeUrl -TimeoutSec 2
        return $probe.StatusCode -eq 200
    } catch {
        return $false
    }
}

$serviceJob = Start-ServiceBackgroundJob

$publicTunnelEnabled = -not $NoPublicTunnel
$cloudflared = if ($publicTunnelEnabled) { Get-CloudflaredPath } else { $null }
$cloudJob = $null
$recentLogs = New-Object 'System.Collections.Generic.Queue[string]'
$publicBase = ""
$printedPublicBase = ""
$serviceRestartCount = 0
$nextServiceRestartAt = [datetime]::MinValue

try {
    $dashboardUrl = New-DashboardUrl
    $serviceReady = $false
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        try {
            $pingUrl = "http://127.0.0.1:$Port/ping"
            if ($token) {
                $pingUrl += "?token=$([System.Uri]::EscapeDataString($token))"
            }
            $response = Invoke-WebRequest -UseBasicParsing -Uri $pingUrl -TimeoutSec 2
            if ($response.StatusCode -eq 200) {
                $serviceReady = $true
                break
            }
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }
    if ($serviceReady -and -not $NoDashboard) {
        Start-Process $dashboardUrl
    } elseif (-not $serviceReady) {
        Add-RecentLog $recentLogs "Service did not become ready in 20 seconds; dashboard was not opened."
    }
    if ($cloudflared) {
        Add-RecentLog $recentLogs "Starting Cloudflare tunnel for data/mobile-network fallback..."
        $cloudJob = Start-Job -ArgumentList $cloudflared, $Port -ScriptBlock {
            param($CloudflaredExe, $ListenPort)
            & $CloudflaredExe tunnel --protocol http2 --url "http://127.0.0.1:$ListenPort" 2>&1 | ForEach-Object { [string]$_ }
        }
    } elseif ($publicTunnelEnabled) {
        Add-RecentLog $recentLogs "Automatic public tunnel needs cloudflared. Install with: winget install --id Cloudflare.cloudflared"
    }

    while ($true) {
        foreach ($line in Receive-Job -Job $serviceJob -ErrorAction SilentlyContinue) {
            Add-ServiceRuntimeLog $recentLogs ([string]$line)
        }
        if ($serviceJob.State -in @("Failed", "Stopped", "Completed")) {
            $now = Get-Date
            if ($now -ge $nextServiceRestartAt) {
                $terminalState = [string]$serviceJob.State
                $reason = ""
                if ($serviceJob.ChildJobs.Count -gt 0 -and $serviceJob.ChildJobs[0].JobStateInfo.Reason) {
                    $reason = [string]$serviceJob.ChildJobs[0].JobStateInfo.Reason.Message
                }
                $detail = if ($reason) { " ($reason)" } else { "" }
                Add-ServiceRuntimeLog $recentLogs "Python service stopped: $terminalState$detail"
                Remove-Job -Job $serviceJob -Force -ErrorAction SilentlyContinue
                $serviceJob = Start-ServiceBackgroundJob
                $serviceRestartCount += 1
                $backoffSeconds = [Math]::Min(30, [Math]::Pow(2, [Math]::Min(4, $serviceRestartCount - 1)))
                $nextServiceRestartAt = $now.AddSeconds($backoffSeconds)
                Add-ServiceRuntimeLog $recentLogs "Python service watchdog restart #$serviceRestartCount started."
            }
        } elseif ($serviceRestartCount -gt 0 -and (Test-LocalServiceHealth)) {
            Add-ServiceRuntimeLog $recentLogs "Python service health check passed after restart."
            $serviceRestartCount = 0
            $nextServiceRestartAt = [datetime]::MinValue
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
                        $githubConfigUrl = Publish-GitHubServiceConfig $publicBase
                        Write-RuntimeConfig $publicBase $tailscaleBase $githubConfigUrl
                        Write-LatestServiceUrls $publicBase $tailscaleBase $githubConfigUrl
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

        Write-RuntimeConfig $publicBase $tailscaleBase $githubConfigUrl
        Write-LatestServiceUrls $publicBase $tailscaleBase $githubConfigUrl
        $status = Read-RuntimeStatus
        Write-ServiceDashboard -Status $status -RecentLogs $recentLogs -PublicBase $publicBase -TailscaleBase $tailscaleBase
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
