"""Apply the reviewed stage-E read-only UI evidence, with source hashes and DB backup."""
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path('/opt/shotcrypto')
PACKAGE = Path('/tmp/cryptog-stage-e-20261018.zip')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


with tempfile.TemporaryDirectory(prefix='cryptog-stage-e-') as temp:
    stage = Path(temp)
    shutil.copytree(ROOT/'cryptog', stage/'cryptog')
    with zipfile.ZipFile(PACKAGE) as package:
        manifest = json.loads(package.read('manifest.json'))
        for name, metadata in manifest.items():
            target = stage/name
            if not target.resolve().is_relative_to(stage) or not name.endswith('.py'):
                raise ValueError('Invalid package path')
            old = ROOT/name
            if metadata['old'] != (sha(old) if old.exists() else None):
                raise ValueError('Server source changed: '+name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(package.read(name))
            if sha(target) != metadata['new']:
                raise ValueError('Package hash mismatch')
        for test in ('test_audit_stage_e.py',):
            (stage/test).write_bytes(package.read(test))
            subprocess.run([sys.executable, str(stage/test)], env=dict(os.environ, PYTHONPATH=str(stage)), check=True)
    sys.path.insert(0, str(stage))
    from cryptog.evaluation import evaluate
    from cryptog.storage import decode_event, canonical
    db = sqlite3.connect('file:/opt/shotcrypto/model_library/monitor-v1.sqlite3?mode=ro', uri=True)
    count = 0
    for (raw,) in db.execute("SELECT payload FROM events WHERE id LIKE 'evaluation:%' ORDER BY rowid DESC LIMIT 120"):
        event = decode_event(raw, db)
        assert canonical(evaluate(event['input'])) == canonical(event['decision']), 'Replay mismatch'
        count += 1
    db.close()
    assert count == 120
    if shutil.disk_usage(ROOT).free < 512*1024*1024:
        raise ValueError('Insufficient backup headroom')
    backup = ROOT/'backups'/('audit-stage-e-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S'))
    backup.mkdir(parents=True, mode=0o700)
    for name in manifest:
        if (ROOT/name).exists():
            (backup/name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT/name, backup/name)
    (backup/'manifest.json').write_text(json.dumps(manifest, indent=2))
    source = sqlite3.connect(str(ROOT/'model_library/research.sqlite3'))
    dest = sqlite3.connect(str(backup/'research.sqlite3'))
    try:
        source.backup(dest)
        assert dest.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
    finally:
        dest.close()
        source.close()
    os.chmod(backup/'research.sqlite3', 0o600)
    subprocess.run(['systemctl', 'stop', 'shotcrypto.service'], check=True)
    try:
        for name in manifest:
            shutil.copy2(stage/name, ROOT/name)
            os.chmod(ROOT/name, 0o644)
        subprocess.run(['systemctl', 'start', 'shotcrypto.service'], check=True)
    except Exception:
        for name in manifest:
            if (backup/name).exists():
                shutil.copy2(backup/name, ROOT/name)
        subprocess.run(['systemctl', 'start', 'shotcrypto.service'], check=True)
        raise
    print(json.dumps(dict(backup=str(backup), parallelReplay=count, mismatches=0,
                         hashes={n:sha(ROOT/n) for n in manifest}, databaseBackupSha256=sha(backup/'research.sqlite3'))))
