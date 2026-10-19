import json
from pathlib import Path
p=Path('/opt/shotcrypto/model_library/user_actions.jsonl')
rows=[json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []
paper=[r for r in rows if r.get('strategy')=='QUICK_PAPER_V2' and r.get('recordType') in ['SIM_BUY','USER_CLOSE']]
print(json.dumps(dict(paperActions=len(paper),unowned=sum(not r.get('authenticatedOwner') for r in paper),journalExists=p.exists())))
