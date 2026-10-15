"""One-time owner Samsung credential; preserve existing OPPO binding and secrets."""
import json, os, secrets, hashlib, shutil, datetime
from pathlib import Path
import pwd

registry = Path('/etc/shotcrypto/devices.json')
data = json.loads(registry.read_text())
name = 'owner-samsung-s24plus'
output = Path('/home/ubuntu/cryptog-samsung-device.json')
assert name not in data and not output.exists(), 'Already provisioned; do not rotate'
backup = registry.with_name('devices.pre-samsung-' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '.json')
shutil.copy2(registry, backup)
os.chmod(backup, 0o600)
token = secrets.token_urlsafe(32)
data[name] = {'sha256': hashlib.sha256(token.encode()).hexdigest(), 'write': True}
with output.open('x') as f:
    os.chmod(output, 0o600)
    json.dump({'url':'https://43.163.203.127:8788','token':token}, f)
    f.flush(); os.fsync(f.fileno())
user = pwd.getpwnam('ubuntu')
os.chown(output, user.pw_uid, user.pw_gid)
temp = registry.with_suffix('.samsung.new')
stat = registry.stat()
with temp.open('x') as f:
    os.chmod(temp, stat.st_mode & 0o777)
    os.chown(temp, stat.st_uid, stat.st_gid)
    json.dump(data, f)
    f.flush(); os.fsync(f.fileno())
os.replace(temp, registry)
print(json.dumps({'created':name,'existingCredentialPreserved':True,'phoneBindingPending':True}))
