#!/usr/bin/env python3
"""Fetch the exact locally built release from GitHub, verifying its checksum."""
import hashlib, json, pathlib, urllib.request
root=pathlib.Path(__file__).resolve().parents[1]
release=json.loads((root/'deploy/apk.json').read_text())
output=root/'site/downloads'; output.mkdir(parents=True,exist_ok=True)
with urllib.request.urlopen(release['url'],timeout=60) as response:
    data=response.read(50*1024*1024+1)
if len(data)>50*1024*1024 or hashlib.sha256(data).hexdigest()!=release['sha256']:
    raise SystemExit('APK checksum mismatch or oversized download')
(output/release['filename']).write_bytes(data)
(output/'update.json').write_text(json.dumps(release)+'\n')
(output/'SHA256SUMS.txt').write_text(release['sha256']+'  '+release['filename']+'\n')
print('Verified release APK:',release['filename'])
