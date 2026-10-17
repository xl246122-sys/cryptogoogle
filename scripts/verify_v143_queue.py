import json,sqlite3,time
db=sqlite3.connect('file:/opt/shotcrypto/model_library/monitor-v1.sqlite3?mode=ro',uri=True)
since=int(time.time()*1000)-86400000
rows=db.execute("SELECT b.id,b.state,b.attempts,b.sent_ms,b.last_error FROM outbox b JOIN events e ON e.id='opportunity:'||b.id WHERE e.at_ms>=?",(since,)).fetchall()
print(json.dumps({'deliveries24h':rows,
 'pendingObservationNoise':db.execute("SELECT count(*) FROM observation_queue WHERE state='PENDING' AND json_extract(payload,'$.eventType')='OBSERVATION_NOTICE'").fetchone()[0],
 'pendingOldAIStages':db.execute("SELECT count(*) FROM ai_stages WHERE state='PENDING'").fetchone()[0]},indent=2))
