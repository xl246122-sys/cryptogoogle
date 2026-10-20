import sqlite3
import datetime

db = sqlite3.connect('/opt/shotcrypto/wave-observe-push-v1/data/push.sqlite3')
cur = db.cursor()
rows = cur.execute("SELECT id, at_ms, result, payload FROM deliveries WHERE result='SAME_PHASE_WITHIN_10M' ORDER BY at_ms DESC LIMIT 5").fetchall()
for r in rows:
    dt = datetime.datetime.fromtimestamp(r[1]/1000)
    print(f"Time: {dt}, result: {r[2]}")
db.close()
