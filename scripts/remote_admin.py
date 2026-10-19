"""Password-authenticated deployment transport; secrets only from process environment.

Pinned existing host key. No password/credential values are logged.
"""
import argparse
import os
from pathlib import Path
import sys
sys.stdout.reconfigure(encoding='utf-8',errors='replace')
sys.stderr.reconfigure(encoding='utf-8',errors='replace')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'.tools/deploydeps'))
import paramiko

parser=argparse.ArgumentParser()
parser.add_argument('--command')
parser.add_argument('--upload',nargs=2,metavar=('LOCAL','REMOTE'))
parser.add_argument('--download',nargs=2,metavar=('REMOTE','LOCAL'))
parser.add_argument('--stdin-file', help='Stream a local file to command stdin without logging its contents')
args=parser.parse_args()
client=paramiko.SSHClient()
client.load_host_keys(str(Path(__file__).resolve().parents[1]/'.ssh_known_hosts'))
client.set_missing_host_key_policy(paramiko.RejectPolicy())
client.connect('43.163.203.127',username='ubuntu',password=os.environ['CRYPTO_G_SSH_PASS'],look_for_keys=False,allow_agent=False,timeout=15)
try:
    if args.upload or args.download:
        with client.open_sftp() as sftp:
            if args.upload:sftp.put(*args.upload)
            else:sftp.get(*args.download)
    if args.command:
        stdin,stdout,stderr=client.exec_command(args.command,timeout=300)
        if args.stdin_file:
            stdin.write(Path(args.stdin_file).read_text(encoding='utf-8-sig'))
            stdin.flush()
            stdin.channel.shutdown_write()
        stdin.close()
        for line in stdout:print(line,end='',flush=True)
        error=stderr.read().decode('utf-8',errors='replace')
        if error:print(error,file=sys.stderr,end='')
        raise SystemExit(stdout.channel.recv_exit_status())
finally:client.close()
