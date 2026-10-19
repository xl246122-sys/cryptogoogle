import json,sqlite3
from pathlib import Path
registry=json.loads(Path('/etc/shotcrypto/devices.json').read_text())
active={v['sha256']:k for k,v in registry.items()}
db=sqlite3.connect('file:/opt/shotcrypto/model_library/monitor-v1.sqlite3?mode=ro',uri=True)
rows=db.execute('SELECT device,length(token) FROM exit_devices').fetchall()
print(json.dumps({'bindings':[{'credential':active.get(d,'REVOKED'),'tokenLength':n} for d,n in rows]}))
db.close()
