# Release Files

This directory is intentionally tracked so GitHub users can install the Android app without building it first.

Expected files:

- `app-v1.0.0.apk`: previous 1.0.0 package. It keeps the original single learning screen where video learning, subtitle generation, translation, replay, dictionary lookup, and subtitle export are all handled in one page.
- `app-v2.0.0.apk`: previous 2.0.0 package with four-tab task management and batch caption generation.
- `app-v2.0.1.apk`: current 2.0.1 package. It adds explicit full bilingual subtitle regeneration, atomic cache replacement, reliable foreground processing across screen-off/unlock, and improved word lemmatization.
- `app-debug.apk`: legacy debug APK kept for compatibility with older README links.
- `SHA256SUMS.txt`: SHA-256 checksums for versioned APKs.

Generate them from an existing debug build:

```powershell
Copy-Item app/build/outputs/apk/debug/app-debug.apk release/app-v2.0.1.apk -Force
$hash = Get-FileHash -Algorithm SHA256 release/app-v2.0.1.apk
"$($hash.Hash.ToLower())  app-v2.0.1.apk" | Add-Content -Encoding UTF8 release/SHA256SUMS.txt
```

Install with adb:

```powershell
adb install -r release/app-v2.0.1.apk
```

For public distribution, prefer publishing a signed release APK through GitHub Releases. This debug APK is convenient for testing and open-source demos.
