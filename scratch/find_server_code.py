with open('/opt/shotcrypto/scanner_daemon.py', 'r', encoding='utf-8') as f:
    text = f.read()

import re
matches = [m.start() for m in re.finditer(r'8788|HTTPServer|ThreadingHTTPServer|class ', text)]
for idx in matches[:10]:
    start = max(0, idx - 100)
    end = min(len(text), idx + 200)
    print("--- MATCH ---")
    print(text[start:end])
