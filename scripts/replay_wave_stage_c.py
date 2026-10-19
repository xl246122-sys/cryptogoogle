"""Replay frozen B causal events through C persistence, without sending or trading."""
import csv
import hashlib
import json
from pathlib import Path
import sys
import tempfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scratch'))
from cryptog.wave_integration import WaveIntegration


def main():
    source=ROOT/'audit/btc-stage-b-20261018';out=ROOT/'audit/wave-stage-c-20261018';out.mkdir(exist_ok=True)
    path=source/'observed-events.csv';manifest=json.loads((source/'result-manifest.json').read_text())
    source_hash=hashlib.sha256(path.read_bytes()).hexdigest()
    assert source_hash==manifest['outputs']['observed-events']
    # One frozen group, all its causal transitions. No selection by trade outcome.
    with path.open(encoding='utf-8',newline='') as fp:
        rows=[r for r in csv.DictReader(fp) if r['branch']=='B-R03']
    mapped={'OBSERVED_DOWN_START':'DOWN_START','OBSERVED_SELL_EXHAUSTION':'SELL_EXHAUSTION',
            'OBSERVED_REBOUND_CONFIRMED':'REBOUND_CONFIRMED','OBSERVED_EVENT_INVALIDATED':'INVALIDATED'}
    counts={};duplicates=0;blocked=0
    with tempfile.TemporaryDirectory() as folder:
        dbpath=str(Path(folder)/'integration.sqlite3');store=WaveIntegration(dbpath)
        try:
            for index,r in enumerate(rows):
                phase=mapped[r['phase']];evidence=json.loads(r['evidence'])
                evidence['stateKey']=f"{r['phase']}:{r['revision']}"
                args=dict(event_id=r['eventId'],parent_id=r['parentEventId'],phase=phase,
                    decision_ms=int(r['decisionTime']),feature_ms=int(r['featureAsOfTime']),evidence=evidence,
                    branch=r['branch'],reason=r['invalidationReason'] or None,source_revision=int(r['revision']))
                # B has no real contemporaneous ask/depth; do not invent one to pass C risk.
                p=store.record(**args)
                assert not p['tradeEligible'] and p['signalType']=='OBSERVE'
                if phase=='REBOUND_CONFIRMED':
                    assert p['risk']['status']=='BLOCKED';blocked+=1
                counts[phase]=counts.get(phase,0)+1
                assert store.enqueue('offline-test-device',p['eventId'],p['revision'])
                assert not store.enqueue('offline-test-device',p['eventId'],p['revision']);duplicates+=1
                if (index+1)%5000==0:print(f'Replayed {index+1}/{len(rows)} causal transitions',flush=True)
            before=store.db.execute('SELECT COUNT(*) FROM wave_history').fetchone()[0]
            store.close();store=WaveIntegration(dbpath)
            assert store.db.execute('SELECT COUNT(*) FROM wave_history').fetchone()[0]==before
            # Receipt is platform acceptance only, not a claimed phone receipt.
            last=rows[-1];p=next(json.loads(r[0]) for r in store.db.execute('SELECT payload FROM wave_events WHERE id=?',(last['eventId'],)))
            assert store.receipt('offline-test-device',p['eventId'],p['revision'],'PLATFORM_ACCEPTED')=='PLATFORM_ACCEPTED'
        finally:store.close()
    result=dict(sourceSha256=source_hash,group='B-R03',inputRows=len(rows),phaseCounts=counts,
        blockedWithoutExecutableQuote=blocked,duplicateDeliveriesSuppressed=duplicates,
        restartHistoryPreserved=True,actualPushes=0,actualTrades=0)
    (out/'replay.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=True))


if __name__=='__main__':main()
