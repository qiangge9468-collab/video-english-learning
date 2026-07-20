param(
    [string]$SampleAudio = "third_party\whisper.cpp\samples\jfk.mp3"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $projectRoot

@'
import sys
from pathlib import Path

root = Path.cwd()
sys.path.insert(0, str(root / "tools"))
import local_whisper_service as service

sample = root / "third_party" / "whisper.cpp" / "samples" / "jfk.mp3"
asr_model = root / "models" / "faster-whisper-large-v3"

print("Testing large-v3 on CUDA...")
model = service.get_whisper_model(str(asr_model))
segments, info = model.transcribe(str(sample), language="en", beam_size=1)
text = " ".join(segment.text.strip() for segment in segments)
print(f"ASR language={info.language}, duration={info.duration:.2f}s")
print(text)

print()
print("Testing NLLB-200-600M on CUDA...")
translations = service.translate_texts([
    "This is the long way around Africa.",
    "If you are going to cross Africa coast to coast, you need serious planning.",
])
for item in translations:
    print(item)
'@ | python -
