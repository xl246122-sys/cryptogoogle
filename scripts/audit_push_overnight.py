import sqlite3,json,datetime,subprocess,collections,zlib
from pathlib import Path
p=Path('/opt/shotcrypto/model_library');c=sqlite3.connect('file:'+str(p/'monitor-v1.sqlite3')+'?mode=ro',uri=True)
a=int(datetime.datetime.fromisoformat('2026-10-14T20:00:00+08:00').timestamp()*1000)
rows=c.execute("select min(at_ms),max(at_ms),count(*) from events where kind='EVALUATION' and at_ms>=?",(a,)).fetchone()
report={'evaluationRange':rows,'opportunities':c.execute('select count(*) from opportunities').fetchone()[0],'outbox':c.execute('select state,count(*) from outbox group by state').fetchall(),'deviceCount':c.execute('select count(*) from exit_devices').fetchone()[0], 'exitOutbox':c.execute('select state,count(*) from exit_outbox group by state').fetchall(),'legacyFiles':[x.name for x in p.iterdir() if x.suffix in ('.json','.jsonl')]}
raw=subprocess.check_output(['journalctl','-u','shotcrypto.service','--since','2026-10-14 12:00:00 UTC','--no-pager','-o','cat'],text=True)
report['journalCounts']={k:raw.count(k) for k in ['FCM PUSH BROADCAST SUCCESS','FCM broadcast failed','Firebase Admin SDK initialized','Failed to initialize Firebase','Traceback']}
print(json.dumps(report))
