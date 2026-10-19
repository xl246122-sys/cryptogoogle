"""Explicit owner credential rotation; no secret in stdout or logs."""
import datetime, hashlib, json, os, pwd, secrets, shutil
from pathlib import Path

registry=Path('/etc/shotcrypto/devices.json')
output=Path('/home/ubuntu/cryptog-owner-rebind-20261018.json')
assert not output.exists(), 'Already generated; retrieve existing file instead'
data=json.loads(registry.read_text())
assert 'owner-phone' in data
stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
backup=registry.with_name('devices.pre-owner-rebind-'+stamp+'.json')
shutil.copy2(registry,backup);os.chmod(backup,0o600)
token=secrets.token_urlsafe(32)
data['owner-phone']={'sha256':hashlib.sha256(token.encode()).hexdigest(),'write':True}
with output.open('x') as f:
    os.chmod(output,0o600)
    json.dump({'url':'https://43.163.203.127:8788','token':token},f)
    f.flush();os.fsync(f.fileno())
user=pwd.getpwnam('ubuntu');os.chown(output,user.pw_uid,user.pw_gid)
temp=registry.with_suffix('.owner-rebind.new');stat=registry.stat()
with temp.open('x') as f:
    os.chmod(temp,stat.st_mode&0o777);os.chown(temp,stat.st_uid,stat.st_gid)
    json.dump(data,f);f.flush();os.fsync(f.fileno())
os.replace(temp,registry)
print(json.dumps({'rotated':'owner-phone','oldCredentialRevoked':True,'otherDevicesPreserved':True,'restartRequired':False}))
