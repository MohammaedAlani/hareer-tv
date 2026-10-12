#!/usr/bin/env python3
"""Build/sign locally. Signing material stays outside the repository."""
import argparse, hashlib, json, os, pathlib, secrets, shutil, subprocess

parser = argparse.ArgumentParser()
parser.add_argument('--catalog-url', default='https://tv.nawaa.app/videos.json')
parser.add_argument('--update-url', default='https://tv.nawaa.app/downloads/update.json')
args = parser.parse_args()
if not args.catalog_url.startswith('https://') or not args.update_url.startswith('https://'):
    parser.error('Release catalog and update URLs must use HTTPS')
root = pathlib.Path(__file__).resolve().parents[1]
signing = pathlib.Path(os.environ.get('HAREER_SIGNING_DIR', pathlib.Path.home()/'.local/share/hareer-tv/signing'))
signing.mkdir(parents=True, exist_ok=True, mode=0o700)
credentials = signing/'credentials.json'
keystore = signing/'hareer-tv.jks'
java_home = os.environ.get('JAVA_HOME')
keytool = str(pathlib.Path(java_home)/'bin/keytool') if java_home else 'keytool'
env = os.environ.copy()
if credentials.exists():
    values = json.loads(credentials.read_text())
    if not keystore.exists():
        raise SystemExit('Existing signing credentials have no keystore. Restore the original key; do not replace it.')
else:
    if keystore.exists():
        raise SystemExit('Keystore exists without credentials. Restore credentials; do not replace the key.')
    values = {'store_password': secrets.token_urlsafe(40), 'key_password': secrets.token_urlsafe(40), 'alias': 'hareer-tv'}
    env.update(HAREER_STORE_PASSWORD=values['store_password'], HAREER_KEY_PASSWORD=values['key_password'])
    old_umask = os.umask(0o077)
    try:
        subprocess.run([keytool,'-genkeypair','-keystore',str(keystore),'-storetype','JKS',
            '-alias',values['alias'],'-keyalg','RSA','-keysize','3072','-validity','10000',
            '-dname','CN=Hareer TV, O=Hareer TV','-storepass:env','HAREER_STORE_PASSWORD',
            '-keypass:env','HAREER_KEY_PASSWORD'],env=env,check=True)
        credentials.write_text(json.dumps(values))
    finally:
        os.umask(old_umask)
env.update(HAREER_STORE_FILE=str(keystore),HAREER_STORE_PASSWORD=values['store_password'],
           HAREER_KEY_PASSWORD=values['key_password'],HAREER_KEY_ALIAS=values['alias'])
subprocess.run([str(root/'gradlew'),':app:testDebugUnitTest',':app:lintRelease',':app:assembleRelease',
               '-PcatalogUrl='+args.catalog_url,'-PupdateUrl='+args.update_url,'--console','plain'],cwd=root,env=env,check=True)
metadata=json.loads((root/'app/build/outputs/apk/release/output-metadata.json').read_text())
version=metadata['elements'][0]['versionName']
output=root/'dist'; output.mkdir(exist_ok=True)
name='hareer-tv-'+version+'.apk'
shutil.copyfile(root/'app/build/outputs/apk/release'/metadata['elements'][0]['outputFile'],output/name)
digest=hashlib.sha256((output/name).read_bytes()).hexdigest()
(output/'SHA256SUMS.txt').write_text(digest+'  '+name+'\n')
(output/'apk.json').write_text(json.dumps({'version': version, 'versionCode': metadata['elements'][0]['versionCode'], 'filename': name, 'url': 'https://github.com/MohammaedAlani/hareer-tv/releases/download/v'+version+'/'+name, 'sha256': digest}, indent=2)+'\n')
print('Signed APK:',output/name)
print('SHA-256:',digest)
print('Back up the private signing directory securely:',signing)
