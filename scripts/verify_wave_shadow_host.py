import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import time

root=Path('/opt/shotcrypto/wave-shadow-d002')
data=Path('/opt/shotcrypto/wave-shadow-data-d002')
samples=[]
for _ in range(5):
    now=int(time.time()*1000)
    status=json.loads((data/'status.json').read_text())
    samples.append(dict(atMs=now,heartbeatAgeMs=now-status['heartbeatMs'],
        quotes=status['quotes'],status=status['status'],latestQuote=status['latestQuote'],
        issues=status['issues'],lastIssue=status['lastIssue']))
    time.sleep(3)
db=sqlite3.connect((data/'shadow.sqlite3').as_uri()+'?mode=ro',uri=True)
bar=db.execute('SELECT count(*),min(time),max(time) FROM bars').fetchone()
gaps=db.execute('SELECT count(*) FROM (SELECT time,lead(time) OVER(ORDER BY time) AS next FROM bars) WHERE next-time!=60000').fetchone()[0]
db.close()
manifest=json.loads((root/'deployment-manifest.json').read_text())
hashes_ok=all(hashlib.sha256((root/name).read_bytes()).hexdigest()==digest for name,digest in manifest['files'].items())
services={name:subprocess.check_output(['systemctl','is-active',name],text=True).strip() for name in ['shotcrypto.service','cryptog-wave-shadow.service']}
enabled=subprocess.check_output(['systemctl','is-enabled','cryptog-wave-shadow.service'],text=True).strip()
report=dict(services=services,enabled=enabled,sourceHashesVerified=hashes_ok,barCoverage=bar,minuteGaps=gaps,
    samples=samples,finalStatus=status,newTradeTierEnabled=False,newWavePushesSent=0,
    rollback='sudo systemctl disable --now cryptog-wave-shadow.service')
report['passed']=bool(hashes_ok and gaps==0 and all(v=='active' for v in services.values())
    and enabled=='enabled' and samples[-1]['quotes']>samples[0]['quotes']
    and all(0<=s['heartbeatAgeMs']<20000 and s['latestQuote']['healthy'] for s in samples)
    and status['status'] in ['WARMUP_BEFORE_UNSEEN_WINDOW','COLLECTING_PROSPECTIVE_SHADOW'])
print(json.dumps(report))
Path('/tmp/wave-shadow-acceptance.json').write_text(json.dumps(report,indent=2))
raise SystemExit(0 if report['passed'] else 1)
