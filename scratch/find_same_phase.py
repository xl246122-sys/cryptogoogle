import os
from pathlib import Path

for root, dirs, files in os.walk('/opt/shotcrypto'):
    if 'backups' in root or 'venv' in root:
        continue
    for f in files:
        if f.endswith('.py') or f.endswith('.json') or f.endswith('.sh'):
            p = Path(root) / f
            try:
                txt = p.read_text(encoding='utf-8', errors='ignore')
                if 'SAME_PHASE' in txt or '10M' in txt or 'COOLDOWN' in txt:
                    print(f"Found in {p}")
                    for line in txt.splitlines():
                        if 'SAME_PHASE' in line or 'COOLDOWN' in line:
                            print("  ", line.strip())
            except Exception as e:
                pass
