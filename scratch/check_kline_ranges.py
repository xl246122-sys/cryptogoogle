import sqlite3
from datetime import datetime, timezone

for db_name in [r'data\research.sqlite3', r'data\stage-d-diagnostic.sqlite3']:
    print('=== DB:', db_name)
    conn = sqlite3.connect(f'file:{db_name}?mode=ro', uri=True)
    cur = conn.cursor()
    # Check schema of klines
    schema = cur.execute("PRAGMA table_info(klines)").fetchall()
    print('Schema:', [(col[1], col[2]) for col in schema])
    # Distinct symbols and intervals
    distinct_combos = cur.execute("SELECT DISTINCT symbol, interval FROM klines").fetchall()
    print('Symbols and intervals:', distinct_combos)
    for sym, interval in distinct_combos:
        row = cur.execute("SELECT min(open_time), max(open_time), count(*) FROM klines WHERE symbol=? AND interval=?", (sym, interval)).fetchone()
        t_min = datetime.fromtimestamp(row[0]/1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
        t_max = datetime.fromtimestamp(row[1]/1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
        print(f"  {sym} {interval}: {row[2]} bars | {t_min} to {t_max}")
    conn.close()
