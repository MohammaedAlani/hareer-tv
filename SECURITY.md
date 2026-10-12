# Security

Hareer TV is an early-stage project. Security fixes are developed on `main`; there is not yet a maintained release support matrix.

Please do not post exploitable vulnerabilities, credentials, or private media URLs in public issues. Use GitHub's **Security → Report a vulnerability** on this repository if that option is available. If it is unavailable, open an issue asking the maintainer for a private reporting channel, without including the vulnerability details.

Include the affected revision, Android/device version, reproduction steps, and impact in the private report. No response-time guarantee is currently offered.

## Boundaries

- The exit puzzle is a child-friendly interaction, not authentication.
- Home/Recents restrictions depend on Android kiosk provisioning and device support. Kiosk setup failure is reported, and the app can still open without that protection.
- The catalog is trusted configuration. The backend must authenticate access and authorize media requests when needed.
- Removing a catalog entry does not revoke an existing video URL or stop buffered playback.
- Debug builds permit cleartext HTTP. Release builds require HTTPS.
- No signing credentials or permanent API secrets belong in the repository or APK.

YouTube imports accept individual HTTPS video links from an explicit hostname allowlist. Storage keys remain server-side. The public media route issues short-lived signed S3 redirects only for currently published catalog entries; previously issued URLs remain valid until expiry. Keep admin tokens private and bypass CDN caching for admin/API/media responses.
