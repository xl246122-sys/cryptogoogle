"""Release only the rotated owner's obsolete binding; keep a private recovery copy."""
import datetime,json,os,sqlite3,time
from pathlib import Path
registry=Path('/etc/shotcrypto/devices.json')
active=json.loads(registry.read_text())
backups=sorted(registry.parent.glob('devices.pre-owner-rebind-*.json'))
assert len(backups)==1, 'Ambiguous prior owner identity'
prior=json.loads(backups[0].read_text())['owner-phone']['sha256']
assert prior!=active['owner-phone']['sha256']
assert prior not in {v['sha256'] for v in active.values()}
db=sqlite3.connect('/opt/shotcrypto/model_library/monitor-v1.sqlite3',timeout=15)
with db:
    db.execute('BEGIN IMMEDIATE')
    row=db.execute('SELECT device,token,generation FROM exit_devices WHERE device=?',(prior,)).fetchone()
    if row:
        path=Path('/opt/shotcrypto/backups')/('revoked-owner-binding-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.json')
        with path.open('x') as f:
            os.chmod(path,0o600);json.dump({'binding':row},f);f.flush();os.fsync(f.fileno())
        db.execute('DELETE FROM exit_devices WHERE device=?',(prior,))
        db.execute("UPDATE exit_outbox SET state='CANCELLED',updated_ms=? WHERE device=? AND state IN ('PENDING','SENDING')",(int(time.time()*1000),prior))
    assert db.execute('SELECT count(*) FROM exit_devices WHERE device=?',(prior,)).fetchone()[0]==0
print(json.dumps({'obsoleteOwnerBindingRemoved':bool(row),'otherDevicesPreserved':True,'restartRequired':False}))
db.close()
