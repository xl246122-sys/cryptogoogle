"""Real previously viewed history: prefix causality check, not OOS evidence."""
import json
import sys
from pathlib import Path
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from run_wave_shadow import detect

def main():
    df=pd.read_csv(ROOT/'audit/btc-dynamic-study-20261018/input-181days.csv')
    # Choose a large historical down minute to ensure this exercises actual events.
    changes=df.close.pct_change()
    index=int(changes.iloc[-5*1440:-60].idxmin())
    df=df.iloc[:index+12]
    day=int(df.time.iloc[-1])//86400000*86400000
    df=df[df.time>=day-92*86400000].reset_index(drop=True)
    old=df.iloc[:-1].reset_index(drop=True)
    start=day-86400000
    before,_=detect(old,start)
    after,_=detect(df,start)
    cutoff=int(old.time.iloc[-1])+60000
    lower=cutoff-15*60000
    first={k:(at,p) for k,at,p in before if at>=lower}
    second={k:(at,p) for k,at,p in after if lower<=at<=cutoff}
    assert first,'Empty event comparisons are not a detector test'
    assert first==second,'A later minute changed a previously knowable observation'
    assert all(at<=cutoff for _,at,_ in before)
    assert all(p['reason']!='CONFIRM_TIMEOUT' or at-int(p['eventId'].split(':')[-1])==31*60000 for _,at,p in after)
    print(json.dumps(dict(test='PREFIX_CAUSALITY_PREVIOUSLY_VIEWED_HISTORY',passed=True,
        prefixEvents=len(before),extendedEvents=len(after),comparedEvents=len(first),oosEvidence=False)))

if __name__=='__main__':main()
