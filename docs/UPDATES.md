# Updating Hareer TV

Version 1.1.0 adds a remote-friendly **Update** button to the library. Updates are checked only when a grown-up chooses this button and solves the existing star puzzle. Nothing interrupts playback or installs automatically. The puzzle is a light gate, not a secure parent PIN.

1. Choose **Update**, then solve the puzzle.
2. If a newer version is available, choose **Download**.
3. Choose **Install**. Android may first ask you to allow Hareer TV to install unknown apps. Enable that permission and return to the app.
4. Confirm **Install** again, then approve Android’s installation prompt. Reopen Hareer TV if the TV does not reopen it automatically.

Existing versions without the Update button need one manual installation of 1.1.0 or newer. Install over the existing release to retain app data. Debug builds use a different signing key and cannot update to production in place.

The app downloads metadata from `https://tv.nawaa.app/downloads/update.json`. Metadata includes `versionCode`, `version`, `url`, and `sha256`; it is generated from `deploy/apk.json` during the server build. Release builds require HTTPS for metadata, APKs, and redirects. Downloads are capped at 50 MiB. Before offering installation, the app verifies the checksum, package name, a strictly newer version code matching metadata, and the same signing certificate as the installed app. Android performs its own installation verification too.

APK builds and signing remain local. Follow [RELEASING.md](RELEASING.md) for each release, increase both version fields, and keep the original signing key. The build script produces `dist/apk.json` for copying to `deploy/apk.json`. Publish the GitHub Release assets **before pushing main** so the server pipeline can fetch them. Fork maintainers can build with `--update-url=https://YOUR_HOST/downloads/update.json` and change the release URL to their own repository.

Configure your CDN to bypass caching for `/downloads/update.json` (or use a short TTL). An unreachable endpoint, invalid metadata, checksum failure, or incompatible signature leaves the installed version intact. A failed download can be retried with **Update**. Only one check/download runs at a time; keep the app open until it finishes.

Kiosk mode is temporarily stopped only after the puzzle and installation approval, so Android’s permission and installation screens can open. The app restores its prior lock-task state when those screens return; on a device-owner installation, startup also re-enters kiosk mode. Test this flow on your TV: device policies may forbid sideloading or hide the installer. A manual installation remains available in that case. Android installation cannot be silently forced by this app.
