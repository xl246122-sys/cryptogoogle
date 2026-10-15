"""Deploy only V1.14 connection-status changes, with pinned SSH and rollback."""
import hashlib,json,os,sys,time,urllib.request,urllib.error
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'.tools/deploydeps'))
import paramiko
source={'scanner_daemon.py':root/'scratch/remote_scanner_daemon.py','cryptog/exit_delivery.py':root/'scratch/cryptog/exit_delivery.py','cryptog/config.py':root/'scratch/cryptog/config.py'}
old=json.loads((root/'audit/releases/v113-source-manifest.json').read_text())
new={k:hashlib.sha256(p.read_bytes()).hexdigest() for k,p in source.items()}
config=json.loads((root/'.private/Crypto-G V1.13设备配置.json').read_text())
client=paramiko.SSHClient();client.load_host_keys(str(root/'.ssh_known_hosts'));client.set_missing_host_key_policy(paramiko.RejectPolicy())
client.connect('43.163.203.127',username='ubuntu',password=os.environ['CRYPTO_G_SSH_PASS'],look_for_keys=False,allow_agent=False,timeout=15)
def command(value):
 _,out,err=client.exec_command(value,timeout=180);result=out.read().decode();error=err.read().decode();code=out.channel.recv_exit_status()
 if code:raise RuntimeError('Remote operation failed: '+error)
 return result
stamp=time.strftime('%Y%m%dT%H%M%SZ',time.gmtime());stage='/tmp/cryptog-v114-'+stamp;backup='/opt/shotcrypto/backups/pre-v114-'+stamp
installed=False
try:
 command('mkdir -m 700 '+stage)
 with client.open_sftp() as sftp:
  for i,(name,path) in enumerate(source.items()):sftp.put(str(path),stage+'/'+str(i)+'.py')
  script="""import hashlib,json,os,pwd,shutil,subprocess
from pathlib import Path
base=Path('/opt/shotcrypto');stage=Path(STAGE);backup=Path(BACKUP)
old=OLD;new=NEW
for i,name in enumerate(new):
 assert hashlib.sha256((base/name).read_bytes()).hexdigest()==old[name], 'Production changed: '+name
 assert hashlib.sha256((stage/(str(i)+'.py')).read_bytes()).hexdigest()==new[name]
 compile((stage/(str(i)+'.py')).read_text(encoding='utf-8-sig'),name,'exec')
backup.mkdir(mode=0o700)
for name in [*new,'manifest.json']:
 (backup/name).parent.mkdir(parents=True,exist_ok=True);shutil.copy2(base/name,backup/name)
uid=pwd.getpwnam('ubuntu').pw_uid;gid=pwd.getpwnam('ubuntu').pw_gid
subprocess.run(['systemctl','stop','shotcrypto.service'],check=True)
try:
 for i,name in enumerate(new):
  target=base/(name+'.new');shutil.copy2(stage/(str(i)+'.py'),target);os.chown(target,uid,gid);os.chmod(target,0o644);os.replace(target,base/name)
 manifest=json.loads((base/'manifest.json').read_text());manifest.update(new);(base/'manifest.json').write_text(json.dumps(manifest,indent=2))
 subprocess.run(['systemctl','start','shotcrypto.service'],check=True)
except Exception:
 for name in [*new,'manifest.json']:shutil.copy2(backup/name,base/name)
 subprocess.run(['systemctl','restart','shotcrypto.service'],check=True);raise
""".replace('STAGE',repr(stage)).replace('BACKUP',repr(backup)).replace('OLD',repr({k:old[k] for k in new})).replace('NEW',repr(new))
  with sftp.open(stage+'/install.py','w') as f:f.write(script)
 command('sudo python3 '+stage+'/install.py');installed=True
 def read(path,payload=None):
  request=urllib.request.Request(config['url']+'/model-library/'+path,headers={'X-Library-Token':config['token'],'Content-Type':'application/json'},data=None if payload is None else json.dumps(payload).encode())
  with urllib.request.urlopen(request,timeout=10) as response:return json.load(response)
 for attempt in range(12):
  try:
   value=read('market-state');device=read('exit-device-status',{'token':None})
   assert value['snapshot']['engineVersion']=='Crypto-G V1.14'
   assert value['runtimeHealthy'] and value['feedHealthy'] and value['notificationHealthy'] and value['exitNotificationHealthy']
   assert device['ok'] and device['matchesCurrentDevice'] is None and device['pushEnabled']
   break
  except Exception:
   if attempt==11:raise
   time.sleep(5)
 try:
  urllib.request.urlopen(config['url']+'/model-library/market-state',timeout=10);raise AssertionError('Missing auth accepted')
 except urllib.error.HTTPError as e:assert e.code==401
 report={'backup':backup,'sha256':new,'trustedPublicTLS':True,'unauthenticatedStatus':401,'engineVersion':value['snapshot']['engineVersion'],'runtimeHealthy':value['runtimeHealthy'],'feedHealthy':value['feedHealthy'],'notificationHealthy':value['notificationHealthy'],'exitNotificationHealthy':value['exitNotificationHealthy'],'ownerCredentialRegistered':device['registered'],'phoneTokenMatchVerified':False,'phoneDeliveryVerified':False}
 (root/'audit/releases/v114-server-verification.json').write_text(json.dumps(report,indent=2))
 print(json.dumps(report))
except Exception:
 if installed:
  restore="import shutil,subprocess;from pathlib import Path;b=Path("+repr(backup)+");r=Path('/opt/shotcrypto');[(shutil.copy2(b/n,r/n)) for n in "+repr([*new,'manifest.json'])+"];subprocess.run(['systemctl','restart','shotcrypto.service'],check=True)"
  with client.open_sftp() as sftp:
   with sftp.open(stage+'/rollback.py','w') as f:f.write(restore)
  command('sudo python3 '+stage+'/rollback.py')
 raise
finally:client.close()
