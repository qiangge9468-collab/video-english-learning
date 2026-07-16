# Release Files

This directory is intentionally tracked so GitHub users can install the Android app without building it first.

Expected files:

- `app-v1.0.0.apk`: previous 1.0.0 package. It keeps the original single learning screen where video learning, subtitle generation, translation, replay, dictionary lookup, and subtitle export are all handled in one page.
- `app-v2.0.0.apk`: current 2.0.0 package. It adds four bottom tabs with real icons: Learning, Generating Subtitles, Completed, and Mine. It also adds illustrated empty states, video first-frame task thumbnails, and an author card. The Generating Subtitles tab can batch-select multiple videos, pause/resume/retry tasks, and queue background English subtitle generation plus Chinese translation. The Completed tab manages finished bilingual subtitle videos.
- `app-debug.apk`: legacy debug APK kept for compatibility with older README links.
- `SHA256SUMS.txt`: SHA-256 checksums for versioned APKs.

Generate them from an existing debug build:

```powershell
Copy-Item app/build/outputs/apk/debug/app-debug.apk release/app-v2.0.0.apk -Force
$hash = Get-FileHash -Algorithm SHA256 release/app-v2.0.0.apk
"$($hash.Hash.ToLower())  app-v2.0.0.apk" | Set-Content -Encoding UTF8 release/SHA256SUMS.txt
```

Install with adb:

```powershell
adb install -r release/app-v2.0.0.apk
```

For public distribution, prefer publishing a signed release APK through GitHub Releases. This debug APK is convenient for testing and open-source demos.
