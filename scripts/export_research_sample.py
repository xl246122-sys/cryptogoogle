import sqlite3,json,zlib,datetime
c=sqlite3.connect('file:/opt/shotcrypto/model_library/monitor-v1.sqlite3?mode=ro',uri=True)
t=int(datetime.datetime.fromisoformat('2026-10-15T08:30:00+08:00').timestamp()*1000)
row=c.execute("SELECT payload FROM events WHERE kind='EVALUATION' AND at_ms BETWEEN ? AND ? ORDER BY abs(at_ms-?) LIMIT 1",(t-2000,t+2000,t)).fetchone()
assert row
v=json.loads(zlib.decompress(row[0]));open('/tmp/cryptog-0830-research-input.json','w').write(json.dumps(v['input']))
print('Market-only replay input exported')
