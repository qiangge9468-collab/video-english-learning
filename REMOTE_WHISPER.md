# Remote Whisper Caption Generation

This project can generate captions on a computer and send the result back to the Android app.

Flow:

1. The Android app extracts 16 kHz mono WAV audio from the current video.
2. The app uploads the audio to `POST /jobs`.
3. The computer runs `faster-whisper`.
4. The app polls `GET /jobs/<id>` for progress.
5. The completed subtitle JSON is cached on the phone.

## Start The Service

```powershell
powershell -ExecutionPolicy Bypass -File tools/start_remote_whisper_service.ps1
```

The script prints an auth token. Keep the service window open.

Useful endpoints:

```text
GET  /ping
GET  /models?token=<token>
POST /jobs?token=<token>
GET  /jobs/<id>?token=<token>
```

## USB Phone Test

Connect the phone with USB debugging enabled:

```powershell
adb devices
adb reverse --remove tcp:8765
adb reverse tcp:8765 tcp:8765
```

In the app, long-press `生成` and set:

```text
http://127.0.0.1:8765/transcribe?token=<token>
```

Tap `测试`, then tap `生成`.

## Remote Test With Cloudflare Tunnel

Install Cloudflare Tunnel:

```powershell
winget install --id Cloudflare.cloudflared
```

Or put `cloudflared.exe` at:

```text
tools/cloudflared.exe
```

Run this in a second PowerShell window:

```powershell
$env:WHISPER_AUTH_TOKEN="paste the token printed by the service"
powershell -ExecutionPolicy Bypass -File tools/start_cloudflare_tunnel.ps1
```

When a `trycloudflare.com` URL appears, set the app service URL to:

```text
https://xxxxx.trycloudflare.com/transcribe?token=<token>
```

Keep both windows open while generating captions:

- Whisper service
- Cloudflare tunnel

### One-Window Public Test

For phone mobile data, guest Wi-Fi, or any network that is not the same LAN as the computer, use a public HTTPS tunnel.
This starts the Whisper service with a token and opens Cloudflare Tunnel in one PowerShell window:

```powershell
powershell -ExecutionPolicy Bypass -File tools/start_public_whisper_service.ps1
```

The script prints an `Auth token` first. A few seconds later, `cloudflared` prints an HTTPS URL like:

```text
https://xxxxx.trycloudflare.com
```

In the Android app, long-press `生成`, set the service URL to:

```text
https://xxxxx.trycloudflare.com/transcribe?token=<Auth token printed by the script>
```

Tap `测试`. If it says the Whisper service is reachable, return and tap `生成`.

You can also test the public URL from the computer before using the phone:

```powershell
powershell -ExecutionPolicy Bypass -File tools/test_remote_whisper_service.ps1 `
  -AppUrl "https://xxxxx.trycloudflare.com/transcribe" `
  -Token "<Auth token printed by the script>"
```

This checks `/ping`, `/models`, and `POST /jobs`. If this script passes, the Android app should be able to upload audio from mobile data too.

## Accuracy Notes

- The app uploads audio, not the full video.
- English captions prefer local `models/faster-whisper-small`, then `models/faster-whisper-medium`.
- Other languages prefer a multilingual medium model.
- The service uses VAD, beam search, word timestamps, deterministic temperature, and sentence-level post-processing.
- Better audio and larger models usually produce better subtitle timing and text.

## GPU

For NVIDIA CUDA:

```powershell
$env:WHISPER_DEVICE="cuda"
$env:WHISPER_COMPUTE_TYPE="float16"
powershell -ExecutionPolicy Bypass -File tools/start_remote_whisper_service.ps1
```
