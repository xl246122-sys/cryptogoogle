"""Read-only counts and time-spaced rejection samples; never prints credentials."""
import collections,json,sqlite3,sys,time,zlib
sys.path.insert(0,'/opt/shotcrypto')
from cryptog.config import MIN_GROSS_TP1,MIN_NET_TP1,TRADE_POLICIES
db=sqlite3.connect('file:/opt/shotcrypto/model_library/monitor-v1.sqlite3?mode=ro',uri=True)
since=int(time.time()*1000)-86400000
report={'grossFloor':MIN_GROSS_TP1,'netFloor':MIN_NET_TP1,'policies':TRADE_POLICIES,
 'events24h':dict(db.execute('SELECT kind,count(*) FROM events WHERE at_ms>=? GROUP BY kind',(since,))),
 'deliveryStates':dict(db.execute('SELECT state,count(*) FROM outbox GROUP BY state')),
 'ai24h':db.execute('SELECT count(*),sum(is_buy) FROM ai_evaluations WHERE at_ms>=?',(since,)).fetchone()}
row=db.execute('SELECT payload FROM strategy_settings WHERE id=1').fetchone()
report['strategySettings']=json.loads(row[0]) if row else 'DEFAULT_ALL_ENABLED'
reasons=collections.Counter(); checks=collections.defaultdict(collections.Counter);sampled=0;last=0
for at,raw in db.execute("SELECT at_ms,payload FROM events WHERE kind='EVALUATION' AND at_ms>=? ORDER BY at_ms",(since,)):
 if at-last<60000:continue
 last=at;sampled+=1
 event=json.loads(zlib.decompress(raw) if isinstance(raw,bytes) else raw)
 decision=event.get('output') or event.get('decision') or {}
 reasons.update(decision.get('reasons',[]))
 for row in decision.get('research',[]):
  checks[row['variant']].update(c['name'] for c in row.get('checks',[]) if not c['passed'])
report.update(sampledMinutes=sampled,rejectionSamples=reasons.most_common(15),researchFailedChecks=dict(checks))
print(json.dumps(report,ensure_ascii=False,indent=2))
