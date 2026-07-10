# Release Files

This directory is intentionally tracked so GitHub users can install the Android app without building it first.

Expected files:

- `app-debug.apk`: installable debug APK.
- `SHA256SUMS.txt`: SHA-256 checksum for the APK.

Generate them from an existing debug build:

```powershell
Copy-Item app/build/intermediates/apk/debug/app-debug.apk release/app-debug.apk -Force
$hash = Get-FileHash -Algorithm SHA256 release/app-debug.apk
"$($hash.Hash.ToLower())  app-debug.apk" | Set-Content -Encoding UTF8 release/SHA256SUMS.txt
```

Install with adb:

```powershell
adb install -r release/app-debug.apk
```

For public distribution, prefer publishing a signed release APK through GitHub Releases. This debug APK is convenient for testing and open-source demos.
