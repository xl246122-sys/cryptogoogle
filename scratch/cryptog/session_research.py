"""Deterministic NYSE core-session research labels; never an entry permission.
Calendar source: https://www.nyse.com/trade/hours-calendars (2026-10-15).
Uncovered years and exceptional closures remain unknown.
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
HOLIDAYS=set('2026-01-01 2026-01-19 2026-02-16 2026-04-03 2026-05-25 2026-06-19 2026-07-03 2026-09-07 2026-11-26 2026-12-25'.split())
EARLY=set('2026-11-27 2026-12-24'.split())
def session_context(now):
    local=datetime.fromtimestamp(now/1000,timezone.utc).astimezone(ZoneInfo('America/New_York'))
    date=local.date().isoformat(); minute=local.hour*60+local.minute
    label='UNKNOWN';delta=None
    if local.year==2026:
        if local.weekday()>=5:label='WEEKEND'
        elif date in HOLIDAYS:label='HOLIDAY'
        else:
            delta=minute-570;close=780 if date in EARLY else 960
            label=('PRE_OPEN' if -30<=delta<0 else 'OPEN_WINDOW' if 0<=delta<60 else 'CORE' if 630<=minute<close else 'POST_CLOSE' if close<=minute<close+30 else 'OFF_CORE')
    return {'version':'nyse-2026-v1','label':label,'minutesFromOpen':delta,'localTime':local.isoformat(),'earlyClose':date in EARLY,'exceptionalClosuresVerified':False,'entryPermission':False}

def shock_measure(bars,window):
    # Reserve last three closed bars for recovery. Peak must precede trough;
    # intrabar OHLC ordering is unknown and never assumed.
    segment=bars[-(window+3):-3]
    pairs=[((a['high']-b['low'])/a['high']*100,a,b) for i,a in enumerate(segment) for b in segment[i+1:]]
    if not pairs:return {'dropPct':0.,'window':window,'reclaim':False}
    drop,peak,trough=max(pairs,key=lambda p:p[0])
    return {'dropPct':drop,'window':window,'reclaim':bars[-1]['close']>trough['high'],'troughTime':trough['close_time']}
