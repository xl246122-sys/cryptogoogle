with open('/opt/shotcrypto/scanner_daemon.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()
print(f"Total lines in scanner_daemon.py: {len(lines)}")
print("First 80 lines:")
print("".join(lines[:80]))
