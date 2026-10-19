"""Read-only research inventory; runnable locally or through SSH stdin."""
import argparse
import hashlib
import json
import sqlite3
import time
from pathlib import Path

INTERVALS = {'1m': 60000, '5m': 300000, '15m': 900000,
             '1h': 3600000, '4h': 14400000, '1d': 86400000}


def inspect(path, now_ms):
    db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    try:
        db.execute('BEGIN')
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        result = {'atMs': now_ms, 'database': str(path),
                  'quickCheck': db.execute('PRAGMA quick_check').fetchone()[0], 'coverage': {}}
        for tf, step in INTERVALS.items():
            digest = hashlib.sha256()
            count = missing = invalid = 0
            start = previous = end = None
            for row in db.execute('SELECT open_time,open,high,low,close,volume,close_time,taker_buy_base '
                                  'FROM klines WHERE symbol=? AND interval=? ORDER BY open_time', ('BTCUSDT', tf)):
                stamp, op, hi, lo, cl, vol, close, taker = row
                digest.update((json.dumps(row, separators=(',', ':'), allow_nan=False)+'\n').encode())
                if start is None:
                    start = stamp
                if previous is not None:
                    missing += max(0, (stamp-previous)//step-1)
                invalid += int(stamp % step != 0 or close != stamp+step-1 or close >= now_ms
                               or not (0 < lo <= min(op, cl) <= max(op, cl) <= hi)
                               or not (0 <= taker <= vol))
                count += 1
                previous = end = stamp
            result['coverage'][tf] = dict(count=count, startMs=start, endMs=end, internalMissing=missing,
                                         invalid=invalid, contentSha256=digest.hexdigest(),
                                         tailMissing=None if end is None else max(0, (now_ms//step*step-step-end)//step))
        result['counts'] = {t: db.execute('SELECT count(*) FROM '+t).fetchone()[0]
                            for t in ('candidates', 'shadow_positions', 'labels', 'real_fills', 'promotions') if t in tables}
        result['releaseStages'] = [dict(module=m, stage=s, startedMs=t, records=n)
                                   for m, s, t, n in db.execute('SELECT module,stage,stage_started_ms,records FROM release_modules')] if 'release_modules' in tables else []
        result['derivatives'] = {}
        for table, column in (('funding_rates','funding_time'), ('open_interest','time'), ('taker_ratio','time')):
            if table in tables:
                n, first, last = db.execute(f'SELECT count(*),min({column}),max({column}) FROM {table} WHERE symbol=?', ('BTCUSDT',)).fetchone()
                result['derivatives'][table] = dict(count=n, startMs=first, endMs=last)
        return result
    finally:
        db.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', required=True)
    args = parser.parse_args()
    print(json.dumps(inspect(args.db, int(time.time()*1000)), ensure_ascii=False, indent=2))
