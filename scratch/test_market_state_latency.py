import time
import urllib.request
import ssl
import json
import os
from pathlib import Path

# Read device auth token
auth_file = os.environ.get('CRYPTOG_DEVICE_AUTH_FILE', '/opt/shotcrypto/model_library/monitor-v1.ai-key')
if not Path(auth_file).exists():
    auth_file = '/opt/shotcrypto/manifest.json'

# Let's find a valid token from /opt/shotcrypto/model_library
token_file = '/opt/shotcrypto/model_library/monitor-v1.ai-key'
ctx = ssl._create_unverified_context()

# We can also test directly without token to see 401 response time
t0 = time.time()
try:
    req = urllib.request.Request('https://127.0.0.1:8788/model-library/market-state?view=radar')
    with urllib.request.urlopen(req, context=ctx, timeout=5) as res:
        pass
except urllib.error.HTTPError as e:
    t1 = time.time()
    print(f"Server response code: {e.code}, latency: {(t1 - t0)*1000:.2f} ms")
except Exception as e:
    t1 = time.time()
    print(f"Error: {e}, latency: {(t1 - t0)*1000:.2f} ms")
