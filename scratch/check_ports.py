import subprocess
res = subprocess.run(['ss', '-tulpn'], capture_output=True, text=True)
print(res.stdout)
