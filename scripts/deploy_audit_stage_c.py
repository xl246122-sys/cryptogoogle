"""Run as root on the authorized server after uploading the stage-C package."""
import hashlib
import json
import os
import py_compile
import shutil
import subprocess
import sys
import tempfile
import zipfile
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path('/opt/shotcrypto')
PACKAGE = Path('/tmp/cryptog-stage-c-20261018.zip')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


with tempfile.TemporaryDirectory(prefix='cryptog-stage-c-') as temp:
    stage = Path(temp)
    shutil.copytree(ROOT/'cryptog', stage/'cryptog')
    with zipfile.ZipFile(PACKAGE) as package:
        manifest = json.loads(package.read('manifest.json'))
        for name, metadata in manifest.items():
            target = stage/name
            if target.resolve().is_relative_to(stage) is False or not name.endswith('.py'):
                raise ValueError('Unexpected package path')
            old = ROOT/name
            if metadata['old'] is not None and (not old.exists() or sha(old) != metadata['old']):
                raise ValueError('Server changed since audit: '+name)
            if metadata['old'] is None and old.exists():
                raise ValueError('Unexpected existing destination: '+name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(package.read(name))
            if sha(target) != metadata['new']:
                raise ValueError('Package checksum mismatch')
            py_compile.compile(str(target), doraise=True)
        (stage/'test_audit_stage_c.py').write_bytes(package.read('test_audit_stage_c.py'))
    subprocess.run([sys.executable, str(stage/'test_audit_stage_c.py')],
                   env=dict(os.environ, PYTHONPATH=str(stage)), check=True)
    sys.path.insert(0, str(stage))
    from cryptog.evaluation import evaluate
    from cryptog.storage import decode_event, canonical
    db = sqlite3.connect('file:/opt/shotcrypto/model_library/monitor-v1.sqlite3?mode=ro', uri=True)
    checked = 0
    for (raw,) in db.execute("SELECT payload FROM events WHERE id LIKE 'evaluation:%' ORDER BY rowid DESC LIMIT 120"):
        event = decode_event(raw, db)
        fresh = evaluate(event['input'])
        old = event['decision']
        assert canonical(fresh.get('signal')) == canonical(old.get('signal')), 'Unexpected pre-switch signal difference'
        assert fresh.get('status') == old.get('status'), 'Unexpected pre-switch status difference'
        checked += 1
    db.close()
    assert checked == 120
    print(json.dumps({'parallelReplay':checked,'unexpectedDifferences':0}), flush=True)
    backup = ROOT/'backups'/('audit-stage-c-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S'))
    backup.mkdir(parents=True, mode=0o700)
    # No historical rows are migrated or deleted; new table is additive.
    # Back up executable code rather than duplicating another 7+ GB journal.
    for name in manifest:
        if (ROOT/name).exists():
            (backup/name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT/name, backup/name)
    (backup/'manifest.json').write_text(json.dumps(manifest, indent=2))
    # Small research database: make a consistent SQLite backup and verify it.
    source = sqlite3.connect(str(ROOT/'model_library/research.sqlite3'))
    dest = sqlite3.connect(str(backup/'research.sqlite3'))
    try:
        source.backup(dest)
        assert dest.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
    finally:
        dest.close(); source.close()
    os.chmod(backup/'research.sqlite3', 0o600)
    (backup/'research-backup.json').write_text(json.dumps({'sha256':sha(backup/'research.sqlite3'), 'quickCheck':'ok'}))
    subprocess.run(['systemctl', 'stop', 'shotcrypto.service'], check=True)
    try:
        for name in manifest:
            (ROOT/name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(stage/name, ROOT/name)
            os.chmod(ROOT/name, 0o644)
        subprocess.run(['systemctl', 'start', 'shotcrypto.service'], check=True)
    except Exception:
        for name in manifest:
            if (backup/name).exists():
                shutil.copy2(backup/name, ROOT/name)
        subprocess.run(['systemctl', 'start', 'shotcrypto.service'], check=True)
        raise
    print(json.dumps(dict(backup=str(backup), hashes={name: sha(ROOT/name) for name in manifest})), flush=True)
