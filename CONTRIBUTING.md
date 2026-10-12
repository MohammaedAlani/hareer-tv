# Contributing to Hareer TV

Use JDK 17 and Android SDK 35. Fork the repository, create a branch, and follow the README to build with a test catalog. Keep pull requests focused and explain the problem, the resulting behavior, and how you tested it.

## Project layout

- `app/src/main/java/family/blossom/tv/`: native Java app, catalog parsing, network requests, and kiosk receiver.
- `app/src/main/res/`: theme, launcher artwork, and device-admin configuration.
- `app/src/test/`: catalog unit tests.
- `examples/videos.json`: backend response contract.
- `backend/`: Python standard-library catalog API backed by SQLite.
- `site/`: buildless landing page.
- `deploy/`: pinned APK metadata and Kubernetes template.

Before opening a pull request, run:

```sh
./gradlew :app:testDebugUnitTest :app:lintDebug :app:assembleDebug
```

Install `backend/requirements.txt` in a Python 3.12+ virtual environment. Run `python3 -m unittest discover -s backend -p 'test_*.py'` for backend changes and `node --check site/app.js` and `node --check site/admin/admin.js` for website JavaScript. Queue tests use fake storage/downloaders and a synthetic local FFmpeg clip; never add production videos as test fixtures. APK releases are built locally, never by GitHub Actions.

Add focused tests when behavior changes. For UI changes, also exercise the D-pad and provide a screenshot. For playback changes, use media you own or are permitted to use; check pause/resume, Back, failed playback, and leaving/reopening the app. For kiosk changes, use a disposable emulator or dedicated test device and verify both Home blocking and exit after solving the puzzle.

Please preserve visible remote focus, large controls, an uncomplicated child-facing screen, and the absence of arbitrary browsing. Keep parent/device configuration out of the children's flow.

Do not commit `local.properties`, signing keys, private URLs, access tokens, videos, build outputs, or screenshots with private content. Examples should use reserved domains such as `your-server.example`.

For bug reports, include the app revision, device model, Android version, reproduction steps, and expected/actual behavior. Redact credentials and private URLs from logs. Use a private report for security issues as described in SECURITY.md.

Contributions are provided under the repository's MIT license. Please be respectful and constructive in discussions.
