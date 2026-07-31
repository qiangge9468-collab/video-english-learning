param(
    [string]$CondaExe = "D:\Anaconda\Scripts\conda.exe",
    [string]$EnvironmentName = "video-english-whisperx"
)

$ErrorActionPreference = "Stop"

function Repair-LocalProxyEnv {
    foreach ($name in @("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")) {
        $item = Get-Item "Env:\$name" -ErrorAction SilentlyContinue
        if ($item -and [string]$item.Value -match "^https://(127\.0\.0\.1|localhost)(:\d+)?(/.*)?$") {
            Set-Item "Env:\$name" ("http://" + ([string]$item.Value).Substring("https://".Length))
        }
    }
}

Repair-LocalProxyEnv

if (-not (Test-Path -LiteralPath $CondaExe)) {
    throw "Conda was not found: $CondaExe"
}

$environmentRoot = Join-Path (Split-Path -Parent (Split-Path -Parent $CondaExe)) "envs\$EnvironmentName"
$python = Join-Path $environmentRoot "python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    & $CondaExe create -n $EnvironmentName python=3.11 -y
    if ($LASTEXITCODE -ne 0) { throw "Could not create the WhisperX Conda environment." }
}

& $python -m pip install "whisperx==3.8.6"
if ($LASTEXITCODE -ne 0) { throw "Could not install WhisperX 3.8.6." }

& $python -m pip install --force-reinstall "torch==2.8.0" "torchvision==0.23.0" "torchaudio==2.8.0" --index-url "https://download.pytorch.org/whl/cu128"
if ($LASTEXITCODE -ne 0) { throw "Could not install CUDA PyTorch for WhisperX." }

& $CondaExe install -n $EnvironmentName -c conda-forge ffmpeg -y
if ($LASTEXITCODE -ne 0) { throw "Could not install ffmpeg for WhisperX." }

$projectRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
$modelDir = Join-Path $projectRoot "models\whisperx"
New-Item -ItemType Directory -Path $modelDir -Force | Out-Null
$env:TORCH_HOME = $modelDir

& $python -c "import importlib.metadata as m, torch, whisperx; assert m.version('whisperx') == '3.8.6'; assert torch.cuda.is_available(); whisperx.load_align_model(language_code='en', device='cuda', model_dir=r'$modelDir'); print('WhisperX CUDA ready:', torch.cuda.get_device_name(0))"
if ($LASTEXITCODE -ne 0) { throw "WhisperX CUDA/model preflight failed." }

Write-Host "WhisperX 3.8.6 CUDA environment and English alignment model are ready." -ForegroundColor Green
