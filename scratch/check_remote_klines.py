import sqlite3
from datetime import datetime, timezone

conn = sqlite3.connect('/opt/shotcrypto/model_library/research.sqlite3')
cur = conn.cursor()
for sym, interval in cur.execute("SELECT DISTINCT symbol, interval FROM klines").fetchall():
    row = cur.execute("SELECT min(open_time), max(open_time), count(*) FROM klines WHERE symbol=? AND interval=?", (sym, interval)).fetchone()
    t_min = datetime.fromtimestamp(row[0]/1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    t_max = datetime.fromtimestamp(row[1]/1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    print(f"{sym} {interval}: {row[2]} bars | {t_min} to {t_max}")
conn.close()
