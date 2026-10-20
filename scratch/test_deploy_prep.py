import hashlib
import json
import os
import subprocess
from pathlib import Path

root = Path('/opt/shotcrypto/wave-observe-push-v1')
py = '/opt/shotcrypto/venv-v113/bin/python'

# Read local updated wave_push.py content that was streamed
src_wave_push = Path('/opt/shotcrypto/cryptog/wave_push.py')
# If not present in /opt/shotcrypto/cryptog/, we will write the exact text
# Let's inspect manifest files
manifest_path = root / 'manifest.json'
manifest = json.loads(manifest_path.read_text(encoding='utf-8'))

print("Current manifest files:", list(manifest['files'].keys()))
