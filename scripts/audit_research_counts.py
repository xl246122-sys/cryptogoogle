import sqlite3,json,collections
c=sqlite3.connect('file:/opt/shotcrypto/model_library/monitor-v1.sqlite3?mode=ro',uri=True)
rows=c.execute("select payload from events where kind='RESEARCH_CANDIDATE'").fetchall()
counts=collections.Counter((json.loads(r[0])['variant'],json.loads(r[0])['version']) for r in rows)
print(json.dumps({'candidateCounts':[{'variant':k[0],'version':k[1],'count':v} for k,v in counts.items()],'independentOutcomesVerified':False}))
