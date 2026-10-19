"""Server-local metadata verification. No local-device credential transfer."""
import hashlib
import http.client
import json
from pathlib import Path
import socket
import sqlite3
import ssl
import subprocess
import sys
import time

sys.path.insert(0,'/opt/shotcrypto')
from cryptog.evolution import MODULES, push_policy

pid=subprocess.check_output(['systemctl','show','shotcrypto.service','-p','MainPID','--value'],text=True).strip()
env=dict(item.split('=',1) for item in Path('/proc/'+pid+'/environ').read_text().split('\0') if '=' in item)
flags={k:env.get(k,'UNSET') for k in ['CRYPTOG_ENABLE_BASELINE_ALERTS','CRYPTOG_ENABLE_EXIT_ALERTS','CRYPTOG_ENABLE_WAVE_RESEARCH']}
db=sqlite3.connect('file:/opt/shotcrypto/model_library/research.sqlite3?mode=ro',uri=True)
registered=dict(db.execute('SELECT module,stage FROM release_modules ORDER BY module'))
modules=[dict(module=m,stage=registered.get(m,'RESEARCH'),registered=m in registered,
              **{k:v for k,v in push_policy(registered.get(m,'RESEARCH'),m).items() if k not in ['module','stage']})
         for m in MODULES]
db.close()
db=sqlite3.connect('file:/opt/shotcrypto/model_library/monitor-v1.sqlite3?mode=ro',uri=True)
samples=[]
for _ in range(5):
    at=db.execute("SELECT at_ms FROM events WHERE kind='EVALUATION' ORDER BY rowid DESC LIMIT 1").fetchone()[0]
    now=int(time.time()*1000);samples.append(dict(atMs=now,evaluationAtMs=at,ageMs=now-at))
    time.sleep(2)
db.close()
assert all(0<=s['ageMs']<=10000 for s in samples),'Runtime evaluations are stale'
assert samples[-1]['evaluationAtMs']>samples[0]['evaluationAtMs'],'No new runtime evaluation'
class LocalHTTPS(http.client.HTTPSConnection):
    def connect(self):
        self.sock=self._context.wrap_socket(socket.create_connection(('127.0.0.1',8788),timeout=8),server_hostname='43.163.203.127')
c=LocalHTTPS('43.163.203.127',8788,context=ssl.create_default_context(),timeout=8)
c.request('GET','/model-library/market-state');r=c.getresponse();status=r.status;r.read();c.close()
assert status==401
report=dict(atMs=int(time.time()*1000),service=subprocess.check_output(['systemctl','is-active','shotcrypto.service'],text=True).strip(),
    trustedServerTLS=True,unauthenticatedStatus=status,authenticatedEndpointVerified=False,
    flags=flags,modules=modules,qualifiedTradeModules=[m['module'] for m in modules if m['tier']=='TRADE'],
    freshEvaluationSamples=samples,hashes={n:hashlib.sha256((Path('/opt/shotcrypto')/n).read_bytes()).hexdigest()
    for n in ['cryptog/runtime.py','cryptog/wave_integration.py']})
Path('/tmp/wave-v158-system.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps(report,ensure_ascii=True))
