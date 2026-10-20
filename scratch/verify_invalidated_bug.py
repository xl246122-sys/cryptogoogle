import sqlite3
import json

db = sqlite3.connect('/opt/shotcrypto/wave-observe-push-v1/data/push.sqlite3')
cur = db.cursor()

# Check how many INVALIDATED were sent when REBOUND_CONFIRMED was NEVER sent
rows = cur.execute("""
    SELECT d.id, d.event, d.at_ms, d.result
    FROM deliveries d
    WHERE d.state='FCM_ACCEPTED' AND json_extract(d.payload, '$.phase')='INVALIDATED'
    ORDER BY d.at_ms DESC LIMIT 10
""").fetchall()

print(f"Total INVALIDATED sent: {len(rows)}")
for r in rows:
    # check if REBOUND_CONFIRMED was ever sent for this event
    reb = cur.execute("""
        SELECT count(*) FROM deliveries 
        WHERE event=? AND state='FCM_ACCEPTED' AND json_extract(payload, '$.phase')='REBOUND_CONFIRMED'
    """, (r[1],)).fetchone()[0]
    # check what was actually sent
    phases = [p[0] for p in cur.execute("""
        SELECT json_extract(payload, '$.phase') FROM deliveries 
        WHERE event=? AND state='FCM_ACCEPTED'
    """, (r[1],)).fetchall()]
    print(f"Event: {r[1]}, Rebound sent: {reb}, All phases sent for event: {phases}")

db.close()
