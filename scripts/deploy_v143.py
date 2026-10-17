"""Run on the authorized host after uploading the seven reviewed modules."""
import hashlib
import json
import py_compile
import shutil
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

root=Path('/opt/shotcrypto')
stage=Path('/tmp/cryptog-v143')
names=('observations.py','research.py','ai_engine.py','runtime.py')
for name in names:
    py_compile.compile(str(stage/name),doraise=True)
backup=root/'backups'/('quiet-v143-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S'))
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
        shutil.copy2(stage/name,root/'cryptog'/name)
    subprocess.run(['systemctl','start','shotcrypto.service'],check=True)
except Exception:
    for name in names:
        old=backup/'cryptog'/name
        if old.exists(): shutil.copy2(old,root/'cryptog'/name)
    subprocess.run(['systemctl','start','shotcrypto.service'],check=True)
    raise
print(json.dumps({'backup':str(backup),'sha256':{n:hashlib.sha256((root/'cryptog'/n).read_bytes()).hexdigest() for n in names}}))
