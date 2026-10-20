import subprocess

def tail(file_path, n=30):
    try:
        res = subprocess.run(['tail', '-n', str(n), file_path], capture_output=True, text=True)
        return res.stdout
    except Exception as e:
        return str(e)

print("=== scanner.log tail ===")
print(tail('/opt/shotcrypto/logs/scanner.log', 25))
print("=== service_err.log tail ===")
print(tail('/opt/shotcrypto/logs/service_err.log', 25))
