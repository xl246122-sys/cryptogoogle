"""Deploy V1.16 shadow research and diagnostics, with pinned SSH and rollback."""
import hashlib,json,os,sys,time,urllib.request,urllib.error
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'.tools/deploydeps'))
import paramiko
source={name:root/'scratch'/name for name in ('cryptog/runtime.py','cryptog/observations.py')}
old=json.loads((root/'audit/releases/experimental-server-verification.json').read_text())['sha256']
old['cryptog/observations.py']=None
new={k:hashlib.sha256(p.read_bytes()).hexdigest() for k,p in source.items()}
config=json.loads((root/'.private/Crypto-G V1.13设备配置.json').read_text())
client=paramiko.SSHClient();client.load_host_keys(str(root/'.ssh_known_hosts'));client.set_missing_host_key_policy(paramiko.RejectPolicy())
client.connect('43.163.203.127',username='ubuntu',password=os.environ['CRYPTO_G_SSH_PASS'],look_for_keys=False,allow_agent=False,timeout=15)
def command(value):
 _,out,err=client.exec_command(value,timeout=180);result=out.read().decode();error=err.read().decode();code=out.channel.recv_exit_status()
 if code:raise RuntimeError('Remote operation failed: '+error)
 return result
stamp=time.strftime('%Y%m%dT%H%M%SZ',time.gmtime());stage='/tmp/cryptog-observations-'+stamp;backup='/opt/shotcrypto/backups/pre-observations-'+stamp
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
 assert (hashlib.sha256((base/name).read_bytes()).hexdigest() if (base/name).exists() else None)==old[name], 'Production changed: '+name
 assert hashlib.sha256((stage/(str(i)+'.py')).read_bytes()).hexdigest()==new[name]
 compile((stage/(str(i)+'.py')).read_text(encoding='utf-8-sig'),name,'exec')
backup.mkdir(mode=0o700)
for name in [*new,'manifest.json']:
 (backup/name).parent.mkdir(parents=True,exist_ok=True)
 if (base/name).exists():shutil.copy2(base/name,backup/name)
shutil.copy2('/etc/shotcrypto/production.env',backup/'production.env')
uid=pwd.getpwnam('ubuntu').pw_uid;gid=pwd.getpwnam('ubuntu').pw_gid
subprocess.run(['systemctl','stop','shotcrypto.service'],check=True)
try:
 for i,name in enumerate(new):
  target=base/(name+'.new');shutil.copy2(stage/(str(i)+'.py'),target);os.chown(target,uid,gid);os.chmod(target,0o644);os.replace(target,base/name)
 manifest=json.loads((base/'manifest.json').read_text());manifest.update(new);(base/'manifest.json').write_text(json.dumps(manifest,indent=2))
 env=Path('/etc/shotcrypto/production.env');text=env.read_text();env.write_text(text+chr(10)+'CRYPTOG_ENABLE_EXPERIMENTAL_ALERTS=1'+chr(10))
 subprocess.run(['systemctl','start','shotcrypto.service'],check=True)
except Exception:
 shutil.copy2(backup/'production.env','/etc/shotcrypto/production.env')
 for name in [*new,'manifest.json']:
  if (backup/name).exists():shutil.copy2(backup/name,base/name)
  elif (base/name).exists():(base/name).unlink()
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
   assert value['snapshot']['engineVersion']=='Crypto-G V1.16'
   assert value['runtimeHealthy'] and value['feedHealthy'] and value['notificationHealthy'] and value['exitNotificationHealthy']
   assert len(value['snapshot']['research'])==7 and all(r['mode']=='SHADOW' and r['status']!='ERROR' for r in value['snapshot']['research'])
   assert device['ok'] and device['matchesCurrentDevice'] is None and device['pushEnabled']
   break
  except Exception:
   if attempt==11:raise
   time.sleep(5)
 try:
  urllib.request.urlopen(config['url']+'/model-library/market-state',timeout=10);raise AssertionError('Missing auth accepted')
 except urllib.error.HTTPError as e:assert e.code==401
 report={'backup':backup,'sha256':new,'trustedPublicTLS':True,'unauthenticatedStatus':401,'engineVersion':value['snapshot']['engineVersion'],'runtimeHealthy':value['runtimeHealthy'],'feedHealthy':value['feedHealthy'],'notificationHealthy':value['notificationHealthy'],'exitNotificationHealthy':value['exitNotificationHealthy'],'ownerCredentialRegistered':device['registered'],'phoneTokenMatchVerified':False,'phoneDeliveryVerified':False,'research':[{k:r[k] for k in ('variant','version','mode','status')} for r in value['snapshot']['research']]}
 (root/'audit/releases/experimental-server-verification.json').write_text(json.dumps(report,indent=2))
 print(json.dumps(report))
except Exception:
 if installed:
  restore="import shutil,subprocess;from pathlib import Path;b=Path("+repr(backup)+");r=Path('/opt/shotcrypto');shutil.copy2(b/'production.env','/etc/shotcrypto/production.env');[(shutil.copy2(b/n,r/n) if (b/n).exists() else (r/n).unlink(missing_ok=True)) for n in "+repr([*new,'manifest.json'])+"];subprocess.run(['systemctl','restart','shotcrypto.service'],check=True)"
  with client.open_sftp() as sftp:
   with sftp.open(stage+'/rollback.py','w') as f:f.write(restore)
  command('sudo python3 '+stage+'/rollback.py')
 raise
finally:client.close()
