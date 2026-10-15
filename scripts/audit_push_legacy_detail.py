import json,datetime
from pathlib import Path
p=Path('/opt/shotcrypto/model_library');rows=[json.loads(l) for l in (p/'alerts.jsonl').read_text().splitlines() if l.strip()]
print(json.dumps([{k:r.get(k) for k in ('alertId','alertedAtCst','engineVersion','strategy','strategyNameZh','reasonZh','entryPrice')} for r in rows[-3:]],ensure_ascii=False))
print(json.dumps({'deliveryFileExists':(p/'delivery_events.jsonl').exists()}))
