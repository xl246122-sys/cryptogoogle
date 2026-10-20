import json, sys, time
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import paramiko
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("43.163.203.127", username="ubuntu", password="Maxence2468;", timeout=20, allow_agent=False, look_for_keys=False)

def run(cmd):
    _, stdout, stderr = c.exec_command(cmd, timeout=40)
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    code = stdout.channel.recv_exit_status()
    print("EXIT", code)
    print(out)
    if err.strip():
        print("ERR", err)
    return code, out

run("sudo -n cp /opt/shotcrypto/wave-observe-push-v1/scratch/cryptog/wave_push.py.bak-20261019-quiet /opt/shotcrypto/wave-observe-push-v1/scratch/cryptog/wave_push.py")
updater = (
    "import hashlib,json,sqlite3; from pathlib import Path; "
    "root=Path('/opt/shotcrypto/wave-observe-push-v1'); name='scratch/cryptog/wave_push.py'; "
    "digest=hashlib.sha256((root/name).read_bytes()).hexdigest(); "
    "p=root/'manifest.json'; m=json.loads(p.read_text()); m['files'][name]=digest; "
    "p.write_text(json.dumps(m, ensure_ascii=False, indent=2)+'\\n'); print('hash',digest); "
    "db=root/'data'/'push.sqlite3'; "
    "if db.exists(): "
    "  conn=sqlite3.connect(db); "
    "  n=conn.execute(\"UPDATE deliveries SET state='PENDING',result=NULL WHERE state='COOLDOWN'\").rowcount; "
    "  conn.commit(); print('requeued',n); conn.close()"
)
run("sudo -n /opt/shotcrypto/venv-v113/bin/python -c " + json.dumps(updater))
run("sudo -n grep -n QUIET_MS /opt/shotcrypto/wave-observe-push-v1/scratch/cryptog/wave_push.py; echo GRADE:$?")
run("sudo -n systemctl restart cryptog-wave-observe-push.service")
time.sleep(4)
run("systemctl is-active cryptog-wave-observe-push.service; systemctl show cryptog-wave-observe-push.service -p ActiveState -p SubState -p Result --no-page")
run("sudo -n journalctl -u cryptog-wave-observe-push.service -n 8 --no-pager")
c.close()
