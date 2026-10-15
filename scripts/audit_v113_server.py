"""Final deployment evidence without exposing credentials or trade rows."""
import hashlib,json,subprocess
from pathlib import Path
base=Path('/opt/shotcrypto')
deployment=json.loads((base/'v113-deployment.json').read_text())
backup=Path(deployment['backup']);manifest=json.loads((base/'manifest.json').read_text())
assert all(hashlib.sha256((base/name).read_bytes()).hexdigest()==digest for name,digest in manifest.items())
assert hashlib.sha256(Path(deployment['backupArchive']).read_bytes()).hexdigest()==deployment['backupArchiveSha256']
preserved={}
for name in ('alerts.jsonl','user_actions.jsonl','outcomes.jsonl'):
    before=(backup/'model_library'/name).read_bytes() if (backup/'model_library'/name).exists() else b''
    after=(base/'model_library'/name).read_bytes() if (base/'model_library'/name).exists() else b''
    preserved[name]=after.startswith(before)
assert all(preserved.values()),'Legacy journal prefix changed'
state=subprocess.check_output(['systemctl','show','shotcrypto.service','-p','ActiveState','-p','SubState','-p','NRestarts'],text=True)
timer=subprocess.check_output(['systemctl','is-enabled','cryptog-cert-renew.timer'],text=True).strip()
cert=subprocess.check_output(['openssl','x509','-in','/etc/shotcrypto/tls/fullchain.pem','-noout','-dates','-issuer'],text=True)
report={'deployment':deployment,'sourceManifestMatches':True,'legacyJournalPrefixesPreserved':preserved,
        'service':state.splitlines(),'certificateRenewTimer':timer,'certificate':cert.splitlines(),
        'fcmDryRunAccepted':True,'phoneDeliveryVerified':False,'publicConnectivityVerified':False,
        'publicConnectivityIssue':'Client TLS attempts did not arrive at host; cloud ingress/network path pending verification'}
(base/'v113-audit.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report))
auth=Path('/etc/shotcrypto/devices.json');devices=json.loads(auth.read_text());devices.pop('release-verifier',None)
temporary=auth.with_suffix('.new');temporary.write_text(json.dumps(devices));temporary.chmod(0o640)
import os,pwd
os.chown(temporary,0,pwd.getpwnam('ubuntu').pw_gid);os.replace(temporary,auth)
Path('/etc/shotcrypto/release-verifier.secret').unlink(missing_ok=True)
print('Temporary release credential revoked; owner device remains configured')
