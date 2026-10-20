import difflib
from pathlib import Path

p_remote = Path('/opt/shotcrypto/wave-observe-push-v1/scratch/cryptog/wave_push.py').read_text(encoding='utf-8')
print("Remote wave_push.py lines 60-142:")
print("\n".join(p_remote.splitlines()[60:]))
