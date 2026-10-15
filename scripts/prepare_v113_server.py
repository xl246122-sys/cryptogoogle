"""Root-only staging preparation. Does not stop or replace production V1.12."""
import hashlib
import json
import os
from pathlib import Path
import pwd
import secrets
import shutil
import subprocess
import tarfile

assert os.geteuid()==0
uid=pwd.getpwnam('ubuntu').pw_uid;gid=pwd.getpwnam('ubuntu').pw_gid
stage=Path('/opt/shotcrypto-stage-v113')
assert not stage.exists(), 'Staging exists; inspect before retry'
stage.mkdir(mode=0o750)
with tarfile.open('/tmp/cryptog-v113.tar.gz') as archive:archive.extractall(stage,filter='data')
manifest=json.loads((stage/'manifest.json').read_text())
for name,digest in manifest.items():assert hashlib.sha256((stage/name).read_bytes()).hexdigest()==digest,name
config=Path('/etc/shotcrypto');config.mkdir(mode=0o750,exist_ok=True);os.chown(config,0,gid)
def write(path,text,mode=0o640):
    path.write_text(text);os.chmod(path,mode);os.chown(path,0,gid)
auth=config/'devices.json'
assert not auth.exists(),'Do not overwrite existing credentials'
owner=secrets.token_urlsafe(32);verifier=secrets.token_urlsafe(32)
write(auth,json.dumps({name:{'sha256':hashlib.sha256(token.encode()).hexdigest(),'write':True} for name,token in [('owner-phone',owner),('release-verifier',verifier)]}))
write(config/'release-verifier.secret',verifier)
transfer=Path('/home/ubuntu/cryptog-v113-device.json')
write(transfer,json.dumps({'url':'https://43.163.203.127:8788','token':owner}),0o600);os.chown(transfer,uid,gid)
tls=config/'tls';tls.mkdir(mode=0o750,exist_ok=True);os.chown(tls,0,gid)
for name in ('fullchain.pem','privkey.pem'):
    shutil.copy2('/etc/letsencrypt/live/43.163.203.127/'+name,tls/name)
    os.chmod(tls/name,0o640);os.chown(tls/name,0,gid)
shutil.copytree('/opt/shotcrypto/model_library',stage/'model_library')
shutil.copytree('/opt/shotcrypto/logs',stage/'logs')
for path in [stage,*stage.rglob('*')]:os.chown(path,uid,gid)
venv=Path('/opt/shotcrypto/venv-v113')
assert not venv.exists(),'New dependency environment already exists'
subprocess.run(['python3','-m','venv',str(venv)],check=True)
subprocess.run([str(venv/'bin/pip'),'install','--index-url','https://pypi.org/simple','--progress-bar','off','requests==2.34.2','websocket-client==1.9.0','firebase-admin==7.7.0'],check=True)
env='''CRYPTOG_LIBRARY_DIR=/opt/shotcrypto-stage-v113/model_library
CRYPTOG_LOG_DIR=/opt/shotcrypto-stage-v113/logs
CRYPTOG_DEVICE_AUTH_FILE=/etc/shotcrypto/devices.json
CRYPTOG_TLS_CERT=/etc/shotcrypto/tls/fullchain.pem
CRYPTOG_TLS_KEY=/etc/shotcrypto/tls/privkey.pem
CRYPTOG_FCM_KEY_PATH=/nonexistent-shadow-fcm.json
CRYPTOG_API_BIND=127.0.0.1
CRYPTOG_API_PORT=18788
CRYPTOG_ENABLE_BASELINE_ALERTS=0
CRYPTOG_ENABLE_EXIT_ALERTS=0
'''
write(config/'stage-v113.env',env)
unit='''[Unit]
Description=Crypto-G V1.13 isolated preflight
After=network-online.target
[Service]
User=ubuntu
WorkingDirectory=/opt/shotcrypto-stage-v113
EnvironmentFile=/etc/shotcrypto/stage-v113.env
ExecStart=/opt/shotcrypto/venv-v113/bin/python /opt/shotcrypto-stage-v113/scanner_daemon.py
Restart=on-failure
RestartSec=5
UMask=0077
'''
Path('/etc/systemd/system/shotcrypto-stage-v113.service').write_text(unit)
subprocess.run(['systemctl','daemon-reload'],check=True)
subprocess.run(['systemctl','start','shotcrypto-stage-v113.service'],check=True)
print('STAGING_STARTED; production unchanged; device transfer file created without printing credentials')
