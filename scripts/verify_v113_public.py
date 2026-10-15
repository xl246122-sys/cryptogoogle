"""Public TLS/authorization verification. Never print device credentials."""
import hashlib
import json
from pathlib import Path
import urllib.request
import urllib.error

config=json.loads(Path('.private/Crypto-G V1.13设备配置.json').read_text())
url=config['url']+'/model-library/market-state'
try:
    urllib.request.urlopen(url,timeout=10)
    raise AssertionError('Unauthenticated API allowed')
except urllib.error.HTTPError as error:assert error.code==401
request=urllib.request.Request(url,headers={'X-Library-Token':config['token']})
with urllib.request.urlopen(request,timeout=10) as response:value=json.load(response)
assert value['mode']=='BASELINE' and value['runtimeHealthy'] and value['feedHealthy']
assert value['snapshot']['engineVersion']=='Crypto-G V1.13'
assert value['positionNotifications']=='DEVICE_PUSH_UNVERIFIED'
report={'publicTrustedTLS':True,'unauthenticatedStatus':401,'engineVersion':value['snapshot']['engineVersion'],
        'mode':value['mode'],'runtimeHealthy':value['runtimeHealthy'],'feedHealthy':value['feedHealthy'],
        'notificationHealthy':value['notificationHealthy'],'exitNotificationHealthy':value['exitNotificationHealthy'],
        'exitDelivery':value['exitDelivery'],'deviceBound':value['exitDelivery']['devices']>0,'phoneDeliveryVerified':False}
Path('audit/releases/v113-public-verification.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report))
