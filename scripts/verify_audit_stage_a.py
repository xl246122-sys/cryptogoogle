"""Read-only live acceptance; print only diagnostics, never credentials."""
import hashlib
import json
import shutil
import sqlite3
import sys
import time
import zlib
sys.path.insert(0, '/opt/shotcrypto')
from cryptog.engine_v2 import context_issue
from cryptog.evaluation import evaluate
from cryptog.storage import canonical, decode_event

now = int(time.time()*1000)
db = sqlite3.connect('file:/opt/shotcrypto/model_library/monitor-v1.sqlite3?mode=ro', uri=True)
rows = db.execute("SELECT id,at_ms,payload FROM events ORDER BY rowid DESC LIMIT 1200").fetchall()
checked, mismatches, refs = [], [], set()
stored_bytes = legacy_bytes = 0
latest = None
for key, at, raw in rows:
    if not key.startswith('evaluation:'):
        continue
    container = json.loads(zlib.decompress(raw) if isinstance(raw, bytes) else raw)
    if 'input_refs_v1' not in container:
        continue
    event = decode_event(raw, db)
    snap = event['input']
    digest = hashlib.sha256(canonical(snap).encode()).hexdigest()
    if key != 'evaluation:'+digest:
        raise ValueError('Reconstructed input hash mismatch')
    actual = evaluate(snap)
    if canonical(actual) != canonical(event['decision']):
        mismatches.append(at)
    checked.append(at)
    stored_bytes += len(raw)
    legacy_bytes += len(zlib.compress(canonical(event).encode(), 3))
    refs.update(container['input_refs_v1'].values())
    if latest is None:
        ctx = snap.get('context')
        latest = dict(atMs=at, ageMs=now-at, healthy=snap['healthy'], issues=snap['issues'],
                      contextIssue=context_issue(ctx, at),
                      closedTimes={tf: (ctx or {}).get(tf, {}).get('close_time') for tf in ('d1', 'h4', 'h1')},
                      status=event['decision']['status'])
blob_bytes = sum(db.execute('SELECT length(payload) FROM evaluation_inputs WHERE digest=?', (ref,)).fetchone()[0] for ref in refs)
disk = shutil.disk_usage('/opt/shotcrypto')
result = dict(atMs=now, latest=latest, reconstructedInputs=len(checked), replayMismatches=len(mismatches),
              sampleSpanSeconds=(max(checked)-min(checked))/1000 if checked else 0,
              newPayloadBytes=stored_bytes+blob_bytes, oldEquivalentPayloadBytes=legacy_bytes,
              sizeRatio=(stored_bytes+blob_bytes)/legacy_bytes if legacy_bytes else None,
              journalBytes=db.execute('PRAGMA page_count').fetchone()[0]*db.execute('PRAGMA page_size').fetchone()[0],
              diskFreeBytes=disk.free, diskTotalBytes=disk.total,
              deliveryStates=dict(db.execute('SELECT state,count(*) FROM outbox GROUP BY state')))
print(json.dumps(result, ensure_ascii=False, indent=2))
assert latest and latest['ageMs'] < 10000 and latest['healthy'] and latest['contextIssue'] is None
assert not mismatches
