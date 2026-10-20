import difflib
from pathlib import Path

dir_path = Path('/opt/shotcrypto/wave-observe-push-v1/scratch/cryptog')
curr = (dir_path / 'wave_push.py').read_text(encoding='utf-8').splitlines()
bak1 = (dir_path / 'wave_push.py.bak-20261019-quiet').read_text(encoding='utf-8').splitlines()
bak2 = (dir_path / 'wave_push.py.bak-20261019-text').read_text(encoding='utf-8').splitlines()

print("=== Diff with wave_push.py.bak-20261019-quiet ===")
for d in difflib.unified_diff(bak1, curr, lineterm=''):
    print(d)

print("\n=== Diff with wave_push.py.bak-20261019-text ===")
for d in difflib.unified_diff(bak2, curr, lineterm=''):
    print(d)
