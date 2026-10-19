"""Verify exported research evidence without changing it or contacting production."""
import json
import pandas as pd
from research_btc_stage_b import OUT, ROOT, sha


def main():
    manifest=json.loads((OUT/'result-manifest.json').read_text())
    protocol=json.loads((OUT/'protocol.json').read_text(encoding='utf-8'))
    assert manifest['scenarioCount']==63 and manifest['baselineNineScenariosReproduced']
    assert not manifest['productionEnabled']
    assert sha(ROOT/'scripts/research_btc_stage_b.py')==manifest['scriptSha256']
    assert sha(OUT/'protocol.json')==manifest['protocolSha256']
    for name,digest in manifest['outputs'].items(): assert sha(OUT/(name+'.csv'))==digest,name
    for name,digest in protocol['sources'].items(): assert sha(ROOT/name)==digest,name
    summary=pd.read_csv(OUT/'summary.csv')
    assert len(summary)==189
    assert len(summary[['method','costPct','delayMinutes']].drop_duplicates())==63
    events=pd.read_csv(OUT/'observed-events.csv')
    assert (events.featureAsOfTime<=events.decisionTime).all()
    assert events.receivedTime.isna().all()
    assert events.phase.str.startswith('OBSERVED_').all()
    assert not events.duplicated(['eventId','revision']).any()
    risk=pd.read_csv(OUT/'risk-observations.csv')
    assert (risk.featureAsOfTime<=risk.decisionTime).all()
    assert (risk.decisionTime>=risk.confirmMs).all()
    pos=pd.read_csv(OUT/'position-observations.csv')
    assert (pos.featureAsOfTime<=pos.decisionTime).all()
    opened=pos[pos.phase=='OBSERVED_POSITION_OPENED'].set_index('positionId')
    closed=pos[pos.phase=='OBSERVED_POSITION_CLOSED'].set_index('positionId')
    assert not opened.index.duplicated().any()
    assert set(opened.index)==set(closed.index)
    assert (closed.remainingQuantity==0).all()
    for t in pos[pos.phase=='OBSERVED_HOLDING_EXHAUSTION'].itertuples():
        assert opened.loc[t.positionId].decisionTime<=t.decisionTime<=closed.loc[t.positionId].decisionTime
        evidence=json.loads(t.evidence)
        if evidence['estimatedNetPct']<=0: assert evidence['wording']=='风险退出提醒'
    pairs=pd.read_csv(OUT/'paired-exits.csv')
    trades=pd.read_csv(OUT/'trades.csv');base=trades[trades.method=='B-R00']
    for mode in ['E1','E2']:
        paired=pairs[pairs['mode']==mode]
        merged=paired.merge(base,on=['costPct','delayMinutes','openedMs','parentIndex'],suffixes=('_pair','_base'),validate='one_to_one')
        assert len(merged)==len(base)==len(paired)
        assert ((merged.notional_pair-merged.notional_base).abs()<1e-9).all()
        assert ((merged.entry_pair-merged.entry_base).abs()<1e-9).all()
    print('PASS: 63 scenarios / 189 segment rows; 9 baseline reproductions; source/output hashes; causal timestamps; position lifecycle; 18 paired comparisons.')


if __name__=='__main__': main()
