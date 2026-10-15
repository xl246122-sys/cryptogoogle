"""Apply the tested final V1.13 TLS listener change with hash guard/rollback."""
import hashlib,json,os,pwd,shutil,subprocess,sys,time
from pathlib import Path
base=Path('/opt/shotcrypto');candidate=Path('/tmp/scanner_daemon-v113-final.py')
manifest=json.loads((base/'manifest.json').read_text());old=manifest['scanner_daemon.py']
assert hashlib.sha256((base/'scanner_daemon.py').read_bytes()).hexdigest()==old
new=hashlib.sha256(candidate.read_bytes()).hexdigest();assert new==sys.argv[1]
compile(candidate.read_text(),str(candidate),'exec')
report=json.loads((base/'v113-deployment.json').read_text());backup=Path(report['backup'])/'scanner_daemon.before-final-tls.py'
assert not backup.exists();shutil.copy2(base/'scanner_daemon.py',backup)
uid=pwd.getpwnam('ubuntu').pw_uid;gid=pwd.getpwnam('ubuntu').pw_gid
def install(source):
    target=base/'scanner_daemon.final.new';shutil.copy2(source,target);os.chown(target,uid,gid);os.chmod(target,0o644);os.replace(target,base/'scanner_daemon.py')
try:
    install(candidate);subprocess.run(['systemctl','restart','shotcrypto.service'],check=True);time.sleep(8)
    subprocess.run(['python3','/tmp/probe_v113_server.py','8788','20'],check=True,timeout=35)
except Exception:
    install(backup);subprocess.run(['systemctl','restart','shotcrypto.service'],check=True);raise
manifest['scanner_daemon.py']=new;(base/'manifest.json').write_text(json.dumps(manifest,indent=2))
report['initialV113DaemonSha256']=old;report['newDaemonSha256']=new
(base/'v113-deployment.json').write_text(json.dumps(report,indent=2))
print('FINAL_TLS_LISTENER_VERIFIED',new)
