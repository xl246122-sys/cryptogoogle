import importlib.util
import json
from pathlib import Path
import sqlite3
root=Path('/opt/shotcrypto/model_library')
result={'dependencies':{k:bool(importlib.util.find_spec(k)) for k in ['pandas','numpy']}}
for name in ['research.sqlite3','monitor-v1.sqlite3']:
    db=sqlite3.connect((root/name).as_uri()+'?mode=ro',uri=True)
    if name.startswith('research'):
        result['minutes']=db.execute("SELECT count(*),min(open_time),max(open_time) FROM klines WHERE symbol='BTCUSDT' AND interval='1m'").fetchone()
    else:
        result['latestEvaluation']=db.execute("SELECT max(at_ms) FROM events WHERE kind='EVALUATION'").fetchone()[0]
        result['receiptCounts']=db.execute('SELECT kind,count(*) FROM exit_receipts GROUP BY kind').fetchall()
    db.close()
print(json.dumps(result))
