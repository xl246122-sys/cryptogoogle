"""Read-only evidence summary; unknown delivery and execution remain unknown."""
import argparse
import json
from pathlib import Path
import sqlite3
import time

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--database',required=True)
    parser.add_argument('--output')
    args=parser.parse_args()
    db=sqlite3.connect(Path(args.database).resolve().as_uri()+'?mode=ro',uri=True)
    db.execute('PRAGMA query_only=ON')
    meta={key:json.loads(value) for key,value in db.execute('SELECT key,value FROM meta')}
    start=meta['startMs']
    counts=dict(db.execute("SELECT CASE WHEN at_ms<? THEN 'warmup' ELSE 'prospective' END,count(*) FROM quotes GROUP BY 1",(start,)))
    health=dict(db.execute("SELECT json_extract(payload,'$.healthy'),count(*) FROM quotes WHERE at_ms>=? GROUP BY 1",(start,)))
    latency={}
    for name in ['sourceToReceiveMs','sourceAgeMs']:
        query=f"SELECT CAST(json_extract(payload,'$.{name}') AS REAL) AS v FROM quotes WHERE at_ms>=? AND json_extract(payload,'$.healthy')=1 AND json_extract(payload,'$.{name}') IS NOT NULL"
        n=db.execute('SELECT count(*) FROM ('+query+')',(start,)).fetchone()[0]
        latency[name]={'samples':n,'p50':None,'p95':None}
        for label,q in [('p50',.5),('p95',.95)]:
            if n:latency[name][label]=db.execute(query+' ORDER BY v LIMIT 1 OFFSET ?',(start,int((n-1)*q))).fetchone()[0]
    # Client/server clocks are not aligned; never estimate one-way latency by subtraction.
    receipts=dict(db.execute("SELECT coalesce(json_extract(payload,'$.receiptKind'),'NO_RECEIPT'),count(*) FROM delivery GROUP BY 1"))
    trade_rows=db.execute('''SELECT json_extract(payload,'$.account'),count(*),
        avg(json_extract(payload,'$.netPct')),sum(json_extract(payload,'$.netPct')>0)
        FROM trades GROUP BY 1''').fetchall()
    report=dict(generatedAtMs=int(time.time()*1000),experiment='WAVE-D-20261018-002',
        status=meta.get('status'),startMs=start,quoteCounts=counts,prospectiveHealthCounts=health,
        measuredMarketLatency=latency,baselineTransportReceiptCounts=receipts,
        newWaveDeliveryLatency=None,oneWayPhoneDeliveryLatency=None,
        qualifiedOosTrades=0,promotionEligible=False,
        modelOutcomes=[dict(account=a,trades=n,meanNetPct=m,winRatePct=w/n*100) for a,n,m,w in trade_rows],
        limitations=['Warmup quotes are excluded from prospective statistics',
            'Baseline transport is not proof of new-wave delivery; OPENED is click time',
            'Sampled ask/bid models include the full scenario cost, conservatively adding spread',
            'Sampled model exits cannot establish tick-extreme or actual fill outcomes',
            'Missing real delivery, execution and complete promotion evidence remain disqualifying'])
    db.close()
    body=json.dumps(report,ensure_ascii=False,indent=2)+'\n'
    if args.output:Path(args.output).write_text(body,encoding='utf-8')
    print(body)

if __name__=='__main__':main()
