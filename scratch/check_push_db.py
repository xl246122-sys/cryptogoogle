import sqlite3
import json

db = sqlite3.connect('/opt/shotcrypto/wave-observe-push-v1/data/push.sqlite3')
cur = db.cursor()
print("Deliveries count by state:")
for r in cur.execute("SELECT state, count(*) FROM deliveries GROUP BY state").fetchall():
    print(" ", r)

print("\nLast 10 deliveries:")
for r in cur.execute("SELECT id, event, revision, state, at_ms, result, payload FROM deliveries ORDER BY at_ms DESC LIMIT 10").fetchall():
    p = json.loads(r[6]) if r[6] else {}
    print(f"  id={r[0][:8]}, event={r[1]}, phase={p.get('phase')}, state={r[3]}, at={r[4]}, result={r[5]}")

print("\nCursor:")
for r in cur.execute("SELECT * FROM cursor").fetchall():
    print(" ", r)
db.close()
