import sys
sys.path.insert(0, '/opt/shotcrypto')
from cryptog.storage import decode_event
import sqlite3,json,zlib,datetime,collections
c=sqlite3.connect('file:/opt/shotcrypto/model_library/monitor-v1.sqlite3?mode=ro',uri=True)
t=int(datetime.datetime.fromisoformat('2026-10-15T11:43:00+08:00').timestamp()*1000)
r=c.execute("select at_ms,payload from events where kind='EVALUATION' and at_ms between ? and ? order by abs(at_ms-?) limit 1",(t-3000,t+3000,t)).fetchone()
v=decode_event(r[1], c);open('/tmp/1143-input.json','w').write(json.dumps(v['input']))
print(json.dumps({'at':r[0],'decision':v['decision'],'outbox':c.execute('select state,count(*) from outbox group by state').fetchall(),'researchCandidates':c.execute("select count(*) from events where kind='RESEARCH_CANDIDATE'").fetchone()[0]},ensure_ascii=False))
