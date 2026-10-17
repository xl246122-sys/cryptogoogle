"""Run on the authorized host after uploading the two reviewed startup modules."""
import hashlib
import json
import py_compile
import shutil
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

root=Path('/opt/shotcrypto')
stage=Path('/tmp/cryptog-v145')
names=('runtime.py','scanner_daemon.py')
def destination(name): return root/name if name == 'scanner_daemon.py' else root/'cryptog'/name
for name in names:
    py_compile.compile(str(stage/name),doraise=True)
backup=root/'backups'/('startup-v145-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S'))
backup.mkdir(parents=True)
shutil.copytree(root/'cryptog',backup/'cryptog')
shutil.copy2(root/'scanner_daemon.py',backup/'scanner_daemon.py')
db=root/'model_library/monitor-v1.sqlite3'
with sqlite3.connect(str(db)) as source,sqlite3.connect(str(backup/db.name)) as target:
    source.backup(target)
shutil.copy2(db.with_suffix('.ai-key'),backup/'monitor-v1.ai-key')
(backup/'monitor-v1.ai-key').chmod(0o600)
subprocess.run(['systemctl','stop','shotcrypto.service'],check=True)
try:
    for name in names:
        shutil.copy2(stage/name,destination(name))
    subprocess.run(['systemctl','start','shotcrypto.service'],check=True)
except Exception:
    for name in names:
        old=backup/name if name == 'scanner_daemon.py' else backup/'cryptog'/name
        if old.exists(): shutil.copy2(old,destination(name))
    subprocess.run(['systemctl','start','shotcrypto.service'],check=True)
    raise
print(json.dumps({'backup':str(backup),'sha256':{n:hashlib.sha256(destination(n).read_bytes()).hexdigest() for n in names}}))
