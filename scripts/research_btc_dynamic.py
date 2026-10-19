"""Registered, causal warning-threshold ablation. Not production S1-S7 backtest."""
import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from report_btc_wave_space import ROOT, COLS, MINUTE, WINDOWS, confirm, event_starts, iso, table
sys.path.insert(0,str(ROOT/'scratch'))
from cryptog.research_protocol import block_bootstrap_lower

DAY=1440
METHODS=['DOCUMENT_FIXED','TRAIN_FROZEN_P95','ROLLING_P90','ROLLING_P95','ROLLING_P99','ADAPTIVE_P95']
FIXED={1:.8,3:1.2,5:.65,15:.9,60:3,240:6,1440:8}
OUT=ROOT/'audit'/'btc-dynamic-study-20261018'
PRIOR=ROOT/'audit'/'btc-wave-study-20261018'


def protocol():
    return dict(version='threshold-ablation-1',status='RESEARCH_ONLY_PREVIOUSLY_VIEWED_HISTORY',
                sampleStart='2026-07-20T06:56:00Z',endExclusive='2026-10-18T06:56:00Z',
                trainDays=90,developmentDays=60,diagnosticTailDays=30,methods=METHODS,
                windowMinutes=WINDOWS,refreshMinutes=1440,
                adaptive='rolling90 P95 * clip(std(last7d 1m returns)/std(last30d 1m returns),0.5,2)',
                eventQuietMinutes=5,confirmation='First green 1m close above previous 1m high within30m',
                target='Prior max(window,60m) high, ending before trigger, discounted0.15%',
                stop='Event-through-confirmation low minus0.15*ATR14(1m simple TR mean); widen to0.35% from confirmation close',
                riskGate=dict(minStopPct=.35,maxStopPct=1.2,minNetRR=1.2,entryBandPct=.1,
                              fastMinNetPct=.8,slowMinNetStrictPct=1.0),
                fastWindowsThroughMin=15,holdFastMinutes=30,holdSlowMinutes=360,
                exit='Whole position at structural target/stop/time; same-minute stop first, gap stop at worse open',
                scenarios=[dict(costPct=c,delayMinutes=d) for c in [.24,.40,.60] for d in [0,1,2]],
                registeredScenarioCount=54,primaryScenario=dict(costPct=.24,delayMinutes=1),
                account=dict(initialUSDT=500,riskPct=.5,maxConcurrent=1,leverage=1),
                selection='First60d primary scenario: >=60 trades, positive net mean and day-cluster lower95>0; rank mean. Otherwise no selection.',
                limitations=['No historical quotes/depth/delivery latency','No independent unseen OOS',
                             'Common diagnostic confirmation/exit model, not production S1-S7',
                             'No opportunity-recall claim; no S6 seconds-level validation',
                             'No automatic promotion or production changes'])


def save_protocol():
    OUT.mkdir(parents=True,exist_ok=True)
    path=OUT/'protocol.json'
    body=json.dumps(protocol(),ensure_ascii=False,indent=2)+'\n'
    if path.exists():
        if path.read_text(encoding='utf-8')!=body:
            raise ValueError('Protocol changed: register a new study, do not overwrite')
    else:
        path.write_text(body,encoding='utf-8')
    return path


def load():
    p=protocol()
    start=int(pd.Timestamp(p['sampleStart']).timestamp()*1000)
    end=int(pd.Timestamp(p['endExclusive']).timestamp()*1000)
    begin=start-91*DAY*MINUTE
    old=pd.read_csv(PRIOR/'btc-1m.csv')
    expected=json.loads((PRIOR/'audit.json').read_text())['csvSha256']
    if hashlib.sha256((PRIOR/'btc-1m.csv').read_bytes()).hexdigest()!=expected:
        raise ValueError('Frozen first study input changed')
    db=sqlite3.connect((ROOT/'data'/'stage-d-diagnostic.sqlite3').as_uri()+'?mode=ro',uri=True)
    try:
        rows=db.execute('SELECT open_time,open,high,low,close,volume,close_time,taker_buy_base FROM klines '
                        'WHERE symbol=? AND interval=? AND open_time>=? AND open_time<? ORDER BY open_time',
                        ('BTCUSDT','1m',begin,int(old.iloc[0].time))).fetchall()
    finally:
        db.close()
    df=pd.concat([pd.DataFrame(rows,columns=COLS),old],ignore_index=True)
    if not np.array_equal(df.time,np.arange(begin,end,MINUTE)):
        raise ValueError('Incomplete minute history, do not synthesize')
    if not np.isfinite(df.to_numpy(dtype=float)).all():
        raise ValueError('Nonfinite input')
    good=((df.low>0)&(df.low<=df[['open','close']].min(axis=1)) &
          (df.high>=df[['open','close']].max(axis=1))&(df.volume>=df.taker_buy_base)&
          (df.taker_buy_base>=0)&(df.close_time==df.time+MINUTE-1))
    if not good.all():
        raise ValueError('Invalid OHLCV')
    df.to_csv(OUT/'input-181days.csv',index=False)
    return df,91*DAY


def daily_levels(drawdowns,returns,boundary,train_minutes=90*DAY):
    """Every slice excludes the first evaluation bar; latest close is strictly earlier."""
    if boundary<train_minutes:
        raise ValueError('Insufficient calibration history')
    a=returns[max(0,boundary-7*DAY):boundary]
    b=returns[max(0,boundary-30*DAY):boundary]
    scale=float(np.clip(np.nanstd(a)/np.nanstd(b),.5,2)) if np.nanstd(b)>0 else 1.0
    levels={}
    for w,values in drawdowns.items():
        past=values[boundary-train_minutes:boundary]
        if not np.isfinite(past).all():
            raise ValueError('Invalid training features')
        levels[w]={q:float(np.quantile(past,q/100)) for q in [90,95,99]}
    return levels,scale


def features(df,start):
    draw={w:((df.high.rolling(w).max()-df.close)/df.high.rolling(w).max()*100).to_numpy() for w in WINDOWS}
    returns=df.close.pct_change().to_numpy()
    levels={m:{} for m in METHODS};records=[]
    initial,_=daily_levels(draw,returns,start)
    for m in METHODS:
        levels[m]={w:np.full(len(df),np.inf) for w in WINDOWS}
    for at in range(start,len(df),DAY):
        past,scale=daily_levels(draw,returns,at)
        for w in WINDOWS:
            values={'DOCUMENT_FIXED':FIXED[w],'TRAIN_FROZEN_P95':initial[w][95],
                    'ROLLING_P90':past[w][90],'ROLLING_P95':past[w][95],
                    'ROLLING_P99':past[w][99],'ADAPTIVE_P95':past[w][95]*scale}
            for m,value in values.items():
                levels[m][w][at:at+DAY]=value
                records.append(dict(method=m,windowMin=w,effectiveMs=int(df.iloc[at].time),
                                    trainingEndExclusiveMs=int(df.iloc[at].time),thresholdPct=value,scale7over30=scale))
    tr=pd.concat([df.high-df.low,(df.high-df.close.shift()).abs(),(df.low-df.close.shift()).abs()],axis=1).max(axis=1)
    return draw,levels,tr.rolling(14).mean().to_numpy(),pd.DataFrame(records)


def candidates(df,start,draw,thresholds,atr):
    bars=df[['open','high','low','close']].to_numpy();times=df.time.to_numpy()
    output={};events=[]
    for method in METHODS:
        hits={w:(draw[w]>=thresholds[method][w]) for w in WINDOWS}
        union=np.logical_or.reduce(list(hits.values()))
        parents=event_starts(union)
        plans=[]
        for w in WINDOWS:
            starts=event_starts(hits[w])
            for i in starts:
                parent=int(parents[np.searchsorted(parents,i,side='right')-1])
                j=confirm(bars,int(i))
                events.append(dict(method=method,windowMin=w,triggerIndex=int(i),triggerMs=int(times[i]+MINUTE),
                                   parentIndex=parent,confirmed=j is not None,confirmIndex=j))
                if j is None:
                    continue
                ref=float(bars[j,3])
                target=float(bars[max(0,i-max(w,60)):i,1].max())*.9985
                stop=min(float(bars[i:j+1,2].min())-.15*atr[j],ref*.9965)
                plans.append(dict(method=method,windowMin=w,triggerIndex=int(i),parentIndex=parent,
                                  confirmIndex=int(j),confirmMs=int(times[j]+MINUTE),reference=ref,
                                  entryLow=ref*.999,entryHigh=ref*1.001,target=target,stop=stop,
                                  holdMinutes=30 if w<=15 else 360,minNet=.8 if w<=15 else 1.0))
        output[method]=sorted(plans,key=lambda p:(p['confirmIndex'],p['triggerIndex'],p['windowMin']))
    return output,pd.DataFrame(events)


def gate(plan,price,cost):
    if not plan['entryLow']<=price<=plan['entryHigh']:
        return 'entry_band'
    risk=(1-plan['stop']/price)*100
    net=(plan['target']/price-1)*100-cost
    if risk<.35-1e-9 or risk>1.2+1e-9:
        return 'stop_distance'
    if net<plan['minNet'] or (plan['windowMin']>15 and net<=plan['minNet']):
        return 'net_space'
    if net/(risk+cost)<1.2:
        return 'net_rr'
    return None


def settle(bars,k,hold,stop,target):
    """Full horizon required to avoid choosing only quickly closed tail winners."""
    if k+hold>len(bars):
        return None
    for i in range(k,k+hold):
        op,hi,lo,cl=bars[i]
        if op<=stop:
            return i,float(op),'STOP_GAP'
        if lo<=stop:
            return i,float(stop),'STOP'
        if hi>=target:
            return i,float(target),'TARGET'
    return k+hold-1,float(bars[k+hold-1,3]),'TIME'


def simulate(df,plans,start,cost,delay):
    bars=df[['open','high','low','close']].to_numpy();times=df.time.to_numpy()
    counts={};trades=[];used=set();busy=-1;equity=500.;curve=np.full(len(df)-start,np.nan);cursor=start
    def reject(reason):
        counts[reason]=counts.get(reason,0)+1
    for p in plans:
        k=p['confirmIndex']+1+delay
        if k>=len(df):
            reject('tail');continue
        if p['parentIndex'] in used:
            reject('parent_duplicate');continue
        if k<=busy:
            reject('position_busy');continue
        price=float(bars[k,0])
        # Stop/target touched during human delay invalidates the old opportunity.
        during=bars[p['confirmIndex']+1:k]
        if len(during) and ((during[:,2]<=p['stop']).any() or (during[:,1]>=p['target']).any()):
            reject('invalid_during_delay');continue
        issue=gate(p,price,cost)
        if issue:
            reject(issue);continue
        result=settle(bars,k,p['holdMinutes'],p['stop'],p['target'])
        if result is None:
            reject('tail');continue
        exit_i,exit_price,outcome=result
        risk=(1-p['stop']/price)*100
        net=(exit_price/price-1)*100-cost
        fraction=min(1,.5/(risk+cost))
        curve[cursor-start:k-start]=equity
        mark=(bars[k:exit_i+1,3]/price-1)*100-cost
        curve[k-start:exit_i+1-start]=equity*(1+fraction*mark/100)
        initial=equity;equity*=1+fraction*net/100
        curve[exit_i-start]=equity
        cursor=exit_i+1;busy=exit_i;used.add(p['parentIndex'])
        trades.append(dict(method=p['method'],windowMin=p['windowMin'],costPct=cost,delayMinutes=delay,
                           openedMs=int(times[k]),closedMs=int(times[exit_i]+MINUTE),
                           parentIndex=p['parentIndex'],entry=price,stop=p['stop'],target=p['target'],
                           exit=exit_price,outcome=outcome,netPct=net,r=net/(risk+cost),
                           holdMinutes=exit_i-k+1,notional=initial*fraction,equityAfter=equity,
                           plannedNetPct=(p['target']/price-1)*100-cost))
    curve[cursor-start:]=equity
    curve=np.nan_to_num(curve,nan=500.)
    peak=np.maximum.accumulate(np.r_[500.,curve])[1:]
    dd=float(((curve/peak-1)*100).min())
    return trades,counts,dict(initial=500,final=equity,minuteCloseDrawdownPct=dd),curve


def metrics(rows):
    a=np.array([r['netPct'] for r in rows]);n=len(a)
    gain=float(a[a>0].sum());loss=float(-a[a<0].sum())
    return dict(trades=n,winPct=float((a>0).mean()*100) if n else None,
                meanNetPct=float(a.mean()) if n else None,
                profitFactor=gain/loss if loss else None,noLosses=bool(n and not loss),
                avgHoldMinutes=float(np.mean([r['holdMinutes'] for r in rows])) if n else None,
                bootstrapLower95=block_bootstrap_lower(rows,iterations=1000) if n else None)


def summary_report(out,summary,events,selected,data,rejections):
    primary=summary[(summary.costPct==.24)&(summary.delayMinutes==1)]
    names={'DOCUMENT_FIXED':'文档固定门槛','TRAIN_FROZEN_P95':'训练期冻结P95','ROLLING_P90':'滚动P90',
           'ROLLING_P95':'滚动P95','ROLLING_P99':'滚动P99','ADAPTIVE_P95':'7/30波动适配P95'}
    frame=primary.copy();frame['method']=frame.method.map(names)
    frame=frame.rename(columns={'method':'方案','segment':'区间','warningParents':'合并预警数','trades':'模拟成交数',
                                'winPct':'净收益为正比例%','meanNetPct':'单笔平均净收益%',
                                'bootstrapLower95':'均值单侧95%下界%','profitFactor':'利润因子',
                                'finalUSDT':'模拟期末资金','minuteCloseDrawdownPct':'分钟收盘最大回撤%'})
    cols=['方案','区间','合并预警数','模拟成交数','净收益为正比例%','单笔平均净收益%','均值单侧95%下界%','利润因子']
    frame['区间']=frame['区间'].map({'ALL90':'全部90天','FIRST60':'前60天','TAIL30':'尾部30天'})
    rejected=rejections[(rejections.costPct==.24)&(rejections.delayMinutes==1)].pivot(index='method',columns='reason',values='count').fillna(0).astype(int)
    rejected.index=rejected.index.map(names)
    rejected=rejected.rename(columns={'entry_band':'入场区失效','stop_distance':'止损距离','net_space':'净目标空间',
                                     'net_rr':'净盈亏比','position_busy':'持仓冲突','parent_duplicate':'同事件重复',
                                     'invalid_during_delay':'等待期间失效','tail':'尾部不完整'}).reset_index().rename(columns={'method':'方案'})
    text=['# 第二项：因果动态门槛与统一风险筛选对照','','状态：历史诊断研究；未改变生产代码和APK；不具备独立样本外晋级资格。',
          '',f"输入：{data['rows']:,}根1分钟K线，91天预热（含特征预热1天）加90天评估；无缺失、重复、无效OHLCV。评估仍为北京时间2026-07-20 14:56至2026-10-18 14:56。",'',
          '## 主要结果','',table(frame[cols]),'',
          f"按预登记规则选择结果：{names.get(selected,selected) if selected else '没有方案通过研究筛选，不推荐新阈值上线'}。",'',
          '初筛仅使用前60天：至少60笔、平均净收益为正、按入场日聚类bootstrap的均值单侧95%下界大于0；若通过则按均值排序。尾部30天只诊断，不反向选参数。这个初筛不是项目的完整晋级门槛。',
          '', '## 主场景门禁拒绝原因','',table(rejected),'',
          '计数单位是窗口候选计划，不是跨窗口父事件。一条计划只记首个拒绝原因；各原因不是彼此独立的因果贡献。',
          '', '## 六组对照与时间纪律','',
          '- 文档固定门槛：1/3/5/15/60/240/1440分钟对应0.8/1.2/0.65/0.9/3/6/8%。它不是线上S1–S4完整策略。',
          '- 训练期冻结P95：仅首次评估之前90天计算一次，此后固定；避免把整个评估期分位数泄漏到开头。',
          '- 滚动P90/P95/P99：每24小时只用刷新时点之前90天重新计算，当天冻结。刷新锚点为06:56 UTC，与原研究截点一致。',
          '- 波动适配P95：滚动P95乘以过去7天/30天分钟收益率标准差比，截断到0.5–2倍。这是预登记假设，不是最优权重。',
          '- 每个窗口连续命中按5分钟静默去重；跨窗口再合并父事件，父事件只允许一次模拟入场。预警次数没有被利润门禁阻断。',
          '- 所有阈值逐日留档thresholds.csv。完整输入保存在input-181days.csv。尾段历史已在第一项报告中被查看，不能改称未见样本外。',
          '', '## 各组共用的诊断确认与退出（不是最终S1–S7规则）','',
          '事件后30分钟内首根阳线收盘突破前一分钟高点，作为共同确认代理；计划入场区为确认价±0.10%。主场景再等待1分钟，以下一分钟开盘作为参考成交价。等待期间触及止损或目标作废。',
          '目标为触发前max(窗口,60分钟)最高价下方0.15%；结构止损为事件至确认最低价减0.15倍1分钟ATR14（此研究用TR简单均值）。止损不足0.35%则从确认价向外扩，不向内缩。',
          '最新参考入场价重新核算：止损距离0.35%–1.20%，净盈亏比≥1.2；1/3/5/15分钟事件净目标≥0.8%，其余净目标>1%。这些是固定比较条件，本轮不优化止损或利润目标。',
          '短窗口最长持有30分钟，其余最长360分钟；整仓在结构目标、止损或到时退出。同柱止损优先；跳空越过止损按较差开盘价，目标只按目标价。完整持有窗口不足的样本统一排除，不能只保留尾部早早止盈的交易。',
          '这是整仓退出的研究模型，与线上TP1半仓退出、跟踪余仓不同；不能把结果称为线上策略表现。',
          '', '## 成本、资金与结果边界','',
          '54个场景全部保留：6组门槛×0.24/0.40/0.60%来回成本×0/1/2分钟延迟；主场景在结果前固定为0.24%和1分钟。成本含费用、价差与滑点预算，非实际账户测量。',
          '初始500 USDT、每笔风险预算0.5%，现货无杠杆且同时最多一仓；仓位比例=min(100%,0.5%/(止损距离+成本))。不将重叠机会当作可以无限同时成交。',
          '分钟收盘盯市回撤按当前价、仓位与全成本计算；不代表分钟内最大回撤，实际跳空和流动性可能造成更大损失。利润因子无亏损分母时为空，不伪造无限值。',
          '区间统计按入场时间分组，前60天用于选择时剔除跨过切分点才退出的交易。90天资金曲线连续，尾段不是独立重置账户。未报告真实机会漏报率；其独立机会分母尚未建立。',
          '本轮不模拟秒级盘口，不证明S6人工可执行，也未实现S7完整区间判定。历史所有试验次数不完整，PBO/DSR不作有效性结论。任何好看结果也不自动晋级。',
          '', '## 交付文件','',
          'protocol.json：结果前冻结方法；thresholds.csv：逐日阈值；warnings.csv：窗口事件与父事件；plans.csv：确认后计划；trades.csv：54场景逐笔；summary.csv：全量场景和区间结果；rejections.csv：门禁拒绝原因；primary-equity.csv：主场景分钟资金曲线；selection.json：前60天筛选结果；audit.json：完整性及哈希。']
    (out/'报告.md').write_text('\n'.join(text)+'\n',encoding='utf-8')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--register-only',action='store_true');args=parser.parse_args()
    path=save_protocol()
    if args.register_only:
        print('PROTOCOL_REGISTERED');return
    df,start=load();draw,levels,atr,thresholds=features(df,start)
    plans,events=candidates(df,start,draw,levels,atr)
    thresholds.to_csv(OUT/'thresholds.csv',index=False)
    events.to_csv(OUT/'warnings.csv',index=False)
    pd.DataFrame([p for group in plans.values() for p in group]).to_csv(OUT/'plans.csv',index=False)
    all_trades=[];summaries=[];rejections=[];curves={'time':df.time.iloc[start:].to_numpy()}
    split=int(df.iloc[start+60*DAY].time);selected=None;eligible=[]
    for method in METHODS:
        for scenario in protocol()['scenarios']:
            cost,delay=scenario['costPct'],scenario['delayMinutes']
            trades,counts,capital,curve=simulate(df,plans[method],start,cost,delay)
            all_trades.extend(trades)
            for reason,n in counts.items():
                rejections.append(dict(method=method,**scenario,reason=reason,count=n))
            for segment in ['ALL90','FIRST60','TAIL30']:
                rows=trades
                if segment=='FIRST60':
                    rows=[t for t in trades if t['openedMs']<split and t['closedMs']<=split]
                elif segment=='TAIL30':
                    rows=[t for t in trades if t['openedMs']>=split]
                ev=events[events.method==method]
                if segment!='ALL90':
                    ev=ev[ev.parentIndex<start+60*DAY] if segment=='FIRST60' else ev[ev.parentIndex>=start+60*DAY]
                stats=metrics(rows)
                summaries.append(dict(method=method,**scenario,segment=segment,warningParents=ev.parentIndex.nunique(),
                                      **stats,finalUSDT=capital['final'] if segment=='ALL90' else None,
                                      minuteCloseDrawdownPct=capital['minuteCloseDrawdownPct'] if segment=='ALL90' else None))
                if segment=='FIRST60' and cost==.24 and delay==1 and stats['trades']>=60 and stats['meanNetPct']>0 and stats['bootstrapLower95'] is not None and stats['bootstrapLower95']>0:
                    eligible.append((stats['meanNetPct'],method))
            if cost==.24 and delay==1:
                curves[method]=curve
            print(f'{method} cost={cost} delay={delay} n={len(trades)}',flush=True)
    if eligible:
        selected=max(eligible)[1]
    summary=pd.DataFrame(summaries)
    pd.DataFrame(all_trades).to_csv(OUT/'trades.csv',index=False)
    summary.to_csv(OUT/'summary.csv',index=False)
    rejection_frame=pd.DataFrame(rejections)
    rejection_frame.to_csv(OUT/'rejections.csv',index=False)
    pd.DataFrame(curves).to_csv(OUT/'primary-equity.csv',index=False)
    (OUT/'selection.json').write_text(json.dumps(dict(selected=selected,eligible=eligible,status='DIAGNOSTIC_ONLY',productionChange=False),indent=2),encoding='utf-8')
    audit=dict(rows=len(df),evaluationRows=len(df)-start,missing=0,invalid=0,
               inputSha256=hashlib.sha256((OUT/'input-181days.csv').read_bytes()).hexdigest(),
               protocolSha256=hashlib.sha256(path.read_bytes()).hexdigest(),
               scriptSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (OUT/'audit.json').write_text(json.dumps(audit,indent=2),encoding='utf-8')
    summary_report(OUT,summary,events,selected,audit,rejection_frame)
    print('DYNAMIC_REPORT_READY',flush=True)


if __name__=='__main__':
    main()
