"""Authenticated loopback probe with real certificate hostname verification."""
import http.client
import json
import ssl
import sys
import time
from pathlib import Path

class LoopbackHTTPS(http.client.HTTPSConnection):
    def connect(self):
        import socket
        sock=socket.create_connection(('127.0.0.1',self.port),timeout=5)
        self.sock=self._context.wrap_socket(sock,server_hostname='43.163.203.127')

port=int(sys.argv[1]) if len(sys.argv)>1 else 18788
seconds=int(sys.argv[2]) if len(sys.argv)>2 else 45
token=Path('/etc/shotcrypto/release-verifier.secret').read_text()
healthy=0;last=None;seen={};started=time.monotonic()
while time.monotonic()-started<seconds:
    conn=LoopbackHTTPS('43.163.203.127',port,context=ssl.create_default_context())
    try:
        conn.request('GET','/model-library/market-state',headers={'X-Library-Token':token})
        response=conn.getresponse();value=json.loads(response.read())
        assert response.status==200
        snapshot=value.get('snapshot') or {}
        last={'mode':value.get('mode'),'runtimeHealthy':value.get('runtimeHealthy'),'feedHealthy':value.get('feedHealthy'),
              'notificationHealthy':value.get('notificationHealthy'),'exitNotificationHealthy':value.get('exitNotificationHealthy'),
              'engineVersion':snapshot.get('engineVersion'),'status':snapshot.get('status'),'reasons':snapshot.get('reasons'),
              'feedError':value.get('feedError'),'positions':len(value.get('positions',[])),
              'positionNotifications':value.get('positionNotifications'),'exitDelivery':value.get('exitDelivery')}
        okay=value.get('runtimeHealthy') and value.get('feedHealthy') and snapshot.get('engineVersion')=='Crypto-G V1.13' and snapshot.get('status')!='BLOCK_ENTRY'
        if okay:healthy+=1
        for reason in snapshot.get('reasons',[]):seen[reason]=seen.get(reason,0)+1
    finally:conn.close()
    time.sleep(2)
report={'healthySamples':healthy,'observedSeconds':round(time.monotonic()-started,1),'latest':last,'reasonCounts':seen}
Path('/tmp/cryptog-probe-'+str(port)+'.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps(report,ensure_ascii=False))
if healthy<5:raise SystemExit('Insufficient healthy live samples')
