"""Replay captured inputs with the exact live evaluator, without imports that initialize FCM."""
import argparse
import hashlib
import json
import pathlib
import sqlite3
import sys
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'scratch'))
from cryptog.evaluation import evaluate
from cryptog.storage import canonical, decode_event

def replay(database):
    uri=pathlib.Path(database).resolve().as_uri()+'?mode=ro'
    db=sqlite3.connect(uri,uri=True)
    results=[]
    for (raw,) in db.execute("SELECT payload FROM events WHERE kind='EVALUATION' ORDER BY at_ms,id"):
        event=decode_event(raw)
        actual=evaluate(event['input'])
        results.append({'atMs':event['input']['atMs'],'equal':canonical(actual)==canonical(event['decision']),
                        'inputSha256':hashlib.sha256(canonical(event['input']).encode()).hexdigest(),
                        'status':actual['status']})
    db.close()
    return {'evaluations':len(results),'mismatches':sum(not r['equal'] for r in results),
            'results':results,'profitability':'UNVERIFIED','historicalDepth':'Only captured actual snapshots are replayed'}

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('database');parser.add_argument('--output',required=True)
    args=parser.parse_args()
    report=replay(args.database)
    pathlib.Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='results'}))
    sys.exit(1 if report['mismatches'] else 0)
