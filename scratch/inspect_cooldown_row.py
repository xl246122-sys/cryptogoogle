import sqlite3

db = sqlite3.connect('/opt/shotcrypto/wave-observe-push-v1/data/push.sqlite3')
cur = db.cursor()
row = cur.execute("SELECT id, at_ms, result, payload FROM deliveries WHERE result='SAME_PHASE_WITHIN_10M' LIMIT 1").fetchone()
print("ID:", row[0])
print("At:", row[1])
print("Result:", row[2])
print("Payload:", row[3])
db.close()
