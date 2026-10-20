import json
import hashlib
from pathlib import Path

root = Path('/opt/shotcrypto/wave-observe-push-v1')
manifest = json.loads((root/'manifest.json').read_text())
for name, digest in manifest.get('files', {}).items():
    p = root / name
    if not p.exists():
        print('Missing:', name)
        continue
    actual = hashlib.sha256(p.read_bytes()).hexdigest()
    if actual != digest:
        print('MISMATCH:', name)
        print('  expected in manifest:', digest)
        print('  actual on disk:      ', actual)
