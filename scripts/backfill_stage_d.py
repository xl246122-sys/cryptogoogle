"""Create an isolated diagnostic SQLite snapshot and resume missing history there."""
import json
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scratch'))
from cryptog.kline_store import ResearchStore, INTERVAL_MS, get_json, KLINE_URL, bar_from_kline
from audit_stage_d_data import inspect


def main():
    target = ROOT/'data'/'stage-d-diagnostic.sqlite3'
    if not target.exists():
        source = sqlite3.connect((ROOT/'data'/'research.sqlite3').as_uri()+'?mode=ro', uri=True)
        dest = sqlite3.connect(target)
        try:
            source.backup(dest)
        finally:
            dest.close()
            source.close()
    store = ResearchStore(str(target))
    try:
        # The old report's end was already viewed: this remains diagnostic data.
        old = json.loads((ROOT/'model_library'/'baseline'/'short-horizon-v2.json').read_text(encoding='utf-8'))
        end = int(old['endMs'])+1
        for tf in INTERVAL_MS:
            start = store.db.execute('SELECT min(open_time) FROM klines WHERE symbol=? AND interval=?', ('BTCUSDT', tf)).fetchone()[0]
            if start is None:
                raise ValueError('Missing original interval: '+tf)
            step = INTERVAL_MS[tf]
            cursor = store.max_open_time('BTCUSDT', tf)+step
            final = end//step*step
            starts = range(cursor, final, step*1000)
            def fetch_page(at):
                stop = min(final, at+step*1000)
                raw = get_json(KLINE_URL.format(symbol='BTCUSDT', interval=tf, start=at, end=stop-1))
                bars = [bar_from_kline(row) for row in raw]
                if [b['time'] for b in bars] != list(range(at, stop, step)):
                    raise ValueError('Incomplete public history page: '+tf+' '+str(at))
                if any(b['close_time'] != b['time']+step-1 for b in bars):
                    raise ValueError('Invalid close time')
                return bars
            # Requests overlap; SQLite commits stay serial and chronological.
            with ThreadPoolExecutor(max_workers=8) as pool:
                for bars in pool.map(fetch_page, starts):
                    store.upsert_klines('BTCUSDT', tf, bars)
                    print(f"{tf} +{len(bars)} through {bars[-1]['time']}", flush=True)
    finally:
        store.close()
    import time
    report = inspect(target, int(time.time()*1000))
    report['use'] = 'DIAGNOSTIC_ONLY'
    (ROOT/'audit'/'stage-d-diagnostic-data.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('DIAGNOSTIC_DATA_READY', flush=True)


if __name__ == '__main__':
    main()
