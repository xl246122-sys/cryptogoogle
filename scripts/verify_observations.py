import sqlite3,json
c=sqlite3.connect('file:/opt/shotcrypto/model_library/monitor-v1.sqlite3?mode=ro',uri=True)
print(json.dumps({'stateRows':c.execute('select count(*) from observation_state').fetchone()[0],'delivery':c.execute('select state,count(*) from observation_queue group by state').fetchall()}))
