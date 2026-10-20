from pathlib import Path
txt = Path('/opt/shotcrypto/wave-observe-push-v1/scratch/cryptog/wave_push.py').read_text(encoding='utf-8')
lines = txt.splitlines()
for idx, line in enumerate(lines[100:], 101):
    print(f"{idx}: {line}")
