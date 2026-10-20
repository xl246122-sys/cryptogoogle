import os
from pathlib import Path

root = Path('/opt/shotcrypto/backups')
total_size = 0
found = []
for p in root.glob('**/*'):
    if p.is_file():
        sz = p.stat().st_size
        total_size += sz
        if sz > 100 * 1024 * 1024: # > 100MB
            found.append((str(p), sz / (1024*1024*1024)))

print(f"Total backups dir size: {total_size / (1024*1024*1024):.2f} GB")
print(f"Files > 100MB ({len(found)} files):")
for f, gb in sorted(found, key=lambda x: -x[1]):
    print(f"  {gb:.2f} GB: {f}")
