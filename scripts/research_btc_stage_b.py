"""Frozen minute-level four-stage ablation. Offline only; never imported by daemon."""
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

from research_btc_dynamic import ROOT, DAY, MINUTE, gate, settle, simulate, metrics
from report_btc_wave_space import event_starts, table
from cryptog.indicators import rsi_series

SOURCE = ROOT/'audit/btc-dynamic-study-20261018'
PREVIOUS = ROOT/'audit/btc-stage-a-20261018'
OUT = ROOT/'audit/btc-stage-b-20261018'
GROUPS = {f'B-R0{i}': rules for i, rules in enumerate([
    ('D0','C0','E0'), ('D1','C0','E0'), ('D2','C0','E0'),
    ('D0','C1','E0'), ('D0','C2','E0'), ('D0','C0','E1'), ('D0','C0','E2')])}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def register():
    OUT.mkdir(parents=True, exist_ok=True)
    spec = dict(version='wave-state-ablation-1', productionEnabled=False,
        sources={str(p.relative_to(ROOT)): sha(p) for p in [
            PREVIOUS/'四阶段标签与实验协议.md', PREVIOUS/'b-experiments-frozen.json',
            PREVIOUS/'reference-opportunities.csv', SOURCE/'input-181days.csv',
            SOURCE/'plans.csv', SOURCE/'warnings.csv', SOURCE/'trades.csv',
            ROOT/'scripts/research_btc_dynamic.py', ROOT/'scratch/cryptog/indicators.py']},
        groups=GROUPS, scenarios=[dict(costPct=c, delayMinutes=d) for c in [.24,.4,.6] for d in [0,1,2]],
        scenarioCount=63, pairedExitComparisons=18,
        clarifications=[
            'D2 windowMin=15 denotes prior support lookback; fast family, target lookback60.',
            'RSI last5 compared to current daily frozen past90d quantile; no current bar in calibration.',
            'X1 observation low = event-through-X1 low; revoke on lower low, may reform on same close.',
            'C2 strict pivot low lower than all four neighbours; tie is not pivot. Previous pivot is nearest confirmed pivot, including pre-event history.',
            'C2 new pivot center must be strictly after X1. Bounce high is maximum high strictly between consecutive pivots. Break can occur on pivot availability close.',
            'C1/C2 confirmation strictly after X1; event deadline30m. Confirmed plan lifetime is inherited single scheduled execution, not repeated retries.',
            'E1/E2 overbought background restricted to closed bars while position exists. ATR14 is simple TR mean as common diagnostic model.',
            'Exit at next open plus scenario delay. Before due open normal E0; at due open gap-stop, gap-target, then reminder exit, before later intrabar prices.',
            'Historical receivedTime unknown; decisionTime assumes zero feed latency at minute close, not measured. No depth inference.',
            'Whole position research only. No partial-fill/mobile/production state-machine claim.'],
        status='SEEN_HISTORY_DIAGNOSTIC_NO_PROMOTION')
    p=OUT/'protocol.json'; body=json.dumps(spec,ensure_ascii=False,indent=2)+'\n'
    if p.exists() and p.read_text(encoding='utf-8') != body:
        raise ValueError('Frozen protocol or inputs changed')
    if not p.exists(): p.write_text(body,encoding='utf-8')
    return spec


def past_quantile(values, boundary, q, negative_only=False, train=90*DAY):
    a=np.asarray(values[boundary-train:boundary])
    if boundary<train or not np.isfinite(a).all(): raise ValueError('Invalid training history')
    if negative_only: a=-a[a<0]
    return float(np.quantile(a,q)) if len(a) else np.inf


def build_features(df,start):
    n=len(df); bars=df[['open','high','low','close']].to_numpy()
    rsi=np.array(rsi_series(df.close.to_list(),14),dtype=float)
    sell=(df.volume-df.taker_buy_base).to_numpy()
    ret={w:(df.close.pct_change(w)*100).to_numpy() for w in [1,5]}
    levels={key:np.full(n,np.nan) for key in ['rsi10','rsi90','sell90','ret1','ret5']}
    records=[]
    for at in range(start,n,DAY):
        v={'rsi10':past_quantile(rsi,at,.1),'rsi90':past_quantile(rsi,at,.9),
           'sell90':past_quantile(sell,at,.9),
           **{f'ret{w}':past_quantile(ret[w],at,.95,True) for w in [1,5]}}
        for key,value in v.items(): levels[key][at:at+DAY]=value
        records.append(dict(effectiveMs=int(df.time.iloc[at]),trainingEndExclusiveMs=int(df.time.iloc[at]),**v))
    prev=np.r_[bars[0,3],bars[:-1,3]]
    tr=np.maximum(bars[:,1]-bars[:,2],np.maximum(abs(bars[:,1]-prev),abs(bars[:,2]-prev)))
    atr=pd.Series(tr).rolling(14).mean().to_numpy()
    support=df.low.shift().rolling(15).min().to_numpy()
    accelerating=(ret[1]<0)&(ret[1]<np.r_[np.nan,ret[1][:-1]])
    masks={'D1':{w:accelerating&(-ret[w]>=levels[f'ret{w}']) for w in [1,5]},
           'D2':{15:(bars[:,3]<support)&(sell>=levels['sell90'])&(sell>0)}}
    for group in masks.values():
        for a in group.values(): a[:start]=False
    vol=df.volume.to_numpy()
    rs=pd.Series(rsi)
    r_up=(rsi>np.roll(rsi,1))&(np.roll(rsi,1)>np.roll(rsi,2))
    lows=bars[:,2]; l_up=(lows>=np.roll(lows,1))&(np.roll(lows,1)>=np.roll(lows,2))
    s2=pd.Series(sell).rolling(2).sum().to_numpy();v2=pd.Series(vol).rolling(2).sum().to_numpy()
    s3=pd.Series(sell).shift(2).rolling(3).sum().to_numpy();v3=pd.Series(vol).shift(2).rolling(3).sum().to_numpy()
    ratio2=np.divide(s2,v2,out=np.full(n,np.nan),where=v2>0)
    ratio3=np.divide(s3,v3,out=np.full(n,np.nan),where=v3>0)
    weaker=ratio2<ratio3
    x=(rs.rolling(5).min().to_numpy()<levels['rsi10'])&(r_up.astype(int)+l_up.astype(int)+weaker.astype(int)>=2)
    pivots=np.full(n,-1,dtype=int)
    for center in range(2,n-2):
        if lows[center]<min(lows[center-2],lows[center-1],lows[center+1],lows[center+2]):
            pivots[center+2]=center
    return dict(bars=bars,rsi=rsi,atr=atr,levels=levels,masks=masks,x=x,pivots=pivots,lastPivot=np.maximum.accumulate(pivots),
                rsiRise=r_up,lowRise=l_up,sellRatio2=ratio2,sellRatio3=ratio3),pd.DataFrame(records)


def confirmation(f,i,mode):
    bars=f['bars']; active=None; floor=None; transitions=[]
    last_pivot=int(f['lastPivot'][i]) if mode=='C2' and f['lastPivot'][i]>=0 else None
    bounce=None
    for j in range(i+1,min(i+31,len(bars))):
        if active is not None and bars[j,2]<floor:
            transitions.append((j,'OBSERVED_DOWN_START','X1_LOW_BROKEN',{}))
            active=None;bounce=None
        new=int(f['pivots'][j])
        if mode=='C2' and new>=0:
            if active is not None and new>active and last_pivot is not None and bars[new,2]>bars[last_pivot,2]:
                bounce=float(bars[last_pivot+1:new,1].max()) if new>last_pivot+1 else None
            else: bounce=None
            last_pivot=new
        green=bars[j,3]>bars[j,0] and bars[j,3]>bars[j-1,1]
        passed=green if mode=='C0' else (active is not None and j>active and
                    (green if mode=='C1' else bounce is not None and bars[j,3]>bounce))
        if passed: return j,transitions
        if mode!='C0' and active is None and f['x'][j]:
            active=j;floor=float(bars[i:j+1,2].min())
            transitions.append((j,'OBSERVED_SELL_EXHAUSTION',None,
                dict(observationLow=floor,rsi=float(f['rsi'][j]),rsiP10=float(f['levels']['rsi10'][j]),
                     rsiRise=bool(f['rsiRise'][j]),lowRise=bool(f['lowRise'][j]),
                     sellRatio2=float(f['sellRatio2'][j]) if np.isfinite(f['sellRatio2'][j]) else None,
                     sellRatio3=float(f['sellRatio3'][j]) if np.isfinite(f['sellRatio3'][j]) else None)))
    return None,transitions


def event_row(df,group,w,i,parent,j,phase,reason=None,evidence=None):
    return dict(eventId=f'{group}:{w}:{i}',parentEventId=f'{group}:{parent}',module='REVERSAL_RESEARCH',
        branch=group,phase=phase,exchangeTime=int(df.time.iloc[j]+MINUTE-1),receivedTime=None,
        decisionTime=int(df.time.iloc[j]+MINUTE),featureAsOfTime=int(df.time.iloc[j]+MINUTE),
        ruleVersion='wave-state-ablation-1',dataSnapshotHash=sha_cached(),dataHealth='VALID_MINUTE_OHLCV_DEPTH_UNKNOWN',
        labelSource='CAUSAL_MINUTE_REPLAY_ASSUMED_ZERO_FEED_DELAY',invalidationReason=reason,
        evidence=json.dumps(evidence or {},ensure_ascii=False),windowMin=w,triggerIndex=i,parentIndex=parent)


def sha_cached():
    return '28720fd4d5da12836425b9c1a82021c0d3396000c22c62e43f917008e8edc465'


def make_plans(df,f):
    old=pd.read_csv(SOURCE/'warnings.csv');old=old[old.method=='ROLLING_P95']
    original=pd.read_csv(SOURCE/'plans.csv');original=original[original.method=='ROLLING_P95']
    d_events={'D0':[(int(t.windowMin),int(t.triggerIndex),int(t.parentIndex)) for t in old.itertuples()]}
    for d,masks in f['masks'].items():
        parents=event_starts(np.logical_or.reduce(list(masks.values())))
        d_events[d]=[(w,int(i),int(parents[np.searchsorted(parents,i,side='right')-1]))
                     for w,mask in masks.items() for i in event_starts(mask)]
    plans={};logs=[];warnings=[]
    for group,(d,c,e) in GROUPS.items():
        current=[]
        for w,i,parent in d_events[d]:
            logs.append(event_row(df,group,w,i,parent,i,'OBSERVED_DOWN_START',evidence=dict(detector=d)))
            j,transitions=confirmation(f,i,c)
            warnings.append(dict(method=group,windowMin=w,triggerIndex=i,parentIndex=parent,
                                 triggerMs=int(df.time.iloc[i]+MINUTE),confirmIndex=j,confirmed=j is not None))
            for k,phase,reason,ev in transitions: logs.append(event_row(df,group,w,i,parent,k,phase,reason,ev))
            if j is None:
                k=min(i+30,len(df)-1)
                logs.append(event_row(df,group,w,i,parent,k,'OBSERVED_EVENT_INVALIDATED',
                                     'CONFIRM_TIMEOUT' if i+30<len(df) else 'DATA_END_CENSORED'))
                continue
            ref=float(f['bars'][j,3]);target=float(f['bars'][i-max(w,60):i,1].max())*.9985
            stop=min(float(f['bars'][i:j+1,2].min())-.15*f['atr'][j],ref*.9965)
            p=dict(method=group,windowMin=w,triggerIndex=i,parentIndex=parent,confirmIndex=j,
                   confirmMs=int(df.time.iloc[j]+MINUTE),reference=ref,entryLow=ref*.999,entryHigh=ref*1.001,
                   target=target,stop=stop,holdMinutes=30 if w<=15 else 360,minNet=.8 if w<=15 else 1.)
            current.append(p)
            logs.append(event_row(df,group,w,i,parent,j,'OBSERVED_REBOUND_CONFIRMED',evidence=dict(
                confirmation=c,entryLow=p['entryLow'],entryHigh=p['entryHigh'],stop=stop,target=target,riskStatus='PENDING_EXECUTION_PRICE')))
        plans[group]=sorted(current,key=lambda p:(p['confirmIndex'],p['triggerIndex'],p['windowMin']))
    # Saved baseline plans are independent evidence, not silently substituted for the new implementation.
    baseline=pd.DataFrame(plans['B-R00']).drop(columns='method').reset_index(drop=True)
    pd.testing.assert_frame_equal(baseline,original.drop(columns='method').reset_index(drop=True),check_dtype=False,rtol=1e-12)
    log_frame=pd.DataFrame(logs)
    log_frame['revision']=log_frame.groupby('eventId').cumcount()+1
    return plans,pd.DataFrame(warnings),log_frame


def exit_signal(f,k,j,mode):
    r=f['rsi'];bars=f['bars']
    if j<k+2 or not np.any(r[max(k,j-4):j+1]>f['levels']['rsi90'][j]): return False
    if mode=='E1': return bool(r[j]<r[j-1]<r[j-2] and bars[j,3]<bars[j-1,2])
    return bool(bars[j,3]<bars[j-1,3]<bars[j-2,3] and
                bars[k:j+1,3].max()-bars[j,3]>=.3*f['atr'][j])


def settle_exit(f,k,hold,stop,target,mode,delay):
    bars=f['bars']
    if mode=='E0':
        a=settle(bars,k,hold,stop,target)
        return (*a,None) if a else None
    if k+hold>len(bars): return None
    reminder=None;due=None
    for j in range(k,k+hold):
        op,hi,lo,cl=bars[j]
        if op<=stop: return j,float(op),'STOP_GAP',reminder
        if due is not None and j>=due:
            if op>=target: return j,float(target),'TARGET',reminder
            return j,float(op),'EXHAUSTION_EXIT',reminder
        if lo<=stop: return j,float(stop),'STOP',reminder
        if hi>=target: return j,float(target),'TARGET',reminder
        if j<k+hold-1 and due is None and exit_signal(f,k,j,mode): reminder=j;due=j+1+delay
    return k+hold-1,float(bars[k+hold-1,3]),'TIME',reminder


def simulate_group(df,plans,start,cost,delay,f,mode):
    if mode=='E0': return simulate(df,plans,start,cost,delay)
    bars=f['bars'];times=df.time.to_numpy();trades=[];counts={};used=set();busy=-1
    equity=500.;curve=np.full(len(df)-start,500.);cursor=start
    for p in plans:
        k=p['confirmIndex']+1+delay
        issue=None
        if k>=len(df): issue='tail'
        elif p['parentIndex'] in used: issue='parent_duplicate'
        elif k<=busy: issue='position_busy'
        else:
            during=bars[p['confirmIndex']+1:k]
            if len(during) and ((during[:,2]<=p['stop']).any() or (during[:,1]>=p['target']).any()): issue='invalid_during_delay'
            else: issue=gate(p,float(bars[k,0]),cost)
        if issue: counts[issue]=counts.get(issue,0)+1;continue
        result=settle_exit(f,k,p['holdMinutes'],p['stop'],p['target'],mode,delay)
        if result is None: counts['tail']=counts.get('tail',0)+1;continue
        end,price,outcome,reminder=result;entry=float(bars[k,0]);risk=(1-p['stop']/entry)*100
        net=(price/entry-1)*100-cost;fraction=min(1,.5/(risk+cost));notional=equity*fraction
        curve[cursor-start:k-start]=equity
        curve[k-start:end+1-start]=equity*(1+fraction*((bars[k:end+1,3]/entry-1)-cost/100))
        equity+=notional*net/100;curve[end-start]=equity;cursor=end+1;busy=end;used.add(p['parentIndex'])
        trades.append(dict(method=p['method'],windowMin=p['windowMin'],costPct=cost,delayMinutes=delay,
            openedMs=int(times[k]),closedMs=int(times[end]+MINUTE),parentIndex=p['parentIndex'],entry=entry,
            stop=p['stop'],target=p['target'],exit=price,outcome=outcome,netPct=net,r=net/(risk+cost),
            holdMinutes=end-k+1,notional=notional,equityAfter=equity,plannedNetPct=(p['target']/entry-1)*100-cost,
            reminderMs=int(times[reminder]+MINUTE) if reminder is not None else None,
            executionMs=int(times[end]) if outcome=='EXHAUSTION_EXIT' else None))
    curve[cursor-start:]=equity;peak=np.maximum.accumulate(np.r_[500.,curve])[1:]
    return trades,counts,dict(final=equity,minuteCloseDrawdownPct=float(((curve/peak-1)*100).min())),curve


def paired_exits(df,f,base,cost,delay,mode):
    rows=[];times=df.time.to_numpy()
    for t in base:
        k=int(np.searchsorted(times,t['openedMs']));hold=30 if t['windowMin']<=15 else 360
        end,price,outcome,reminder=settle_exit(f,k,hold,t['stop'],t['target'],mode,delay)
        net=(price/t['entry']-1)*100-cost
        rows.append(dict(mode=mode,costPct=cost,delayMinutes=delay,openedMs=t['openedMs'],
            parentIndex=t['parentIndex'],entry=t['entry'],notional=t['notional'],baseNetPct=t['netPct'],
            newNetPct=net,deltaNetPct=net-t['netPct'],deltaUSDT=t['notional']*(net-t['netPct'])/100,
            outcome=outcome,closedMs=int(times[end]+MINUTE),reminderMs=int(times[reminder]+MINUTE) if reminder is not None else None))
    return rows


def execution_audit(df,f,plans,trades,cost,delay,group):
    """Causal risk observations and actual simulated position-linked reminders."""
    risks=[];events=[];bars=f['bars'];times=df.time.to_numpy()
    for p in plans:
        j=p['confirmIndex'];k=j+1+delay
        if k>=len(df): continue
        during=bars[j+1:k];price=float(bars[k,0])
        invalid=bool(len(during) and ((during[:,2]<=p['stop']).any() or (during[:,1]>=p['target']).any()))
        issue='invalid_during_delay' if invalid else gate(p,price,cost)
        risks.append(dict(method=group,costPct=cost,delayMinutes=delay,eventId=f"{group}:{p['windowMin']}:{p['triggerIndex']}",
            decisionTime=int(times[k]),featureAsOfTime=int(times[k]),confirmMs=p['confirmMs'],
            riskStatus='REJECT' if issue else 'PASS',reason=issue,entryReference=price,
            netTargetPct=(p['target']/price-1)*100-cost,stopDistancePct=(1-p['stop']/price)*100,
            labelNamespace='OBSERVED',note='Risk-only evaluation, not account availability or guaranteed fill'))
    lookup={(p['parentIndex'],p['confirmIndex']+1+delay,p['windowMin']):p for p in plans}
    for t in trades:
        k=int(np.searchsorted(times,t['openedMs']));p=lookup[t['parentIndex'],k,t['windowMin']]
        position=f"{group}:{cost}:{delay}:{k}"
        base=dict(positionId=position,positionVersion=1,remainingQuantity=t['notional']/t['entry'],
                  costVersion=f'ROUND_TRIP_{cost}',costPct=cost,delayMinutes=delay,
                  costBasis=t['entry'],labelNamespace='OBSERVED')
        row=event_row(df,group,p['windowMin'],p['triggerIndex'],p['parentIndex'],k,'OBSERVED_POSITION_OPENED')
        # Entry is at open, not the close of the entry candle.
        row.update(base,exchangeTime=int(times[k]),decisionTime=int(times[k]),featureAsOfTime=int(times[k]))
        events.append(row)
        reminder=t.get('reminderMs')
        if reminder is not None:
            j=int(np.searchsorted(times,reminder))-1
            mark=(bars[j,3]/t['entry']-1)*100-cost
            row=event_row(df,group,p['windowMin'],p['triggerIndex'],p['parentIndex'],j,
                'OBSERVED_HOLDING_EXHAUSTION',evidence=dict(rsi=float(f['rsi'][j]),
                rsiP90=float(f['levels']['rsi90'][j]),estimatedNetPct=float(mark),
                wording='利润保护提醒' if mark>0 else '风险退出提醒',quoteSource='MINUTE_CLOSE_PROXY_NOT_EXECUTABLE_BID'))
            row.update(base);events.append(row)
        end=k+t['holdMinutes']-1
        row=event_row(df,group,p['windowMin'],p['triggerIndex'],p['parentIndex'],end,
            'OBSERVED_POSITION_CLOSED',evidence=dict(exitReason=t['outcome'],exitReference=t['exit']))
        row.update(base,positionVersion=2,remainingQuantity=0.)
        if t.get('executionMs') is not None:
            row.update(exchangeTime=t['executionMs'],decisionTime=t['executionMs'],featureAsOfTime=t['executionMs'])
        events.append(row)
    return risks,events


def main():
    spec=register()
    if '--register-only' in sys.argv: print('REGISTERED');return
    if sha(SOURCE/'input-181days.csv')!=sha_cached(): raise ValueError('Data snapshot mismatch')
    df=pd.read_csv(SOURCE/'input-181days.csv');start=len(df)-90*DAY
    f,levels=build_features(df,start);print('FEATURES_READY',flush=True)
    plans,warnings,logs=make_plans(df,f);print('PLANS_READY',flush=True)
    alltrades=[];summaries=[];rejections=[];pairs=[];baselines={};risklogs=[];positionlogs=[]
    curves={'time':df.time.iloc[start:].to_numpy()}
    split=int(df.time.iloc[start+60*DAY]);old=pd.read_csv(SOURCE/'trades.csv')
    for group,(_,_,mode) in GROUPS.items():
        for s in spec['scenarios']:
            cost,delay=s['costPct'],s['delayMinutes']
            trades,counts,cap,curve=simulate_group(df,plans[group],start,cost,delay,f,mode)
            if group=='B-R00':
                prev=old[(old.method=='ROLLING_P95')&(old.costPct==cost)&(old.delayMinutes==delay)].drop(columns='method').reset_index(drop=True)
                now=pd.DataFrame(trades).drop(columns='method').reset_index(drop=True)
                pd.testing.assert_frame_equal(now,prev,check_dtype=False,rtol=1e-11)
                baselines[cost,delay]=trades
            if mode!='E0': pairs.extend(paired_exits(df,f,baselines[cost,delay],cost,delay,mode))
            risk_events,position_events=execution_audit(df,f,plans[group],trades,cost,delay,group)
            risklogs.extend(risk_events);positionlogs.extend(position_events)
            for t in trades:
                k=int(np.searchsorted(df.time.to_numpy(),t['openedMs']));end=k+t['holdMinutes']-1
                peak=float(((f['bars'][k:end,3]/t['entry']-1)*100-cost).max()) if end>k else None
                t.update(grossPct=t['netPct']+cost,positiveThenLoss=bool(peak is not None and peak>0 and t['netPct']<0),
                         preExitClosedPeakNet=peak,labelNamespace='OUTCOME',rightCensored=False,
                         sameBarStopTargetAmbiguous=bool(f['bars'][end,2]<=t['stop'] and f['bars'][end,1]>=t['target']))
            alltrades.extend(trades)
            rejections.extend(dict(method=group,**s,reason=r,count=n) for r,n in counts.items())
            if cost==.24 and delay==1: curves[group]=curve
            for segment in ['ALL90','FIRST60','TAIL30']:
                rows=trades
                if segment=='FIRST60': rows=[t for t in trades if t['openedMs']<split and t['closedMs']<=split]
                elif segment=='TAIL30': rows=[t for t in trades if t['openedMs']>=split]
                summaries.append(dict(method=group,**s,segment=segment,**metrics(rows),
                    grossMeanPct=np.mean([t['grossPct'] for t in rows]) if rows else None,
                    positiveThenLoss=sum(t['positiveThenLoss'] for t in rows),
                    stopCount=sum(t['outcome'].startswith('STOP') for t in rows),targetCount=sum(t['outcome']=='TARGET' for t in rows),
                    timeCount=sum(t['outcome']=='TIME' for t in rows),exitCount=sum(t['outcome']=='EXHAUSTION_EXIT' for t in rows),
                    finalUSDT=cap['final'] if segment=='ALL90' else None,
                    minuteCloseDrawdownPct=cap['minuteCloseDrawdownPct'] if segment=='ALL90' else None))
        print(group+' COMPLETE',flush=True)
    summary=pd.DataFrame(summaries);paired=pd.DataFrame(pairs)
    pair_summary=paired.groupby(['mode','costPct','delayMinutes']).agg(trades=('newNetPct','size'),
        baseMeanNetPct=('baseNetPct','mean'),newMeanNetPct=('newNetPct','mean'),meanDeltaPct=('deltaNetPct','mean'),deltaUSDT=('deltaUSDT','sum')).reset_index()
    opps=pd.read_csv(PREVIOUS/'reference-opportunities.csv');coverage=[]
    for group in GROUPS:
        for o in opps.to_dict('records'):
            w=warnings[(warnings.method==group)&((warnings.windowMin<=15) if o['profile']=='FAST' else (warnings.windowMin>15))]
            match=w[(w.triggerMs>=o['confirmMs']-30*MINUTE)&(w.triggerMs<=o['confirmMs'])]
            coverage.append(dict(method=group,**o,warningCovered=bool(len(match)),labelNamespace='OUTCOME_REFERENCE'))
    coverage=pd.DataFrame(coverage)
    cover_summary=coverage[coverage.success].groupby(['method','profile']).agg(successfulReferences=('success','size'),warned=('warningCovered','sum')).reset_index()
    latency=warnings[warnings.confirmed].copy()
    latency['confirmationDelayMinutes']=latency.confirmIndex-latency.triggerIndex
    latency=latency.groupby('method').confirmationDelayMinutes.agg(['count','mean','median','max']).reset_index()
    files={'thresholds':levels,'warnings':warnings,'observed-events':logs,'plans':pd.DataFrame([p for v in plans.values() for p in v]),
           'trades':pd.DataFrame(alltrades),'summary':summary,'rejections':pd.DataFrame(rejections),
           'risk-observations':pd.DataFrame(risklogs),'position-observations':pd.DataFrame(positionlogs),'confirmation-latency':latency,
           'paired-exits':paired,'paired-summary':pair_summary,'reference-coverage-detail':coverage,
           'reference-coverage':cover_summary,'primary-equity':pd.DataFrame(curves)}
    for name,frame in files.items(): frame.to_csv(OUT/(name+'.csv'),index=False)
    report(summary,pair_summary,cover_summary,logs,warnings,latency)
    manifest=dict(scenarioCount=63,baselineNineScenariosReproduced=True,productionEnabled=False,
        scriptSha256=sha(__file__),protocolSha256=sha(OUT/'protocol.json'),outputs={n:sha(OUT/(n+'.csv')) for n in files})
    (OUT/'result-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(summary[(summary.costPct==.24)&(summary.delayMinutes==1)&(summary.segment=='ALL90')].to_string(index=False))


def report(summary,pairs,coverage,logs,warnings,latency):
    main=summary[(summary.costPct==.24)&(summary.delayMinutes==1)&(summary.segment=='ALL90')]
    names={'B-R00':'原P95基线','B-R01':'下跌加速D1','B-R02':'破位卖压D2','B-R03':'衰竭后确认C1',
           'B-R04':'更高低点确认C2','B-R05':'超买乏力退出E1','B-R06':'超买回撤退出E2'}
    display=main[['method','trades','winPct','grossMeanPct','meanNetPct','bootstrapLower95','profitFactor','positiveThenLoss','finalUSDT','minuteCloseDrawdownPct']].copy()
    display['method']=display.method.map(names)
    display=display.rename(columns=dict(method='规则',trades='成交数',winPct='净盈利比例%',grossMeanPct='平均毛收益%',meanNetPct='平均净收益%',bootstrapLower95='均值95%下界%',profitFactor='利润因子',positiveThenLoss='先盈后亏笔数',finalUSDT='期末USDT',minuteCloseDrawdownPct='分钟收盘回撤%'))
    phase=logs.groupby(['branch','phase']).size().rename('records').reset_index()
    freq=warnings.groupby('method').agg(windowEvents=('triggerIndex','size'),parentEvents=('parentIndex','nunique'),confirmations=('confirmed','sum')).reset_index()
    lines=['# B阶段：四阶段反转路径首轮消融实验','','已完成7组×3种成本×3种延迟，共63场景。另18组同入场退出配对比较，不新增参数搜索。仅用于已看历史开发诊断；未接入生产或APP。',
        '','## 主场景：来回成本0.24%，额外等待1分钟','',table(display),'',
        '单笔收益以买入名义金额为分母，账户初始500 USDT、每笔风险预算0.5%、最多一仓现货。相对改善不等于正期望；没有独立未见样本，不能晋级。',
        '', '本轮结论：主场景7组平均净收益全部为负。D1/D2和C1/C2的平均毛收益转正，但不足以覆盖0.24%来回成本；C2仅19笔，不能把低交易数带来的较小回撤当成稳定盈利。E1/E2虽缩短持仓，仍未改善完整账户收益，不能直接采用为正式退出规则。',
        '','## 同入场退出配对','',table(pairs[(pairs.costPct==.24)&(pairs.delayMinutes==1)]),'',
        '上述配对固定B-R00每笔入场、名义金额和结构计划，只改变退出。deltaUSDT是固定名义金额的收益差合计，不是重新复利账户。主表E1/E2则重新运行单仓账户，提前退出后可能增加交易；不能把两张表混用。',
        '','## 预警、确认与阶段状态','',table(freq),'',table(phase),'',
        '事件后30分钟确认超时作废；衰竭后破低撤销并允许重新形成。确认标签只表示形态成立，仍需最新模拟成交价通过成本/止损/净利/净RR门禁。预警不受利润门禁拦截。X1与C2只使用当时已知数据，局部低点右侧两根未收盘时不可用。风险逐条记录于risk-observations.csv；持仓提醒记录于position-observations.csv，含positionId、余量和成本版本，净估值为负时使用风险退出文案。提醒时估值不是最终成交利润。',
        '', '确认延迟（分钟，仅已确认窗口事件，尚未经过风险过滤）：','',table(latency),'',
        'C1平均等待约11.55分钟，C2约19.04分钟，基线约4.49分钟。更严格的确认减少候选并显著推迟入场；不能只看胜率略升就忽略等待代价。',
        '','## A阶段固定参考机会覆盖','',table(coverage),'',
        '沿用A阶段1个FAST、7个SLOW成功参考机会，未将本轮盈利交易加入分母。这里只计参考确认前30分钟的同类预警覆盖，不代表正式买入覆盖或全市场漏报率。D1/D2本轮是快周期入口，不覆盖SLOW类别并不等于全系统漏报。样本过少不可据此挑最佳阈值。',
        '','## 时间与成本核算','',
        '- 181天分钟数据，91天预热、90天评估。分位只用刷新前90天，每24小时刷新；RSI采用项目Wilder种子。D1只用负收益样本。全部规则与实现歧义在protocol.json先登记。',
        '- 净收益%=(卖出参考价/买入参考价−1)×100−来回成本%。主场景0.24%=双边taker各0.10%+双边滑点预算各0.02%；另测0.40%、0.60%。没有账户实际费率、盘口价差或真实成交数据，不声称已精确测量成本。',
        '- 所有入场从确认收盘后的开盘再加0/1/2分钟延迟；提醒退出也在下一开盘加同等延迟执行。等待期间止损/目标仍有效，止损跳空按较差开盘。',
        '- 止损0.35%–1.20%、净RR≥1.2、快周期净目标≥0.8%/慢周期>1%暂作统一比较控制，不是恢复为未来模块永久全局限制。结构目标仍取触发前价格，不能为通过净利门禁虚构目标。',
        '- 盈利回吐只使用退出前完整分钟收盘估值，排除退出当柱高点/收盘。分钟内顺序未知仍按原模型止损优先；所有场景剔除完整持有期不足的尾部候选。',
        '- 前60天统计剔除跨切分点交易；尾30天已看过，仅为诊断。summary.csv保留全部189个场景/区间结果，未挑最好成本或延迟。置信区间按入场日聚类bootstrap，样本稀少不代表稳定性。',
        '','## 交付边界与下一步','',
        '本轮完成分钟级研究模块、因果状态记录、退出执行模拟和完整矩阵回放。尚未实现正式S1/S6/S3/S4/S7生产模块、实时Tick盘口、部分卖出监控、手机消息交互或上线部署。后续应根据失败/改善来源登记下一轮模块独立风控与确认实验；未通过开发筛选不能直接上线。',
        '','文件：protocol.json冻结口径；thresholds.csv逐日阈值；observed-events.csv可知阶段记录；warnings/plans/trades.csv逐事件和逐笔；summary/rejections.csv全场景；paired-exits/paired-summary.csv配对；reference-coverage*.csv固定分母；result-manifest.json哈希与基线复现证据。']
    (OUT/'报告.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


if __name__=='__main__': main()
