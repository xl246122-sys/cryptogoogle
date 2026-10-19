"""Install isolated read-only sidecar. Does not restart shotcrypto.service."""
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

PACKAGE=Path('/tmp/wave-shadow-d002.zip')
EXPECTED='0b0cb5586bb1bb7c441cfca8bdb4810d0d838d9b61067e2b14060e54773f5297'
ROOT=Path('/opt/shotcrypto/wave-shadow-d002')
DATA=Path('/opt/shotcrypto/wave-shadow-data-d002')

def run(*args):
    subprocess.run(args,check=True)

def main():
    assert hashlib.sha256(PACKAGE.read_bytes()).hexdigest()==EXPECTED
    assert not ROOT.exists(),'Refuse overwriting registered implementation'
    ROOT.mkdir()
    with zipfile.ZipFile(PACKAGE) as archive:
        for name in archive.namelist():
            target=(ROOT/name).resolve()
            assert target.is_relative_to(ROOT)
        archive.extractall(ROOT)
    manifest=json.loads((ROOT/'deployment-manifest.json').read_text())
    for name,digest in manifest['files'].items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest
    run('/opt/shotcrypto/venv-v113/bin/python','-m','venv',str(ROOT/'venv'))
    run(str(ROOT/'venv/bin/python'),'-m','pip','install','numpy==2.4.4','pandas==3.0.1')
    run(str(ROOT/'venv/bin/python'),'-m','unittest','discover','-s',str(ROOT/'tests'),'-p','test_wave_shadow.py','-v')
    DATA.mkdir(exist_ok=True)
    run('chown','ubuntu:ubuntu',str(DATA))
    unit=f'''[Unit]
Description=Crypto-G isolated prospective wave shadow evidence
After=shotcrypto.service network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
Group=ubuntu
WorkingDirectory={ROOT}
ExecStart={ROOT}/venv/bin/python -B {ROOT}/scripts/run_wave_shadow.py --library /opt/shotcrypto/model_library --output {DATA} --protocol {ROOT}/protocol.json --seed {ROOT}/seed.csv
Restart=on-failure
RestartSec=15
TimeoutStopSec=30
Environment=PYTHONUNBUFFERED=1
Environment=OPENBLAS_NUM_THREADS=1
Environment=OMP_NUM_THREADS=1
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths={DATA}
MemoryMax=768M
CPUQuota=50%
Nice=10
UMask=0077

[Install]
WantedBy=multi-user.target
'''
    Path('/etc/systemd/system/cryptog-wave-shadow.service').write_text(unit)
    run('systemctl','daemon-reload')
    run('systemctl','enable','--now','cryptog-wave-shadow.service')
    print(json.dumps(dict(installed=True,root=str(ROOT),data=str(DATA),packageSha256=EXPECTED,
        originalServiceRestarted=False,rollback='sudo systemctl disable --now cryptog-wave-shadow.service')))

if __name__=='__main__':main()
