# Release Files

This directory is intentionally tracked so GitHub users can install the Android app without building it first.

Expected files:

- `app-v1.0.0.apk`: previous 1.0.0 package. It keeps the original single learning screen where video learning, subtitle generation, translation, replay, dictionary lookup, and subtitle export are all handled in one page.
- `app-v2.0.0.apk`: previous 2.0.0 package with four-tab task management and batch caption generation.
- `app-v2.0.1.apk`: previous 2.0.1 package. It adds explicit full bilingual subtitle regeneration, atomic cache replacement, reliable foreground processing across screen-off/unlock, and improved word lemmatization.
- `app-v2.0.2.apk`: previous 2.0.2 package. It adds automatic USB -> LAN -> public failover, upload-all-first batching, a persistent FIFO computer queue, offline progress recovery, visible-frame task covers, and reusable audio/English/bilingual caches.
- `app-v2.0.3.apk`: previous 2.0.3 package. It repairs `adb reverse` after a real phone is unplugged and reconnected, improves connection recovery, playback boundaries, dictionary lookup, and semantic English subtitle segmentation. Pair it with the v2.0.3 computer service.
- `app-v2.0.4.apk`: current 2.0.4 package. It changes subtitle sync adjustments to 0.05 seconds, immediately yields computer-result polling when a new video needs extraction/upload, keeps foreground CPU/Wi-Fi locks continuously across queued stages, and submits durable FIFO computer jobs before returning to result polling. Pair it with `tools/start_video_english_service_v2.0.4.ps1` and `tools/local_whisper_service_v2.0.4.py`.
- Legacy APKs remain paired with `tools/start_video_english_service.ps1` and `tools/local_whisper_service.py`; those existing files are intentionally preserved.
- `app-debug.apk`: legacy debug APK kept for compatibility with older README links.
- `SHA256SUMS.txt`: SHA-256 checksums for versioned APKs.

Generate them from an existing debug build:

```powershell
Copy-Item app/build/outputs/apk/debug/app-debug.apk release/app-v2.0.4.apk -Force
$hash = Get-FileHash -Algorithm SHA256 release/app-v2.0.4.apk
"$($hash.Hash.ToLower())  app-v2.0.4.apk" | Add-Content -Encoding UTF8 release/SHA256SUMS.txt
```

Install with adb:

```powershell
adb install -r release/app-v2.0.4.apk
```

For public distribution, prefer publishing a signed release APK through GitHub Releases. This debug APK is convenient for testing and open-source demos.
