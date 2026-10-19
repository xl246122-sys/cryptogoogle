"""Build a credential-free, hash-pinned private research sender deployment."""
import hashlib
import json
from pathlib import Path
import sys
import zipfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests'))
from test_wave_push import source,quote,NOW
from cryptog.wave_push import payload_from_event,recheck,transport_fields
fixtures=[]
for phase in ['DOWN_START','SELL_EXHAUSTION','REBOUND_CONFIRMED','INVALIDATED']:
    d,c=payload_from_event(source(phase=phase),NOW,NOW,NOW)
    fixtures.append(transport_fields(recheck(d,c,quote(),NOW))[2])
(ROOT/'tests/fixtures/wave_push_contract.json').write_text(json.dumps(fixtures,ensure_ascii=False,indent=2),encoding='utf-8')
out=ROOT/'audit/wave-observe-push-20261018';out.mkdir(parents=True,exist_ok=True)
names=['scripts/run_wave_research_push.py','scratch/cryptog/__init__.py','scratch/cryptog/wave_push.py',
       'scratch/cryptog/wave_integration.py','tests/test_wave_push.py']
files={n:(ROOT/n).read_bytes() for n in names}
config=dict(enabled=True,shadowDatabase='/opt/shotcrypto/wave-shadow-data-d002/shadow.sqlite3',
    monitorDatabase='/opt/shotcrypto/model_library/monitor-v1.sqlite3',deviceRegistry='/etc/shotcrypto/devices.json',
    firebaseCertificate='/opt/shotcrypto/serviceAccountKey.json')
manifest=dict(files={n:hashlib.sha256(b).hexdigest() for n,b in files.items()})
files['config.json']=json.dumps(config,indent=2).encode()
files['manifest.json']=json.dumps(manifest,indent=2).encode()
package=out/'wave-observe-push-v1.zip'
with zipfile.ZipFile(package,'w',zipfile.ZIP_DEFLATED) as z:
    for n,b in files.items():z.writestr(n,b)
digest=hashlib.sha256(package.read_bytes()).hexdigest()
(out/'package.json').write_text(json.dumps(dict(sha256=digest,manifest=manifest,config=config),indent=2))
print(digest)
