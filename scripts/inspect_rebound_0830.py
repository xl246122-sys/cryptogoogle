import sqlite3,json,zlib,datetime,collections,sys
sys.path.insert(0,'/opt/shotcrypto')
from cryptog.evaluation import evaluate
from cryptog.strategy import recent_crash_confirmed
p='/opt/shotcrypto/model_library/monitor-v1.sqlite3'
c=sqlite3.connect('file:'+p+'?mode=ro',uri=True)
def ms(t):return int(datetime.datetime.fromisoformat(t+'+08:00').timestamp()*1000)
a,b=ms('2026-10-15T08:25:00'),ms('2026-10-15T08:35:00')
rows=c.execute("SELECT at_ms,payload FROM events WHERE kind='EVALUATION' AND at_ms BETWEEN ? AND ? ORDER BY at_ms",(a,b)).fetchall()
counts=collections.Counter();samples=[]
for at,raw in rows:
 v=json.loads(zlib.decompress(raw) if isinstance(raw,bytes) else raw);d=v['decision'];counts[(d['status'],';'.join(d['reasons']))]+=1
 if not samples or abs(at-ms('2026-10-15T08:30:00'))<abs(samples[0][0]-ms('2026-10-15T08:30:00')):samples=[(at,v)]
report={'evaluations':len(rows),'reasons':[{'status':k[0],'reason':k[1],'count':n} for k,n in counts.items()], 'opportunities':c.execute('select count(*) from opportunities where updated_ms between ? and ?',(a,b)).fetchone()[0],'outbox':c.execute('select state,count(*) from outbox group by state').fetchall()}
if samples:
 at,v=samples[0];s=v['input'];t=s['ticker'];bars=s['series']['5m'];peak=max(x['high'] for x in bars[-12:-4]);low=min(x['low'] for x in bars[-4:]);price=t['price'];h=max(t['high24h'],max(x['high'] for x in s['series']['1m'][-47:]),price)
 report['sample']={'at':at,'price':price,'high24h':t['high24h'],'change24h':t['change24h'],'effectiveDrop':max((h-price)/h*100,abs(min(t['change24h'],0))),'recentHourDrop':(peak-low)/peak*100,'macro':v['decision']['macro'],'replayReasons':evaluate(s)['reasons'],'last1hClose':s['series']['1h'][-1]['close_time']}
print(json.dumps(report,ensure_ascii=False))
