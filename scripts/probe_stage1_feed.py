"""Read-only public-market smoke test. No daemon import, credentials, FCM or order API."""
import argparse
import json
import pathlib
import sys
import threading
import time
root=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'scratch'))
if (root/'.tools/stage1deps').exists(): sys.path.insert(0,str(root/'.tools/stage1deps'))
from cryptog.market import MarketCache
from cryptog.feed import BinanceFeed
from cryptog.evaluation import evaluate
from cryptog.storage import EventStore

parser=argparse.ArgumentParser();parser.add_argument('--seconds',type=int,default=40);parser.add_argument('--name',default='public-feed');args=parser.parse_args()
if not args.name.replace('-','').isalnum(): raise ValueError('Simple file name required')
cache=MarketCache();stop=threading.Event();feed=BinanceFeed(cache,stop)
folder=root/'audit/stage1';folder.mkdir(exist_ok=True)
store=EventStore(folder/(args.name+'.sqlite3'))
healthy=0;count=0;latencies=[];errors=[];issues={}
feed.start()
try:
    for _ in range(args.seconds):
        stop.wait(1)
        snap=cache.snapshot(int(time.time()*1000))
        start=time.perf_counter();decision=evaluate(snap);latencies.append((time.perf_counter()-start)*1000)
        store.record_evaluation(snap,decision);count+=1
        healthy+=int(snap['healthy'])
        for issue in snap['issues']: issues[issue]=issues.get(issue,0)+1
        if feed.error and feed.error not in errors: errors.append(feed.error)
finally:
    stop.set();feed.join(10);store.close()
latencies.sort()
report={'source':'PUBLIC_BINANCE_SPOT_READ_ONLY','samples':count,'healthySamples':healthy,'errors':errors,
        'issueCounts':issues,
        'evaluationMs':{str(p):latencies[min(len(latencies)-1,int((len(latencies)-1)*p/100))] for p in (50,95,99)},
        'phoneDeliveryMeasured':False,'profitability':'UNVERIFIED'}
(folder/(args.name+'-report.json')).write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report))
sys.exit(0 if healthy else 2)
