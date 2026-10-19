"""Server-side lossless archive of stopped, immutable monitor backups only.

Keeps every byte in an XZ archive; checks SQLite and a decompression SHA256
before replacing an original. Never touches the live model_library directory.
"""
import lzma
import hashlib
import json
import os
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

ROOT = Path('/opt/shotcrypto/backups').resolve(strict=True)


def digest(stream):
    h = hashlib.sha256()
    for chunk in iter(lambda: stream.read(4*1024*1024), b''):
        h.update(chunk)
    return h.hexdigest()


def archive(source):
    if source.is_symlink() or source.resolve().parent.parent != ROOT:
        raise ValueError('Backup path outside the authorized directory')
    for suffix in ('-wal', '-shm', '-journal'):
        if Path(str(source)+suffix).exists():
            raise ValueError('Backup has active sidecars: '+str(source))
    before = source.stat()
    if before.st_mtime > __import__('time').time()-3600:
        raise ValueError('Backup is too recent: '+str(source))
    print(json.dumps(dict(source=str(source), phase='CHECK_SQLITE')), flush=True)
    with closing(sqlite3.connect(source.as_uri()+'?mode=ro&immutable=1', uri=True)) as db:
        db.execute('PRAGMA mmap_size=8589934592')
        if db.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
            raise ValueError('SQLite integrity check failed')
    target, temporary = Path(str(source)+'.xz'), Path(str(source)+'.xz.partial')
    if target.exists() or temporary.exists():
        raise ValueError('Archive destination already exists')
    try:
        print(json.dumps(dict(source=str(source), phase='COMPRESS')), flush=True)
        with source.open('rb') as src, temporary.open('xb') as dst:
            os.chmod(temporary, 0o600)
            with lzma.LZMAFile(dst, mode='wb', preset=1) as zipped:
                shutil.copyfileobj(src, zipped, 4*1024*1024)
            dst.flush()
            os.fsync(dst.fileno())
        print(json.dumps(dict(source=str(source), phase='VERIFY_RESTORE_BYTES')), flush=True)
        with source.open('rb') as src:
            original_hash = digest(src)
        with lzma.open(temporary, 'rb') as restored:
            if digest(restored) != original_hash:
                raise ValueError('Decompressed archive does not match original')
        after = source.stat()
        if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
            raise ValueError('Source changed during archive')
        report = dict(source=str(source), archive=str(target), originalBytes=before.st_size,
                      archiveBytes=temporary.stat().st_size, sha256=original_hash, sqliteQuickCheck='ok',
                      decompressedHashVerified=True)
        if report['archiveBytes'] >= before.st_size*.9:
            temporary.unlink()
            return dict(report, status='KEPT_ORIGINAL_LOW_SAVINGS')
        temporary.rename(target)
        manifest = Path(str(target)+'.json')
        with manifest.open('x') as handle:
            json.dump(report, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(manifest, 0o600)
        directory_fd = os.open(str(target.parent), os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        # All preconditions hold; this exact immutable backup now has verified recovery bytes.
        source.unlink()
        return dict(report, status='ARCHIVED')
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise


if __name__ == '__main__':
    # Explicit inventory: retain all other backups untouched.
    for name in ('pre-p5-20261017-090306',):
        source = ROOT/name/'monitor-v1.sqlite3'
        try:
            print(json.dumps(archive(source)), flush=True)
        except Exception as exc:
            print(json.dumps(dict(source=str(source), status='UNCHANGED', error=str(exc))), flush=True)
    print(json.dumps(dict(diskFreeBytes=shutil.disk_usage(ROOT).free)), flush=True)
