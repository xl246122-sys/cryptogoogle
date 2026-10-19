import sys
sys.path.insert(0, '/opt/shotcrypto')
from cryptog.storage import decode_event
import sqlite3,json,zlib,datetime
c=sqlite3.connect('file:/opt/shotcrypto/model_library/monitor-v1.sqlite3?mode=ro',uri=True)
t=int(datetime.datetime.fromisoformat('2026-10-15T08:30:00+08:00').timestamp()*1000)
row=c.execute("SELECT payload FROM events WHERE kind='EVALUATION' AND at_ms BETWEEN ? AND ? ORDER BY abs(at_ms-?) LIMIT 1",(t-2000,t+2000,t)).fetchone()
assert row
v=decode_event(row[0], c);open('/tmp/cryptog-0830-research-input.json','w').write(json.dumps(v['input']))
print('Market-only replay input exported')
