"""Per-device bearer credentials stored only as SHA256 digests on the server."""
import hashlib
import hmac
import json
import os
import ssl
import threading
import time
from collections import OrderedDict
from pathlib import Path

class DeviceAuth:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()
        self.buckets = OrderedDict()
        self.load()

    def load(self):
        data = json.loads(self.path.read_text(encoding='utf-8'))
        if not isinstance(data, dict) or not data: raise ValueError('Device credentials required')
        for device, item in data.items():
            digest = item.get('sha256','')
            if not device or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
                raise ValueError('Invalid credential digest')
            if not isinstance(item.get('write',False),bool): raise ValueError('Invalid write permission')
        return data

    def allow(self, token, address, write=False):
        now = time.monotonic()
        with self.lock:
            tokens, at = self.buckets.pop(address,(120.,now))
            tokens = min(120.,tokens+(now-at)*2)
            self.buckets[address] = (max(0.,tokens-1),now)
            while len(self.buckets)>2048: self.buckets.popitem(last=False)
            if tokens < 1: return False
        if len(token)<32 or len(token)>256: return False
        digest = hashlib.sha256(token.encode()).hexdigest()
        try: devices = self.load()  # Revocation takes effect without daemon restart.
        except (ValueError,OSError): return False
        return any(hmac.compare_digest(digest,item['sha256']) and (not write or item.get('write',False))
                   for item in devices.values())

def tls_context():
    cert, key = os.environ.get('CRYPTOG_TLS_CERT'), os.environ.get('CRYPTOG_TLS_KEY')
    if not cert or not key: raise RuntimeError('TLS certificate/key required; plaintext server disabled')
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(cert,key)
    return ctx
