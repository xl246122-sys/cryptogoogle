import difflib
from pathlib import Path

p_remote = Path('/opt/shotcrypto/wave-observe-push-v1/scratch/cryptog/wave_push.py').read_text(encoding='utf-8').splitlines()
p_local = Path('/opt/shotcrypto/cryptog/wave_push.py')
if not p_local.exists():
    p_local = Path('/opt/shotcrypto/wave-shadow-d002/cryptog/wave_push.py')

if p_local.exists():
    lines_local = p_local.read_text(encoding='utf-8').splitlines()
    print("Diff with /opt/shotcrypto/cryptog/wave_push.py:")
    for d in difflib.unified_diff(lines_local, p_remote, lterm=''):
        print(d)
else:
    print("p_local not found, showing full wave_push.py in wave-observe-push-v1:")
    print("\n".join(p_remote[:60]))
