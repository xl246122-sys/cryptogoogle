import sqlite3

for db_name in [r'data\research.sqlite3', r'data\stage-d-diagnostic.sqlite3']:
    print('=== DB:', db_name)
    try:
        conn = sqlite3.connect(f'file:{db_name}?mode=ro', uri=True)
        cur = conn.cursor()
        tables = cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        print('Tables:', [t[0] for t in tables])
        for t in tables:
            name = t[0]
            try:
                count = cur.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
                print(f'  {name}: {count} rows')
            except Exception as e:
                print(f'  {name}: count error {e}')
        conn.close()
    except Exception as e:
        print('Error:', e)
