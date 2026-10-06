# Release Files

This directory is intentionally tracked so GitHub users can install the Android app without building it first.

Expected files:

- `app-v2.2.0.apk`: current recommended phone package (versionName 2.2.0, versionCode 29). Includes the fullscreen control-layout bug fix: edge-to-edge gradients with cutout-safe controls, previous/next sentence actions, and inline video controls that appear on single tap, with double-tap playback. Time, progress and fullscreen entry now live inside the learning-page video. Keeps current-sentence bilingual subtitles, dragging/resizing/locking and word lookup. Pair with the existing v2.1.0 computer service. The original versionCode 28 APK remains available at Git commit `47d1145`; all other versioned APKs remain untouched.
- `app-v1.0.0.apk`: previous 1.0.0 package. It keeps the original single learning screen where video learning, subtitle generation, translation, replay, dictionary lookup, and subtitle export are all handled in one page.
- `app-v2.0.0.apk`: previous 2.0.0 package with four-tab task management and batch caption generation.
- `app-v2.0.1.apk`: previous 2.0.1 package. It adds explicit full bilingual subtitle regeneration, atomic cache replacement, reliable foreground processing across screen-off/unlock, and improved word lemmatization.
- `app-v2.0.2.apk`: previous 2.0.2 package. It adds automatic USB -> LAN -> public failover, upload-all-first batching, a persistent FIFO computer queue, offline progress recovery, visible-frame task covers, and reusable audio/English/bilingual caches.
- `app-v2.0.3.apk`: previous 2.0.3 package. It repairs `adb reverse` after a real phone is unplugged and reconnected, improves connection recovery, playback boundaries, dictionary lookup, and semantic English subtitle segmentation. Pair it with the v2.0.3 computer service.
- `app-v2.0.4.apk`: previous 2.0.4 package. It changes subtitle sync adjustments to 0.05 seconds, immediately yields computer-result polling when a new video needs extraction/upload, keeps foreground CPU/Wi-Fi locks continuously across queued stages, submits durable FIFO computer jobs before returning to result polling, and refreshes saved service URLs/tokens during background reconnects. The paired v2.0.4 computer service also recovers VAD-confirmed speech gaps, guards numeric/NLLB translations against runaway repetition, and retries under-translated clauses before they can enter the bilingual cache. Pair it with `tools/versions/v2.0.4/start_service.ps1` and `tools/versions/v2.0.4/service.py`.
- `app-v2.0.5.apk`: previous 2.0.5 package. It preserves the v2.0.4 caption, translation, queue, background-upload and 0.05-second sync fixes, keeps the user's scroll position while a long processing queue refreshes, resets to the first item only when the page is entered again, refreshes the Chinese author profile, and pairs with an automatically opened local web dashboard showing the current video, progress/ETA, FIFO queue, models, GPU, connection URLs and recent outcomes. Pair it with `tools/versions/v2.0.5/start_service.ps1` and `tools/versions/v2.0.5/service.py`.
- `app-v2.0.6.apk`: current 2.0.6 phone package. It keeps the v2.0.5 computer protocol, fixes inflection lookup with the ECDICT lemma map, adds selected Open English WordNet definitions/relations/examples, common collocations, tappable UK/US pronunciation controls, and tap-anywhere video play/pause. Pair it with the unchanged `tools/versions/v2.0.5/start_service.ps1` and `tools/versions/v2.0.5/service.py`.
- `app-v2.1.0.apk`: preserved previous phone package. It adds review practice, first-time USB pairing, persistent local tokens, Tailscale private access, a fixed token-free official Gist fallback for older pairings, and automatic discovery of the latest Cloudflare public base URL when the phone is not connected by USB. Pair it with `tools/versions/v2.1.0/start_service.ps1` and `tools/versions/v2.1.0/service.py`.
- Legacy APKs remain paired with `tools/versions/legacy/start_service.ps1` and `tools/versions/legacy/service.py`; those existing files are intentionally preserved.
- `app-debug.apk`: legacy debug APK kept for compatibility with older README links.
- `SHA256SUMS.txt`: SHA-256 checksums for versioned APKs.

Generate them from an existing debug build:

```powershell
Copy-Item app/build/outputs/apk/debug/app-debug.apk release/app-v2.2.0.apk
$hash = Get-FileHash -Algorithm SHA256 release/app-v2.2.0.apk
"$($hash.Hash.ToLower())  app-v2.2.0.apk" | Add-Content -Encoding UTF8 release/SHA256SUMS.txt
```

Install with adb:

```powershell
adb install -r release/app-v2.2.0.apk
```

For public distribution, prefer publishing a signed release APK through GitHub Releases. This debug APK is convenient for testing and open-source demos.
