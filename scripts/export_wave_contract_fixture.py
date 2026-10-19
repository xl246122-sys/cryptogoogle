"""Generate frontend integration fixtures through the actual backend contract."""
import json
from pathlib import Path
import sys
import tempfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scratch'))
from cryptog.wave_integration import WaveIntegration


def main():
    now=1800000000000
    config=dict(protocolId='C-CONTRACT-TEST-NOT-PRODUCTION',minStopPct=.35,maxStopPct=2.,minNetPct=.8,
        minRR=1.2,costPct=.24,maxQuoteAgeMs=10000,maxHoldMinutes=360,priceMode='REFERENCE_PLUS_ROUND_TRIP_COST')
    plan=dict(entryLow=99.9,entryHigh=100.1,stop=99.5,target=101.5,expiresAt=now+60000)
    quote=dict(ask=100.,bid=101.,atMs=now,healthy=True)
    with tempfile.TemporaryDirectory() as folder:
        store=WaveIntegration(str(Path(folder)/'fixture.sqlite3'));messages=[]
        try:
            for i,phase in enumerate(['DOWN_START','SELL_EXHAUSTION','REBOUND_CONFIRMED']):
                messages.append(store.record(event_id='contract-event',parent_id='contract-parent',phase=phase,
                    decision_ms=now+i,feature_ms=now+i,evidence={'stateKey':phase,'说明':'自动化联调样本，非真实行情'},
                    plan=plan,config=config,quote=quote))
            actions=[dict(eventId='manual-paper-buy',actedAtMs=now,recordType='SIM_BUY',strategy='QUICK_PAPER_V2',
                entryPrice=100,positionSize=500,costSnapshot=dict(frictionPct=.24,applicableAtMs=now,costModelVersion='test'))]
            messages.append(store.observe_paper(actions,'fixture-owner',event_id='contract-position',parent_id='paper-parent',
                decision_ms=now+3,feature_ms=now+3,evidence={'stateKey':'E1'},quote=quote))
            store.expire(now+60000)
            messages.append(next(m for m in store.messages() if m['eventId']=='contract-event'))
            target=ROOT/'tests/fixtures/wave_contract.json';target.parent.mkdir(parents=True,exist_ok=True)
            target.write_text(json.dumps(messages,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
        finally:store.close()
    print('Backend-to-APP contract fixture written (synthetic test records only).')


if __name__=='__main__': main()
