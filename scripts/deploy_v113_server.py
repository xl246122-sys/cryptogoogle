"""Guarded V1.13 promotion with stopped-writer backup and automatic code rollback.

Run only after staging and release authorization. Keeps any failed-new-version data
separately on rollback instead of discarding newly received manual fills.
"""
import datetime
import hashlib
import json
import os
from pathlib import Path
import pwd
import shutil
import ssl
import subprocess
import tarfile
import time

assert os.geteuid()==0
base=Path('/opt/shotcrypto');stage=Path('/opt/shotcrypto-stage-v113')
old_digest='5b5917e0a70b82cfe8d4f65215598fedc4b8af25aa852268c2623b241d122e21'
assert hashlib.sha256((base/'scanner_daemon.py').read_bytes()).hexdigest()==old_digest,'Production changed'
manifest=json.loads((stage/'manifest.json').read_text())
for name,digest in manifest.items():assert hashlib.sha256((stage/name).read_bytes()).hexdigest()==digest,name
assert not (base/'cryptog').exists(),'Existing package needs separate migration review'
uid=pwd.getpwnam('ubuntu').pw_uid;gid=pwd.getpwnam('ubuntu').pw_gid
stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
backup=base/'backups'/('pre-v113-'+stamp);backup.mkdir(mode=0o700)
unit=Path('/etc/systemd/system/shotcrypto.service')
def run(*args):subprocess.run(args,check=True,timeout=60)
def write(path,text,mode=0o640,owner=0):
    path.write_text(text);os.chmod(path,mode);os.chown(path,owner,gid)
run('systemctl','stop','shotcrypto-stage-v113.service')
run('systemctl','stop','shotcrypto.service')
try:
    shutil.copy2(unit,backup/'shotcrypto.service')
    shutil.copy2(base/'scanner_daemon.py',backup/'scanner_daemon.py')
    shutil.copytree(base/'model_library',backup/'model_library')
    shutil.copytree(base/'logs',backup/'logs')
    shutil.copy2(base/'serviceAccountKey.json',backup/'serviceAccountKey.json')
    hashes={str(p.relative_to(backup)):hashlib.sha256(p.read_bytes()).hexdigest() for p in backup.rglob('*') if p.is_file()}
    (backup/'manifest.json').write_text(json.dumps(hashes,indent=2))
    for name,digest in hashes.items():assert hashlib.sha256((backup/name).read_bytes()).hexdigest()==digest
    snapshot=backup.with_suffix('.tar.gz')
    with tarfile.open(snapshot,'w:gz') as archive:archive.add(backup,arcname=backup.name)
    os.chmod(snapshot,0o600)
    (backup/'archive.sha256').write_text(hashlib.sha256(snapshot.read_bytes()).hexdigest())
except Exception:
    run('systemctl','start','shotcrypto.service');raise

env='''CRYPTOG_LIBRARY_DIR=/opt/shotcrypto/model_library
CRYPTOG_LOG_DIR=/opt/shotcrypto/logs
CRYPTOG_DEVICE_AUTH_FILE=/etc/shotcrypto/devices.json
CRYPTOG_TLS_CERT=/etc/shotcrypto/tls/fullchain.pem
CRYPTOG_TLS_KEY=/etc/shotcrypto/tls/privkey.pem
CRYPTOG_FCM_KEY_PATH=/opt/shotcrypto/serviceAccountKey.json
CRYPTOG_API_BIND=0.0.0.0
CRYPTOG_API_PORT=8788
CRYPTOG_ALLOWED_ORIGINS=https://localhost,capacitor://localhost
CRYPTOG_ENABLE_BASELINE_ALERTS=1
CRYPTOG_ENABLE_EXIT_ALERTS=1
'''
try:
    shutil.copytree(stage/'cryptog',base/'cryptog')
    for name in ('scanner_daemon.py','requirements.txt','manifest.json'):shutil.copy2(stage/name,base/name)
    for path in [base/'cryptog',*(base/'cryptog').rglob('*'),base/'scanner_daemon.py']:os.chown(path,uid,gid)
    os.chmod(base/'serviceAccountKey.json',0o600);os.chown(base/'serviceAccountKey.json',uid,gid)
    write(Path('/etc/shotcrypto/production.env'),env)
    write(unit,'''[Unit]
Description=Crypto-G V1.13 BTC spot monitoring
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/shotcrypto
EnvironmentFile=/etc/shotcrypto/production.env
ExecStart=/opt/shotcrypto/venv-v113/bin/python /opt/shotcrypto/scanner_daemon.py
Restart=always
RestartSec=5
UMask=0077
NoNewPrivileges=true
StandardOutput=append:/opt/shotcrypto/logs/service.log
StandardError=append:/opt/shotcrypto/logs/service_err.log
[Install]
WantedBy=multi-user.target
''',0o644)
    run('systemctl','daemon-reload');run('systemctl','restart','shotcrypto.service')
    time.sleep(8)
    run('systemctl','is-active','--quiet','shotcrypto.service')
    result=subprocess.run(['python3','/tmp/probe_v113_server.py','8788','40'],capture_output=True,text=True,timeout=55)
    (backup/'promotion-health.json').write_text(result.stdout)
    if result.returncode:raise RuntimeError('Production health probe failed: '+result.stdout+result.stderr)
    print(result.stdout,flush=True)
except Exception:
    run('systemctl','stop','shotcrypto.service')
    if (base/'cryptog').exists():shutil.move(base/'cryptog',backup/'failed-new-package')
    shutil.copytree(base/'model_library',backup/'failed-new-library')
    # V1.12 can read compatible append-only journals; preserve new fills for recovery.
    shutil.copy2(backup/'scanner_daemon.py',base/'scanner_daemon.py')
    shutil.copy2(backup/'shotcrypto.service',unit)
    run('systemctl','daemon-reload');run('systemctl','restart','shotcrypto.service')
    print('ROLLED_BACK_CODE; failed-new-library preserved at',backup,flush=True)
    raise

hook=Path('/usr/local/sbin/cryptog-install-cert')
write(hook,'''#!/usr/bin/python3
import os, shutil, ssl, subprocess
from pathlib import Path
import pwd
root=Path('/etc/shotcrypto/tls');gid=pwd.getpwnam('ubuntu').pw_gid
for name in ('fullchain.pem','privkey.pem'):
    dest=root/(name+'.new')
    shutil.copy2('/etc/letsencrypt/live/43.163.203.127/'+name,dest)
    os.chown(dest,0,gid);os.chmod(dest,0o640)
ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
ctx.load_cert_chain(root/'fullchain.pem.new',root/'privkey.pem.new')
for name in ('fullchain.pem','privkey.pem'):os.replace(root/(name+'.new'),root/name)
subprocess.run(['systemctl','try-restart','shotcrypto.service'],check=True)
''',0o750)
write(Path('/etc/systemd/system/cryptog-cert-renew.service'),'''[Unit]
Description=Renew Crypto-G IP TLS certificate
[Service]
Type=oneshot
ExecStart=/opt/cryptog-certbot/bin/certbot renew --quiet --deploy-hook /usr/local/sbin/cryptog-install-cert
''',0o644)
write(Path('/etc/systemd/system/cryptog-cert-renew.timer'),'''[Unit]
Description=Check Crypto-G TLS renewal twice daily
[Timer]
OnCalendar=*-*-* 00,12:00:00
RandomizedDelaySec=1800
Persistent=true
[Install]
WantedBy=timers.target
''',0o644)
run('systemctl','daemon-reload');run('systemctl','enable','--now','cryptog-cert-renew.timer')
report={'version':'1.13','backup':str(backup),'backupArchive':str(snapshot),'backupArchiveSha256':hashlib.sha256(snapshot.read_bytes()).hexdigest(),
        'oldDaemonSha256':old_digest,'newDaemonSha256':manifest['scanner_daemon.py'],'baselinePushEnabled':True,'exitPushEnabled':True,
        'endpoint':'https://43.163.203.127:8788','androidDeliveryVerified':False}
(base/'v113-deployment.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report),flush=True)
