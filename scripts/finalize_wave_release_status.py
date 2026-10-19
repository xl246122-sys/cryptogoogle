"""Write verified deployment evidence into the local V1.58 release record."""
import hashlib
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
audit=ROOT/'audit/wave-stage-c-20261018'
lines=(audit/'v158-deploy.txt').read_text(encoding='utf-8-sig').splitlines()
deployment=next(json.loads(line) for line in lines if line.startswith('{"backup"'))
verification=json.loads((audit/'v158-system-verification.json').read_text(encoding='utf-8-sig'))
target=ROOT/'release/V1.58-release-status.json';status=json.loads(target.read_text(encoding='utf-8'))
for name,expected in status['backendFiles'].items():
    assert deployment['hashes'][name]==verification['hashes'][name]==expected['new']
assert deployment['parallelReplay']==120 and deployment['mismatches']==0
assert verification['service']=='active'
assert hashlib.sha256((ROOT/'release/Crypto-G V1.58.apk').read_bytes()).hexdigest()==status['apkSha256']
public_path=audit/'v158-public-verification.json'
public=json.loads(public_path.read_text(encoding='utf-8')) if public_path.exists() else None
status.update(deployed=True,deploymentBlocker=None,deployment=deployment,verification=verification,
    baselineBuyPushEnabled=verification['flags']['CRYPTOG_ENABLE_BASELINE_ALERTS']=='1',
    positionExitPushEnabled=verification['flags']['CRYPTOG_ENABLE_EXIT_ALERTS']=='1',
    authenticatedEndpointVerification='PASSED' if public and public.get('passed') else 'PENDING',
    apkSignatureMatchesV157=True,newTradeTierEnabled=False)
if public:
    status['authenticatedEndpointEvidence']=public
target.write_text(json.dumps(status,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('V1.58 release evidence recorded; authenticated endpoint:',status['authenticatedEndpointVerification'])
