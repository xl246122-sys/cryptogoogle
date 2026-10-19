import sys
sys.path.insert(0, '/opt/shotcrypto')
from cryptog.storage import decode_event
import sqlite3,json,zlib,datetime,collections
c=sqlite3.connect('file:/opt/shotcrypto/model_library/monitor-v1.sqlite3?mode=ro',uri=True)
a=int(datetime.datetime.fromisoformat('2026-10-15T09:30:00+08:00').timestamp()*1000);b=a+65*60000
counts=collections.Counter();statuses=collections.Counter();samples=[]
for at,raw in c.execute("select at_ms,payload from events where kind='EVALUATION' and at_ms between ? and ? order by at_ms",(a,b)):
 d=decode_event(raw, c)['decision'];statuses[d.get('status')]+=1
 for r in d.get('reasons',[]):counts[r]+=1
 if not samples or at-samples[-1]['at']>=600000:samples.append({'at':at,'decision':d})
print(json.dumps({'statuses':dict(statuses),'topReasons':counts.most_common(12),'samples':samples},ensure_ascii=False))
