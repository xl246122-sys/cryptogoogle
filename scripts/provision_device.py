"""Create a revocable single-owner device credential; never print the bearer secret."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets

parser=argparse.ArgumentParser()
parser.add_argument('--devices',required=True,help='Server credential digest file')
parser.add_argument('--device',required=True)
parser.add_argument('--secret-output',required=True,help='Private one-time transfer file')
args=parser.parse_args()
devices=Path(args.devices); output=Path(args.secret_output)
data=json.loads(devices.read_text(encoding='utf-8')) if devices.exists() else {}
if args.device in data: raise SystemExit('Device already exists; revoke/remove it explicitly before replacement')
if output.exists(): raise SystemExit('Refusing to overwrite credential transfer file')
token=secrets.token_urlsafe(32)
data[args.device]={'sha256':hashlib.sha256(token.encode()).hexdigest(),'write':True}
with output.open('x',encoding='utf-8') as handle:
    if os.name!='nt': os.chmod(output,0o600)
    handle.write(token);handle.flush();os.fsync(handle.fileno())
temporary=devices.with_suffix(devices.suffix+'.new')
with temporary.open('x',encoding='utf-8') as handle:
    if os.name!='nt': os.chmod(temporary,0o600)
    json.dump(data,handle,indent=2);handle.flush();os.fsync(handle.fileno())
os.replace(temporary,devices)
print('Device digest saved. Transfer the separate private credential file securely; do not commit it.')
