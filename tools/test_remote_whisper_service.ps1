param(
    [Parameter(Mandatory = $true)]
    [string]$AppUrl,

    [string]$Token = $env:WHISPER_AUTH_TOKEN
)

$ErrorActionPreference = "Stop"

function Join-TokenQuery([string]$Url, [string]$AuthToken) {
    if (-not $AuthToken) {
        return $Url
    }
    if ($Url -match "[?&]token=") {
        return $Url
    }
    $separator = "?"
    if ($Url.Contains("?")) {
        $separator = "&"
    }
    return "${Url}${separator}token=${AuthToken}"
}

function Root-Url([string]$Url) {
    $base = $Url.Split("?")[0].TrimEnd("/")
    if ($base.EndsWith("/transcribe")) {
        return $base.Substring(0, $base.Length - "/transcribe".Length)
    }
    if ($base.EndsWith("/jobs")) {
        return $base.Substring(0, $base.Length - "/jobs".Length)
    }
    return $base
}

function Invoke-Text([string]$Url, [string]$Method = "GET", [byte[]]$Body = $null, [string]$ContentType = "text/plain") {
    if ($Body) {
        return Invoke-WebRequest -UseBasicParsing -Method $Method -Uri $Url -Body $Body -ContentType $ContentType -TimeoutSec 60
    }
    return Invoke-WebRequest -UseBasicParsing -Method $Method -Uri $Url -TimeoutSec 30
}

$fullAppUrl = Join-TokenQuery $AppUrl $Token
$root = Root-Url $fullAppUrl
$query = ""
if ($fullAppUrl.Contains("?")) {
    $query = "?" + $fullAppUrl.Split("?", 2)[1]
}

$pingUrl = "${root}/ping${query}"
$modelsUrl = "${root}/models${query}"
$jobsUrl = "${root}/jobs${query}"

Write-Host "Testing remote Whisper service..."
Write-Host "App URL: $fullAppUrl"
Write-Host "Ping:    $pingUrl"

try {
    $ping = Invoke-Text $pingUrl
    Write-Host "OK: /ping -> $($ping.Content)"
} catch {
    Write-Host "FAILED: /ping"
    Write-Host $_.Exception.Message
    exit 1
}

if ($Token) {
    try {
        $openPing = Invoke-Text "${root}/ping"
        if ($openPing.StatusCode -ge 200 -and $openPing.StatusCode -lt 300) {
            Write-Host "WARNING: /ping also works without token. Do not expose this service publicly unless you meant to disable auth."
        }
    } catch {
        Write-Host "OK: unauthenticated /ping is blocked."
    }
}

try {
    $models = Invoke-Text $modelsUrl
    Write-Host "OK: /models"
    Write-Host $models.Content
} catch {
    Write-Host "WARNING: /models failed"
    Write-Host $_.Exception.Message
}

try {
    $tinyWav = [byte[]]@(82,73,70,70,36,0,0,0,87,65,86,69,102,109,116,32,16,0,0,0,1,0,1,0,128,62,0,0,0,125,0,0,2,0,16,0,100,97,116,97,0,0,0,0)
    $job = Invoke-Text $jobsUrl "POST" $tinyWav "audio/wav"
    Write-Host "OK: POST /jobs accepted upload"
    Write-Host $job.Content
} catch {
    Write-Host "FAILED: POST /jobs"
    Write-Host $_.Exception.Message
    exit 1
}

Write-Host ""
Write-Host "Remote service is reachable. Use this in the Android app:"
Write-Host "  $fullAppUrl"
