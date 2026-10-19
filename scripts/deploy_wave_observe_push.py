"""Install only the isolated, authorized Samsung research notification service."""
import hashlib
import json
import os
from pathlib import Path
import pwd
import subprocess
import sys
import time
import zipfile

ROOT=Path('/opt/shotcrypto/wave-observe-push-v1')
PY='/opt/shotcrypto/venv-v113/bin/python'
UNIT='cryptog-wave-observe-push.service'
def run(*args):return subprocess.check_output(args,text=True).strip()
def pid(unit):return run('systemctl','show',unit,'--property=MainPID','--value')
package=Path(sys.argv[1]);expected=sys.argv[2]
assert hashlib.sha256(package.read_bytes()).hexdigest()==expected,'PACKAGE_HASH'
assert not ROOT.exists(),'ALREADY_EXISTS_DO_NOT_OVERWRITE'
before={u:pid(u) for u in ['shotcrypto.service','cryptog-wave-shadow.service']}
with zipfile.ZipFile(package) as z:
    for name in z.namelist():
        assert not Path(name).is_absolute() and '..' not in Path(name).parts,'INVALID_PATH'
    ROOT.mkdir();z.extractall(ROOT)
manifest=json.loads((ROOT/'manifest.json').read_text())
for name,digest in manifest['files'].items():assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest
data=ROOT/'data';data.mkdir();user=pwd.getpwnam('ubuntu');os.chown(data,user.pw_uid,user.pw_gid);data.chmod(0o700)
subprocess.check_call([PY,'-B','-m','unittest','discover','-s',str(ROOT/'tests'),'-p','test_wave_push.py','-v'],cwd=ROOT)
dry=json.loads(run('runuser','-u','ubuntu','--',PY,'-B',str(ROOT/'scripts/run_wave_research_push.py'),'--root',str(ROOT),'--dry-check'))
assert dry['dryRunAccepted'] and dry['actualMessagesSent']==0
unit=f'''[Unit]
Description=Crypto-G private research observations for bound Samsung
After=network-online.target cryptog-wave-shadow.service
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory={ROOT}
ExecStart={PY} -B {ROOT}/scripts/run_wave_research_push.py --root {ROOT}
Restart=on-failure
RestartSec=10
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths={data}
MemoryMax=256M
CPUQuota=25%

[Install]
WantedBy=multi-user.target
'''
unitpath=Path('/etc/systemd/system')/UNIT
assert not unitpath.exists(),'UNIT_ALREADY_EXISTS'
unitpath.write_text(unit)
subprocess.check_call(['systemctl','daemon-reload'])
subprocess.check_call(['systemctl','enable','--now',UNIT])
for _ in range(15):
    time.sleep(1)
    if (data/'status.json').exists():break
status=json.loads((data/'status.json').read_text())
assert status['targetBound'] and status['enabled'] and not status['tradeTierEnabled']
assert run('systemctl','is-active',UNIT)=='active'
after={u:pid(u) for u in before};assert before==after,'EXISTING_SERVICE_PID_CHANGED'
report=dict(packageSha256=expected,dryRun=dry,status=status,service=UNIT,
    existingServicePidsUnchanged=True,existingServicePids=after,
    actualMessagesSentDuringDryCheck=0,mainStrategyChanged=False)
(ROOT/'deployment.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps(report,ensure_ascii=True))
