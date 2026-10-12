# Website, catalog backend, and Kubernetes deployment

The deployment serves:

| Path | Purpose |
| --- | --- |
| `/` | Hareer TV landing page and TV installation guide |
| `/downloads/hareer-tv-1.0.0.apk` | Exact signed APK downloaded from GitHub Releases during the container build |
| `/downloads/SHA256SUMS.txt` | APK checksum |
| `/videos.json` | Public catalog read by the official APK |
| `/api/admin/videos` | Bearer-token-protected catalog management |
| `/healthz` | Kubernetes health check |

The official APK uses `https://tv.nawaa.app/videos.json`. The first catalog is empty. The backend stores only video metadata in SQLite; S3 stores your media. It also supports a persistent, sequential YouTube import queue; see [IMPORTS.md](IMPORTS.md) for storage configuration and the admin page.

## Release flow

1. Build and sign the APK **on the maintainer's machine** with `scripts/build-release.py`.
2. Upload the APK plus `SHA256SUMS.txt` to a GitHub Release, and update the version, URL, and checksum in `deploy/apk.json`.
3. Push to `main`. The `Deploy server` workflow (`.github/workflows/deploy.yml`) runs the backend tests, builds the server image, and pushes it to Harbor as `registry.cloudfares.net/hareer-tv/app:prod-<commit>`. The image build fetches the APK from GitHub and fails if its SHA-256 does not match `deploy/apk.json`.
4. The workflow then commits the new image tag to `apps/hareer-tv/10-app.yaml` on the `prod` branch of `cloudfares-platform`, and Argo CD rolls it out to `tv.nawaa.app`.

The workflow runs only when the server-side files change (`Dockerfile`, `backend/`, `site/`, `deploy/apk.json`, `scripts/fetch-apk.py`). Android-only commits do not redeploy. Run it by hand from the Actions tab with **Run workflow**.

GitHub Actions never builds, signs, or uploads APKs and never creates releases. It builds only the server image, which downloads the APK you already published. The workflow needs the repository secrets `HARBOR_USER`, `HARBOR_PASS`, and `PLATFORM_DEPLOY_KEY`.

## Build the deployment image by hand

The workflow above normally does this. To build manually:

```sh
git clone https://github.com/MohammaedAlani/hareer-tv.git
cd hareer-tv
git checkout main
git pull --ff-only
docker build -t YOUR_REGISTRY/hareer-tv:YOUR_COMMIT .
docker push YOUR_REGISTRY/hareer-tv:YOUR_COMMIT
```

Use the commit tag you tested, rather than a mutable `latest` tag. For an amd64 cluster when building on Apple Silicon, use Docker Buildx with `--platform linux/amd64 --push` and your registry tag. The APK is architecture-independent Java code; the server image still needs to match the cluster architecture.

`deploy/apk.json` pins the exact release URL and checksum. A missing release or mismatched download makes the image build fail. APK binaries and signing keys are never committed to Git.

## Kubernetes setup

The template in `deploy/kubernetes.yaml` contains a namespace, 10 GiB PVC, a single-replica deployment, service, and ingress for `tv.nawaa.app`.

First create the namespace and an administrator secret:

```sh
kubectl create namespace hareer-tv
umask 077
mkdir -p .private
openssl rand -hex 32 > .private/admin-token
kubectl -n hareer-tv create secret generic hareer-admin --from-file=token=.private/admin-token
```

The generated token file includes a trailing newline; the server strips surrounding whitespace from `ADMIN_TOKEN`. Store the token securely and use its value for admin API requests. Do not commit it. The backend refuses to start with a token shorter than 32 characters.

Copy `deploy/kubernetes.yaml` to an ignored local file and change:

- `image` to your pushed image and immutable commit tag.
- `ingressClassName` to the ingress controller installed in your cluster.
- Storage class if your cluster has no default provisioner.
- TLS setup to match your certificate management. The referenced `hareer-tv-tls` secret must contain a certificate valid for `tv.nawaa.app`. If using cert-manager, add your existing issuer configuration; the template does not install an issuer.

Then apply your edited manifest:

```sh
kubectl apply -f .private/kubernetes.yaml
kubectl -n hareer-tv rollout status deployment/hareer-tv
```

The SQLite backend intentionally uses **one replica** with a persistent volume and a `Recreate` update strategy. Updates briefly interrupt the website/catalog. Do not scale it horizontally against separate SQLite databases. For multiple replicas, replace SQLite with a shared database first.

## Cloudflare and S3

Point the DNS record for `tv.nawaa.app` to your Kubernetes ingress. If proxying through Cloudflare, use **Full (strict)** TLS with a valid origin certificate. Ensure HTTP redirects to HTTPS at the ingress or Cloudflare. Do not use an “allow invalid certificate” workaround on the TV.

Bypass CDN caching for `/videos.json`, `/api/*`, and `/healthz`; the API also sends `Cache-Control: no-store`. Static assets and versioned APKs may be cached. Keep `/api/admin/*` restricted to your administrative access where possible and preserve the `Authorization` header through the proxy. Configure request limits/timeouts on your ingress for internet exposure.

For automatic YouTube-link imports, configure S3 using [IMPORTS.md](IMPORTS.md). The worker uploads video and thumbnail files to a private bucket. Stable `/media/*` URLs redirect to fresh signed S3 URLs. Bypass CDN caching for those redirects.

Existing manually supplied media URLs are still supported. The server does not refresh presigned URLs entered manually, so use stable delivery URLs for those entries. S3 credentials stay on the backend; they never go into the APK or source repository.

Use `video/mp4` and byte-range support for MP4 delivery. The backend is a metadata API, not a video streaming proxy. The catalog and media links are public to anyone who can reach `/videos.json`; there is no per-family account/access system in this first version.

## Manage the video list

Set `HAREER_ADMIN_TOKEN` locally from your secret manager. Do not paste the real token into a committed command or file.

Create `video.json`:

```json
{
  "title": "My favourite story",
  "imageUrl": "https://your-media.example/images/story.jpg",
  "videoUrl": "https://your-media.example/videos/story.mp4"
}
```

Add a video:

```sh
curl --fail-with-body https://tv.nawaa.app/api/admin/videos \
  -H "Authorization: Bearer $HAREER_ADMIN_TOKEN" \
  -H 'Content-Type: application/json' \
  --data-binary @video.json
```

List entries with their IDs:

```sh
curl --fail-with-body https://tv.nawaa.app/api/admin/videos \
  -H "Authorization: Bearer $HAREER_ADMIN_TOKEN"
```

Update video 1 with the same JSON format:

```sh
curl --fail-with-body -X PUT https://tv.nawaa.app/api/admin/videos/1 \
  -H "Authorization: Bearer $HAREER_ADMIN_TOKEN" \
  -H 'Content-Type: application/json' \
  --data-binary @video.json
```

Remove video 1:

```sh
curl --fail-with-body -X DELETE https://tv.nawaa.app/api/admin/videos/1 \
  -H "Authorization: Bearer $HAREER_ADMIN_TOKEN"
```

Every added entry is immediately in the public catalog; there is no separate approval state. A link-import page is available at `/admin`. Entries appear in insertion order. Up to 300 entries are accepted. Removing an entry does not stop playback already underway or revoke its S3 URL.

## Verify and maintain

```sh
curl --fail https://tv.nawaa.app/healthz
curl --fail https://tv.nawaa.app/videos.json
curl --fail -o hareer-tv-1.0.0.apk https://tv.nawaa.app/downloads/hareer-tv-1.0.0.apk
curl --fail -O https://tv.nawaa.app/downloads/SHA256SUMS.txt
sha256sum -c SHA256SUMS.txt
```

On macOS, use `shasum -a 256 -c SHA256SUMS.txt`. Open the page on a phone and computer, check the download, then test the APK on the actual TV. Sideloading instructions are on the landing page.

Back up the SQLite database using SQLite's backup API or a consistent volume backup. Keep the PVC through deployments; do not delete the namespace/PVC during normal upgrades. Rotate the administrator token through the Kubernetes Secret and restart the deployment to load the new value. Back up media separately using your storage provider's tools.
