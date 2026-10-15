"""Backup legacy event files before any recovery may repair a torn final line."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil

def backup_legacy(directory):
    root=Path(directory)
    sources=sorted([p for p in root.iterdir() if p.is_file() and p.suffix in ('.json','.jsonl')])
    if not sources: return None
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    target=root/'backups'/('pre-stage1-'+stamp)
    target.mkdir(parents=True,exist_ok=False)
    manifest={}
    for source in sources:
        dest=target/source.name
        shutil.copy2(source,dest)
        with dest.open('r+b') as handle: os.fsync(handle.fileno())
        digest=hashlib.sha256(dest.read_bytes()).hexdigest()
        if digest!=hashlib.sha256(source.read_bytes()).hexdigest():
            raise RuntimeError('Legacy files changed during backup; stop other writers before migration')
        manifest[source.name]=digest
    with (target/'manifest.json').open('x',encoding='utf-8') as handle:
        json.dump(manifest,handle,sort_keys=True);handle.flush();os.fsync(handle.fileno())
    return target
