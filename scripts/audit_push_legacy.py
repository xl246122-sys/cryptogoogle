import json,datetime
from pathlib import Path
p=Path('/opt/shotcrypto/model_library/alerts.jsonl')
a=int(datetime.datetime.fromisoformat('2026-10-14T20:00:00+08:00').timestamp()*1000)
rows=[json.loads(l) for l in p.read_text().splitlines() if l.strip()]
times=[r.get('alertedAtMs') for r in rows if isinstance(r.get('alertedAtMs'),(int,float))]
print(json.dumps({'legacyAlertRows':len(rows),'sinceYesterday20h':sum(t>=a for t in times),'latestAlertAtMs':max(times) if times else None,'rowsWithoutTime':len(rows)-len(times)}))
