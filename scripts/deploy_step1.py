"""One-time guarded promotion for V1.10, run with sudo on the specified server.
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
candidate = Path('/tmp/cryptog-v110-candidate.py')
expected_old = 'fbedc12519bd37df53c2c385ddd8e457e5ba5d08af9d6701c17e84e1c8c7d80c'
expected_new = '5f160bed23e38bc346faad17b3228312a741df48924f44abdbbdda8890909385'
def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
assert os.geteuid() == 0, 'Run through sudo'
assert digest(target) == expected_old, 'Live file changed: stop and review'
assert digest(candidate) == expected_new, 'Candidate hash mismatch'
compile(candidate.read_text(encoding='utf-8'), str(candidate), 'exec')
stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
backup = target.parent / 'backups' / ('scanner_daemon.pre-v110.' + stamp + '.py')
backup.parent.mkdir(exist_ok=True)
assert not backup.exists()
shutil.copy2(target, backup)
metadata = target.stat()
staged = target.with_name('scanner_daemon.v110.new')
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
print('DEPLOYED Crypto-G V1.10', digest(target), 'BACKUP', backup, flush=True)
