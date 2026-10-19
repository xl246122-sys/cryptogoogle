"""Read-only V1.58 live acceptance; reports no tokens, bindings or fill details."""
import hashlib
import http.client
import json
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import time

class LoopbackHTTPS(http.client.HTTPSConnection):
    def connect(self):
        sock=socket.create_connection(('127.0.0.1',8788),timeout=8)
        self.sock=self._context.wrap_socket(sock,server_hostname='43.163.203.127')

phase=sys.argv[1] if len(sys.argv)>1 else 'after'
token=json.load(sys.stdin)['token']
def fetch(auth=True):
    c=LoopbackHTTPS('43.163.203.127',8788,context=ssl.create_default_context(),timeout=8)
    try:
        c.request('GET','/model-library/market-state',headers={'X-Library-Token':token} if auth else {})
        r=c.getresponse();body=r.read()
        return r.status,json.loads(body)
    finally:c.close()

status,_=fetch(False)
assert status==401,'Endpoint must require authentication'
samples=[];last=None
for attempt in range(20):
    status,last=fetch()
    assert status==200,'Authenticated endpoint rejected'
    now=int(time.time()*1000);snapshot=last.get('snapshot') or {}
    good=bool(last.get('ok') and last.get('runtimeHealthy') and last.get('feedHealthy')
        and last.get('notificationHealthy') and last.get('exitNotificationHealthy')
        and isinstance(snapshot.get('atMs'),(int,float)) and 0<=now-snapshot['atMs']<=10000)
    samples.append(dict(atMs=now,healthy=good,snapshotAgeMs=now-snapshot.get('atMs',0)))
    if len(samples)>=5 and all(s['healthy'] for s in samples[-5:]): break
    time.sleep(2)
assert len(samples)>=5 and all(s['healthy'] for s in samples[-5:]),'Live health did not stabilize'
pid=subprocess.check_output(['systemctl','show','shotcrypto.service','-p','MainPID','--value'],text=True).strip()
process_env=dict(item.split('=',1) for item in Path('/proc/'+pid+'/environ').read_text().split('\0') if '=' in item)
flags={key:process_env.get(key,'UNSET') for key in [
    'CRYPTOG_ENABLE_BASELINE_ALERTS','CRYPTOG_ENABLE_EXIT_ALERTS','CRYPTOG_ENABLE_WAVE_RESEARCH']}
modules=[{k:m.get(k) for k in ['module','stage','tier','tierLabel']} for m in (last.get('evolution') or {}).get('modules',[])]
report=dict(phase=phase,atMs=int(time.time()*1000),trustedTLS=True,unauthenticatedStatus=401,
    service=subprocess.check_output(['systemctl','is-active','shotcrypto.service'],text=True).strip(),
    mode=last.get('mode'),runtimeHealthy=last.get('runtimeHealthy'),feedHealthy=last.get('feedHealthy'),
    notificationHealthy=last.get('notificationHealthy'),exitNotificationHealthy=last.get('exitNotificationHealthy'),
    pushFlags=flags,waveResearch=last.get('waveResearch'),moduleReleaseState=modules,
    qualifiedTradeModules=[m['module'] for m in modules if m['tier']=='TRADE'],samples=samples,
    hashes={name:hashlib.sha256((Path('/opt/shotcrypto')/name).read_bytes()).hexdigest()
            for name in ['cryptog/runtime.py','cryptog/wave_integration.py'] if (Path('/opt/shotcrypto')/name).exists()})
if phase=='after':
    assert report['waveResearch']=={'mode':'DISABLED','tradeEligible':False},'Research must not silently become live'
Path('/tmp/wave-v158-'+phase+'.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps(report,ensure_ascii=True))
