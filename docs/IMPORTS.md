# Import YouTube links into Hareer TV

The backend now accepts individual YouTube video links, queues them in SQLite, and processes **one video at a time**. It downloads the video, converts it to an Android TV-friendly MP4 (H.264/AAC), creates a JPEG thumbnail, uploads both to a private S3 bucket, and only then publishes the entry in `/videos.json`.

Use only videos you are permitted to download and store. Private, unavailable, restricted, or sign-in-required videos can fail; the worker does not bypass access restrictions or DRM. YouTube can also reject downloads from datacenter IPs. A failed job remains visible with a retry action and does not block the next link.

## Configure the deployment

The existing website and catalog still work without storage configuration. New imports are disabled until all required variables are supplied.

| Variable | Required | Value |
| --- | --- | --- |
| `S3_ENDPOINT_URL` | Yes | HTTPS S3 API endpoint; for R2, `https://ACCOUNT_ID.r2.cloudflarestorage.com` |
| `S3_BUCKET` | Yes | Dedicated bucket for Hareer media |
| `S3_ACCESS_KEY_ID` | Yes | Storage credential, only in the Kubernetes Secret |
| `S3_SECRET_ACCESS_KEY` | Yes | Storage credential, only in the Kubernetes Secret |
| `S3_REGION` | No | `auto` for R2 (default); your region for other S3 providers |
| `PUBLIC_BASE_URL` | Yes | `https://tv.nawaa.app` |
| `ADMIN_TOKEN` | Existing | Your current administrator token; unchanged |

Grant the storage credential object **PutObject** and **GetObject** access for `hareer-tv/imports/*` in this bucket. GetObject permission covers the object-size verification (HEAD) and signed playback URLs. No bucket-management permission or public ACL is required. Large uploads use multipart transfer; allow multipart operations required by your provider and configure a lifecycle rule to expire abandoned multipart uploads.

Create the Secret without committing keys:

```sh
umask 077
mkdir -p .private
cp deploy/storage.env.example .private/storage.env
# Edit .private/storage.env with your real bucket and credentials.
kubectl -n hareer-tv create secret generic hareer-storage \
  --from-env-file=.private/storage.env \
  --dry-run=client -o yaml | kubectl apply -f -
```

In the actual GitOps deployment at `cloudfares-platform@prod:apps/hareer-tv/10-app.yaml`, add this to the app container beside its existing `env`:

```yaml
envFrom:
  - secretRef:
      name: hareer-storage
      optional: true
```

Keep the existing `ADMIN_TOKEN` entry. `deploy/kubernetes.yaml` in this repository is a standalone reference template; the CI workflow updates the image tag in the platform repository, not that reference template.

Keep **one replica**, `Recreate`, and the `/data` PVC. Downloads use `/data/import-work`, so allow at least **4 GiB free** on the volume. The live 10 GiB catalog PVC is suitable if it has that free space. Suggested worker resources are a 250m CPU / 256 MiB request and a 2 CPU / 2 GiB limit; update the actual GitOps manifest's previous 500m / 256 MiB limits for conversion workloads. Temporary work is removed after each job and stale work is cleaned after restart.

After applying the Secret and GitOps environment/resource changes, restart or roll out the deployment. The Docker image includes pinned yt-dlp, its bundled EJS dependency, Node.js, FFmpeg, and boto3. The APK remains the existing locally built release; no Android rebuild is necessary.

## YouTube cookies (required on datacenter IPs)

YouTube refuses downloads from most cloud and datacenter IPs with "Sign in to confirm you're not a bot". Every import then fails with "YouTube could not provide this video". The worker can send cookies from a signed-in YouTube session to get past this.

1. Use a **spare Google account**, not your personal one. YouTube can flag or limit accounts used for automated downloads.
2. In a private/incognito window, sign in to that account on youtube.com, then export cookies for `youtube.com` in Netscape `cookies.txt` format (for example with a "Get cookies.txt LOCALLY" browser extension). Close the private window afterwards without signing out, so the session stays valid.
3. Store the file in the cluster. Never commit it:

```sh
kubectl -n hareer-tv create secret generic hareer-youtube-cookies \
  --from-file=cookies.txt=.private/youtube-cookies.txt \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n hareer-tv rollout restart deployment/hareer-tv
```

The deployment mounts this optional Secret and sets `YTDLP_COOKIES_FILE` to the mounted file. Without the variable or the file, imports run without cookies. Each job copies the cookies into its own temporary directory, because yt-dlp rewrites the file. The Secret itself is never modified.

Cookies expire, typically after a few weeks, or sooner if you sign out of that session. When imports start failing again with the same message, export a fresh `cookies.txt`, re-run the commands above, then use **Retry** on the failed jobs.

## Submit links

Open **https://tv.nawaa.app/admin** and sign in using the existing administrator token. Paste one link per line, then choose **Add to queue**. The token stays only in the browser tab's memory; it is not saved to browser storage.

The page lists `queued`, `downloading`, `uploading`, `completed`, and `failed` jobs and refreshes every five seconds. A failed job can be retried. Adding a duplicate link returns its existing job instead of adding another download.

Or call the protected API:

```sh
curl --fail-with-body https://tv.nawaa.app/api/admin/imports \
  -H "Authorization: Bearer $HAREER_ADMIN_TOKEN" \
  -H 'Content-Type: application/json' \
  --data '{"urls":["https://www.youtube.com/watch?v=VIDEO_ID_HERE"]}'
```

Read status:

```sh
curl --fail-with-body https://tv.nawaa.app/api/admin/imports \
  -H "Authorization: Bearer $HAREER_ADMIN_TOKEN"
```

Retry a failed import:

```sh
curl --fail-with-body -X POST https://tv.nawaa.app/api/admin/imports/1/retry \
  -H "Authorization: Bearer $HAREER_ADMIN_TOKEN"
```

The existing `/api/admin/videos` endpoints still support editing titles and deleting published entries. Deletion hides the video and disables its stable media URLs. It does not delete S3 objects. Retained objects from failed uploads, retries, or removed entries remain for operator-managed cleanup; do not delete keys still used by published videos.

## What the TV receives

The response format is unchanged:

```json
{
  "videos": [
    {
      "title": "Imported title",
      "imageUrl": "https://tv.nawaa.app/media/IMAGE_ID",
      "videoUrl": "https://tv.nawaa.app/media/VIDEO_ID"
    }
  ]
}
```

The media route checks that the object still belongs to a published video, then redirects to a fresh S3 URL valid for 15 minutes. This keeps the bucket private and avoids stale signed URLs in SQLite. The player streams from S3, not from the Python API. A previously issued signed URL can remain usable until it expires; deleting the catalog entry cannot revoke bytes already buffered. Very long playback sessions may need reopening the video after a signed URL expires.

Cloudflare must **bypass caching** for `/videos.json`, `/api/*`, `/admin*`, and `/media/*`. The media redirect and API send `Cache-Control: no-store`. Do not apply an interactive Cloudflare challenge to catalog or media routes used by the TV.

The catalog remains public to people who can access its URL. This is a single-family catalog, not a multi-user account system. Importing a link publishes it automatically after successful processing; there is no separate approval step.

## Limits and recovery

- 1–50 links per request; individual YouTube watch, short, embed, or youtu.be links only. A playlist parameter on a watch link is stripped; playlists/channels are never expanded.
- Up to 200 outstanding jobs and 300 published videos.
- Recorded videos up to 60 minutes, selected at up to 720p; each source/output is limited to 1 GiB.
- Scratch usage is monitored with a 3 GiB limit; downloads time out after 30 minutes and conversion after 60 minutes.
- A filesystem lock on the shared PVC prevents two worker processes from running imports simultaneously. Jobs interrupted by a restart are requeued and use deterministic object keys on retry.
- The public catalog is updated atomically after both uploads are confirmed. Partial uploads never create a visible catalog entry.

For YouTube extractor changes, update the pinned yt-dlp dependency, rerun the tests, and deploy the server. No APK rebuild is needed. The extractor cannot guarantee every YouTube video will be downloadable.
