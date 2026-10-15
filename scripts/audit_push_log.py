from pathlib import Path
import json
lines=[]
for name in ('scanner.log','service_err.log'):
 p=Path('/opt/shotcrypto/logs')/name
 if p.exists():
  for line in p.read_text(errors='replace').splitlines():
   if ('FCM' in line or 'Firebase' in line) and ('2026-10-14' in line or '2026-10-15' in line):lines.append(line[:350])
print(json.dumps(lines[-25:],ensure_ascii=False))
