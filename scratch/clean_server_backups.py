import os
import shutil
from pathlib import Path

targets = [
    '/opt/shotcrypto/backups/startup-v145-20261016-135404/monitor-v1.sqlite3',
    '/opt/shotcrypto/backups/quiet-v143-20261016-093431/monitor-v1.sqlite3',
    '/opt/shotcrypto/backups/short-v2-20261016-080954/monitor-v1.sqlite3',
    '/opt/shotcrypto/backups/ai-contract-20261016-111436/monitor-v1.sqlite3',
    '/opt/shotcrypto/backups/api-v136-20261016/monitor-v1.sqlite3',
    '/opt/shotcrypto/backups/ai-v133-20261016/monitor-v1.sqlite3',
    '/opt/shotcrypto/backups/ai-v134-20261016/pre-deploy.tgz',
]

deleted_bytes = 0
for t in targets:
    p = Path(t)
    if p.exists():
        sz = p.stat().st_size
        p.unlink()
        deleted_bytes += sz
        print(f"Deleted: {t} ({sz / (1024*1024*1024):.2f} GB)")
    else:
        print(f"Not found: {t}")

print(f"\nTotal space freed: {deleted_bytes / (1024*1024*1024):.2f} GB")
total, used, free = shutil.disk_usage('/opt/shotcrypto')
print(f"Current Disk: Total={total/(1024**3):.1f} GB, Used={used/(1024**3):.1f} GB, Free={free/(1024**3):.1f} GB ({free/total*100:.1f}% free)")
