"""Reproduce saved-input evaluation locally. No network, clock reads or notifications."""
import json,sys
from pathlib import Path
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root/'scratch'))
from cryptog.evaluation import evaluate
source=Path(sys.argv[1]);destination=Path(sys.argv[2])
s=json.loads(source.read_text(encoding='utf-8-sig'));a=evaluate(s);assert a==evaluate(s)
destination.write_text(json.dumps(a,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'status':a['status'],'reasons':a['reasons'],'research':[{'label':r['label'],'status':r['status'],'reasons':r['reasons']} for r in a['research']]},ensure_ascii=False))
