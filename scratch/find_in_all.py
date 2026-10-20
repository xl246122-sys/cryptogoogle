import os
from pathlib import Path

for root, dirs, files in os.walk('/opt/shotcrypto'):
    if 'venv' in root:
        continue
    for f in files:
        if f.endswith('.py') or f.endswith('.json'):
            p = Path(root) / f
            try:
                txt = p.read_text(encoding='utf-8', errors='ignore')
                if 'SAME_PHASE_WITHIN_10M' in txt:
                    print(f"MATCH: {p}")
            except:
                pass
