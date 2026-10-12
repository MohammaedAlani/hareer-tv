# Build and publish an APK locally

GitHub Actions must not build/sign/upload the APK. The release artifact comes from the maintainer's machine; GitHub Releases distributes it to the deployment build.

## Signing key

Use JDK 17, Android SDK 35, and Python 3. Run:

```sh
python3 scripts/build-release.py --catalog-url=https://tv.nawaa.app/videos.json
```

The first run creates a signing key and random credentials under `~/.local/share/hareer-tv/signing/`, with private filesystem permissions. Later runs reuse that key. `HAREER_SIGNING_DIR` can select a different private directory. Keep an encrypted backup of **the complete signing directory**; losing it prevents compatible updates. Never commit or upload it as a GitHub release asset.

The script runs Android tests, release lint, and the release build locally, then writes `dist/hareer-tv-VERSION.apk` and `dist/SHA256SUMS.txt`. `dist/` is ignored by Git. It never prints the key passwords.

## Publish a new version

1. Increment `versionCode` and `versionName` in `app/build.gradle`.
2. Run the local release script and verify the APK signature using the SDK's `apksigner verify --verbose`.
3. Update `deploy/apk.json` with that artifact's version, filename, GitHub Release URL, and SHA-256. Update the landing page download/install text and deployment docs for that version.
4. Test the backend and landing page, review changes, and commit/push to `main`.
5. Tag that source commit, then create a GitHub Release with the locally built APK and checksum file. Do not overwrite an existing version with different bytes or a new signing key.
6. Build the server container from the pushed source commit. Its asset stage downloads and verifies the release APK; it never invokes Gradle.

Example for a new version (replace `VERSION` throughout):

```sh
git tag -a vVERSION -m 'Hareer TV VERSION'
git push origin vVERSION
gh release create vVERSION dist/hareer-tv-VERSION.apk dist/SHA256SUMS.txt \
  --verify-tag --title 'Hareer TV VERSION' --notes-file .private/release-notes.md
```

The earlier development APK was signed with a debug key. Installing this release over that debug build may fail with an incompatible-signature error. Uninstall the test build first if appropriate; this removes its local data. Do not uninstall or deprovision a managed device without its administrator's instructions. Subsequent releases must use the same release key and a larger version code.
