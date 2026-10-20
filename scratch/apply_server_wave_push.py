import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

root = Path('/opt/shotcrypto/wave-observe-push-v1')
py = '/opt/shotcrypto/venv-v113/bin/python'

# 1. Copy files into place
target_wave_push = root / 'scratch/cryptog/wave_push.py'
shutil.copy2('/tmp/wave_push.py', target_wave_push)
os.chmod(target_wave_push, 0o644)

if Path('/opt/shotcrypto/cryptog').exists():
    shutil.copy2('/tmp/wave_push.py', '/opt/shotcrypto/cryptog/wave_push.py')

target_test = root / 'tests/test_wave_push.py'
shutil.copy2('/tmp/test_wave_push.py', target_test)
os.chmod(target_test, 0o644)

# 2. Recalculate manifest.json
manifest_path = root / 'manifest.json'
manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
for name in list(manifest['files'].keys()):
    p = root / name
    if p.exists():
        manifest['files'][name] = hashlib.sha256(p.read_bytes()).hexdigest()
        print(f"Updated hash for {name}: {manifest['files'][name]}")
    else:
        print(f"Warning: {name} not found")

manifest_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
print("Updated manifest.json successfully.")

# 3. Run unit tests
print("Running unit tests on server...")
subprocess.check_call([py, '-B', '-m', 'unittest', 'discover', '-s', str(root/'tests'), '-p', 'test_wave_push.py', '-v'], cwd=root)
print("Unit tests PASSED!")

# 4. Dry check
print("Running dry check...")
res = subprocess.check_output([py, '-B', str(root/'scripts/run_wave_research_push.py'), '--root', str(root), '--dry-check'], text=True)
print("Dry check output:", res.strip())

# 5. Restart service
print("Restarting cryptog-wave-observe-push.service...")
subprocess.check_call(['systemctl', 'restart', 'cryptog-wave-observe-push.service'])
time_status = subprocess.check_output(['systemctl', 'status', 'cryptog-wave-observe-push.service', '--no-pager'], text=True)
print("Service status:\n", time_status)
