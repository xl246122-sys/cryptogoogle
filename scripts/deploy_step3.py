"""One-time guarded promotion for V1.12, run with sudo on the specified server.
No credentials, package installation or notification test sends.
"""
import datetime
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import time

target = Path('/opt/shotcrypto/scanner_daemon.py')
candidate = Path('/tmp/cryptog-v112-candidate.py')
expected_old = 'e48ab35c24050c65638535ce3ccba0e278c152e507ba0fd177deda1f342ff060'
expected_new = '5b5917e0a70b82cfe8d4f65215598fedc4b8af25aa852268c2623b241d122e21'
def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
assert os.geteuid() == 0, 'Run through sudo'
assert digest(target) == expected_old, 'Live file changed: stop and review'
assert digest(candidate) == expected_new, 'Candidate hash mismatch'
compile(candidate.read_text(encoding='utf-8'), str(candidate), 'exec')
stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
backup = target.parent / 'backups' / ('scanner_daemon.pre-v112.' + stamp + '.py')
backup.parent.mkdir(exist_ok=True)
assert not backup.exists()
shutil.copy2(target, backup)
metadata = target.stat()
staged = target.with_name('scanner_daemon.v112.new')
def install(source):
    shutil.copy2(source, staged)
    os.chown(staged, metadata.st_uid, metadata.st_gid)
    os.chmod(staged, metadata.st_mode & 0o777)
    os.replace(staged, target)
def restart_and_check():
    subprocess.run(['systemctl', 'restart', 'shotcrypto.service'], check=True, timeout=30)
    time.sleep(3)
    subprocess.run(['systemctl', 'is-active', '--quiet', 'shotcrypto.service'], check=True, timeout=10)
try:
    install(candidate)
    restart_and_check()
    assert digest(target) == expected_new
except Exception:
    install(backup)
    restart_and_check()
    print('ROLLED_BACK', backup, flush=True)
    raise
print('DEPLOYED Crypto-G V1.12', digest(target), 'BACKUP', backup, flush=True)
