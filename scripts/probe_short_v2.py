"""Read-only live health probe; credentials are never printed."""
import http.client
import json
import socket
import ssl
import time
from pathlib import Path

config=json.loads((Path(__file__).resolve().parents[1]/'.private/Crypto-G V1.13设备配置.json').read_text(encoding='utf-8-sig'))
from urllib.parse import urlparse
address=urlparse(config['url'])
reports=[]
for _ in range(6):
    conn=http.client.HTTPSConnection(address.hostname,address.port or 443,context=ssl.create_default_context(),timeout=15)
    try:
        conn.request('GET','/model-library/market-state',headers={'X-Library-Token':config['token']})
        response=conn.getresponse();data=json.loads(response.read());assert response.status==200
        ai=data.get('aiState') or {};snap=data.get('snapshot') or {}
        reports.append({**{k:data.get(k) for k in ('runtimeHealthy','feedHealthy','aiDeliveryHealthy','aiDeliveryError','aiFastHealthy','aiFastError')},
            'ruleVersion':snap.get('ruleVersion'),'status':snap.get('status'),'reasons':snap.get('reasons'),
            'minNetTp1':ai.get('config',{}).get('minNetTp1'),'aiEnabled':ai.get('config',{}).get('enabled'),'aiError':ai.get('error'),'buyCount':ai.get('buyCount'),'rejectedCount':ai.get('rejectedCount')})
    finally: conn.close()
    time.sleep(2)
(Path(__file__).resolve().parents[1]/'audit/short-v2-live-health.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(reports,ensure_ascii=True))
assert all(r['runtimeHealthy'] and r['feedHealthy'] and r['aiDeliveryHealthy'] and r['aiFastHealthy'] and not r['aiFastError'] and not r['aiDeliveryError'] and r['minNetTp1']==.59 for r in reports)
