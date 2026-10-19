"""Read-only source, isolated 90-day descriptive study; never a strategy backtest."""
import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scratch'))
from cryptog.kline_store import get_json, KLINE_URL

MINUTE = 60000
WINDOWS = [1, 3, 5, 15, 60, 240, 1440]
HORIZONS = [5, 15, 30, 60, 240]
COLS = ['time', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'taker_buy_base']


def iso(t):
    return pd.Timestamp(int(t), unit='ms', tz='UTC').isoformat()


def event_starts(mask, quiet=5):
    """A new event needs quiet full non-hit minutes since the previous hit."""
    hits = np.flatnonzero(mask)
    return hits[np.r_[True, np.diff(hits) > quiet]] if len(hits) else hits


def confirm(bars, start, max_wait=30):
    """Fixed diagnostic proxy: green 1m closes over previous 1m high."""
    for j in range(start + 1, min(len(bars), start + max_wait + 1)):
        if bars[j, 3] > bars[j, 0] and bars[j, 3] > bars[j - 1, 1]:
            return j
    return None


def path_stats(bars, entry_index, horizon, entry):
    if entry_index + horizon > len(bars):
        return None
    future = bars[entry_index:entry_index + horizon]
    return ((float(future[:, 1].max()) / entry - 1) * 100,
            (float(future[:, 2].min()) / entry - 1) * 100,
            (float(future[-1, 3]) / entry - 1) * 100)


def load_data(out, end):
    begin = end - 91 * 1440 * MINUTE  # 24h warmup before the 90-day sample
    cached = out / 'btc-1m.csv'
    if cached.exists():
        df = pd.read_csv(cached)
        provenance = json.loads((out / 'provenance.json').read_text(encoding='utf-8'))
        if provenance['endExclusiveMs'] != end:
            raise ValueError('Use another output folder for another frozen cutoff')
        return df, provenance
    source = ROOT / 'data' / 'stage-d-diagnostic.sqlite3'
    db = sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)
    try:
        rows = db.execute('SELECT open_time,open,high,low,close,volume,close_time,taker_buy_base '
                          'FROM klines WHERE symbol=? AND interval=? AND open_time>=? AND open_time<? '
                          'ORDER BY open_time', ('BTCUSDT', '1m', begin, end)).fetchall()
    finally:
        db.close()
    by_time = {r[0]: r for r in rows}
    missing = [t for t in range(begin, end, MINUTE) if t not in by_time]
    pages = []
    for t in missing:
        if not pages or t != pages[-1][-1] + MINUTE or len(pages[-1]) == 1000:
            pages.append([])
        pages[-1].append(t)

    def fetch(times):
        url = KLINE_URL.format(symbol='BTCUSDT', interval='1m', start=times[0], end=times[-1]+MINUTE-1)
        raw = get_json(url)
        if [int(r[0]) for r in raw] != times:
            raise ValueError('Incomplete Binance response: ' + url)
        return [(int(r[0]), *map(float, r[1:6]), int(r[6]), float(r[9])) for r in raw]

    with ThreadPoolExecutor(max_workers=4) as pool:
        for result in pool.map(fetch, pages):
            by_time.update({r[0]: r for r in result})
            print(f'Fetched {len(result)} closed minutes through {iso(result[-1][0])}', flush=True)
    df = pd.DataFrame([by_time[t] for t in sorted(by_time)], columns=COLS)
    df.to_csv(cached, index=False)
    provenance = dict(sourceDatabase=str(source), symbol='BTCUSDT', interval='1m',
                      startInclusiveMs=begin, sampleStartMs=end-90*1440*MINUTE, endExclusiveMs=end,
                      inheritedRows=len(rows), fetchedRows=len(missing),
                      publicEndpoint='https://data-api.binance.vision/api/v3/klines',
                      sourceStatus='Inherited local historical rows plus public REST gap fill; not independently re-downloaded',
                      use='DESCRIPTIVE_DIAGNOSTIC_NOT_OUT_OF_SAMPLE')
    (out / 'provenance.json').write_text(json.dumps(provenance, indent=2), encoding='utf-8')
    return df, provenance


def audit(df, p):
    expected = np.arange(p['startInclusiveMs'], p['endExclusiveMs'], MINUTE)
    if not np.array_equal(df.time.to_numpy(), expected):
        raise ValueError('Duplicate, missing or misaligned minute')
    if not np.isfinite(df.to_numpy(dtype=float)).all():
        raise ValueError('Nonfinite data')
    good = ((df.close_time == df.time + MINUTE - 1) & (df.low > 0)
            & (df.low <= df[['open', 'close']].min(axis=1))
            & (df.high >= df[['open', 'close']].max(axis=1))
            & (df.volume >= 0) & (df.taker_buy_base >= 0) & (df.taker_buy_base <= df.volume))
    if not good.all():
        raise ValueError('Invalid OHLCV or close timestamp')
    return dict(rows=len(df), sampleRows=90*1440, warmupRows=1440, missing=0, duplicates=0, invalid=0,
                sampleStartUTC=iso(p['sampleStartMs']), endExclusiveUTC=iso(p['endExclusiveMs']),
                firstPrice=float(df.iloc[1440].open), lastPrice=float(df.iloc[-1].close))


def verify_source(df):
    checks=[]
    for start in [1440, len(df)//2, len(df)-2500]:
        subset=df.iloc[start:start+1000]
        raw=get_json(KLINE_URL.format(symbol='BTCUSDT',interval='1m',start=int(subset.iloc[0].time),end=int(subset.iloc[-1].time)+MINUTE-1))
        fetched=np.array([(int(r[0]),*map(float,r[1:6]),int(r[6]),float(r[9])) for r in raw])
        if fetched.shape!=subset.shape or not np.allclose(fetched,subset.to_numpy(),rtol=0,atol=1e-8):
            raise ValueError('Public REST source comparison failed')
        checks.append(dict(startUTC=iso(subset.iloc[0].time),rows=len(raw),matched=True))
    return dict(checkedRows=3000,method='Three preselected 1000-row historical slices compared with public REST',checks=checks)


def study(df):
    bars = df[['open', 'high', 'low', 'close']].to_numpy()
    times = df.time.to_numpy()
    c = df.close
    sample = np.arange(len(df)) >= 1440
    distributions, frequencies, events, fixed, bands, sensitivity = [], [], [], [], [], []
    # Defined before inspecting outcomes: diagnostic confirmation, not optimized.
    for window in WINDOWS:
        change = (c / c.shift(window) - 1) * 100
        peak = df.high.rolling(window).max()
        drawdown = (peak-c) / peak * 100
        for metric, values in [('close_return_down', -change), ('peak_drawdown', drawdown)]:
            s = values[sample]
            selected = s[s > 0] if metric == 'close_return_down' else s
            row = dict(windowMin=window, metric=metric, sampleN=len(s), distributionN=len(selected),
                       downSharePct=float((s > 0).mean()*100))
            row.update({f'p{q}': float(selected.quantile(q/100)) for q in [50,75,90,95,99]})
            distributions.append(row)
            band=sample & (c.to_numpy()>=80000) & (c.to_numpy()<=90000)
            bs=values[band]
            selected_band=bs[bs>0] if metric=='close_return_down' else bs
            bands.append(dict(windowMin=window,metric=metric,band='80000-90000',sampleN=len(bs),distributionN=len(selected_band),
                              **{f'p{q}':float(selected_band.quantile(q/100)) for q in [50,75,90,95,99]}))
            fixed_threshold={1:.8,3:1.2,5:.65,15:.9,60:3,240:6,1440:8}[window]
            fm=sample & (values.to_numpy()>=fixed_threshold)
            fs=event_starts(fm)
            fixed.append(dict(windowMin=window,metric=metric,thresholdPct=fixed_threshold,rawHits=int(fm.sum()),events=len(fs),perDay=len(fs)/90))
            for q in [90,95,99]:
                threshold = row[f'p{q}']
                mask = sample & (values.to_numpy() >= threshold)
                starts = event_starts(mask)
                for quiet in [5,15,30]:
                    count=len(event_starts(mask,quiet))
                    sensitivity.append(dict(windowMin=window,metric=metric,percentile=q,quietMinutes=quiet,events=count,perDay=count/90))
                frequencies.append(dict(windowMin=window, metric=metric, percentile=q, thresholdPct=threshold,
                                        rawHits=int(mask.sum()), events=len(starts), perDay=len(starts)/90,
                                        meanIntervalMinutes=float(np.diff(starts).mean()) if len(starts)>1 else None))
                # Outcome analysis uses peak drawdown events only, to avoid counting both definitions as trades.
                if metric != 'peak_drawdown':
                    continue
                for i in starts:
                    event = dict(windowMin=window, percentile=q, thresholdPct=threshold,
                                 triggerMs=int(times[i]+MINUTE), actualDropPct=float(values.iloc[i]),
                                 confirmMs=None, confirmed=False, confirmationCensored=i+30>=len(df))
                    j = confirm(bars, i)
                    if j is not None:
                        event.update(confirmed=True, confirmMs=int(times[j]+MINUTE), waitMin=int(j-i))
                        # Pre-event rolling high is known at trigger; no future-derived target.
                        target = float(df.high.iloc[max(0, i-max(window,60)):i].max())
                        structural_low = float(df.low.iloc[i:j+1].min())
                        for delay in [0,1,2]:
                            k = j+1+delay  # first open AFTER confirmation close, plus delay
                            if k >= len(df):
                                continue
                            entry = float(bars[k,0])
                            event[f'entry{delay}'] = entry
                            event[f'structuralGross{delay}'] = (target/entry-1)*100
                            event[f'structuralRisk{delay}'] = (1-structural_low/entry)*100
                            for h in HORIZONS:
                                stats = path_stats(bars,k,h,entry)
                                if stats is not None:
                                    for name,value in zip(['mfe','mae','end'],stats):
                                        event[f'{name}_{h}m_d{delay}'] = value
                    events.append(event)
    return tuple(pd.DataFrame(x) for x in [distributions,frequencies,events,fixed,bands,sensitivity])


def summarize(events):
    rows=[]
    for (w,q), group in events.groupby(['windowMin','percentile']):
        confirmed=group[group.confirmed]
        for delay in [0,1,2]:
            for h in HORIZONS:
                name=f'mfe_{h}m_d{delay}'
                if name not in confirmed:
                    continue
                valid=confirmed[confirmed[name].notna()]
                for cost in [.24,.40,.60]:
                    net=valid[name]-cost
                    rows.append(dict(windowMin=int(w),percentile=int(q),delayMinutes=delay,horizonMinutes=h,costPct=cost,
                                     eventN=len(group),confirmedN=len(confirmed),completeOutcomeN=len(valid),
                                     unconfirmedCensoredN=int((~group.confirmed & group.confirmationCensored).sum()),
                                     medianNetMFE=float(net.median()) if len(net) else None,
                                     medianMAE=float(valid[f'mae_{h}m_d{delay}'].median()) if len(valid) else None,
                                     medianNetEnd=float((valid[f'end_{h}m_d{delay}']-cost).median()) if len(valid) else None,
                                     netMFE_ge08_pct=float((net>=.8).mean()*100) if len(net) else None,
                                     netMFE_gt1_pct=float((net>1).mean()*100) if len(net) else None,
                                     structuralSpace_ge08_pct=float(((valid[f'structuralGross{delay}']-cost)>=.8).mean()*100) if len(valid) else None))
    return pd.DataFrame(rows)


def table(frame):
    labels={'windowMin':'窗口(分钟)','downSharePct':'正跌幅占比%','percentile':'分位档位','thresholdPct':'阈值%',
            'rawHits':'分钟命中数','events':'合并事件数','perDay':'日均事件数','meanIntervalMinutes':'平均间隔(分钟)',
            'horizonMinutes':'观察期(分钟)','eventN':'事件数','confirmedN':'确认数','completeOutcomeN':'完整结果数',
            'medianNetMFE':'净最大空间中位数%','medianMAE':'最不利波动中位数%','medianNetEnd':'终点净收益中位数%',
            'netMFE_ge08_pct':'净空间≥0.8%占比%','netMFE_gt1_pct':'净空间>1%占比%',
            'delayMinutes':'延迟(分钟)','costPct':'成本%','structuralSpace_ge08_pct':'先验目标空间≥0.8%占比%',
            'sampleN':'分钟窗口数','distributionN':'分布样本数','quietMinutes':'去重静默(分钟)'}
    frame=frame.rename(columns=labels)
    def fmt(x):
        return f'{x:.3f}' if isinstance(x,(float,np.floating)) else str(x)
    return '| '+' | '.join(map(str,frame.columns))+' |\n|'+ '|'.join(['---']*len(frame.columns))+'|\n' + '\n'.join('| '+' | '.join(fmt(x) for x in r)+' |' for r in frame.itertuples(index=False,name=None))


def report(out,a,dist,freq,summary,fixed,bands,sensitivity):
    def row(w,h):
        return summary[(summary.windowMin==w)&(summary.percentile==95)&(summary.delayMinutes==1)&
                       (summary.costPct==.24)&(summary.horizonMinutes==h)].iloc[0]
    r5,r15=row(5,30),row(15,30)
    lines=['# BTC真实跌幅、独立事件频率与确认后收益空间报告',
           '', '状态：第一项描述性研究交付；不是策略回测，不是新阈值推荐，也不是样本外验证。',
           '', '## 主要发现', '',
           '- 固定大跌入口确实可能非常稀疏，但本报告未计算“有效买入机会漏报率”，不能把少触发直接等同于漏掉盈利交易。',
           f"- 5分钟P95回撤事件确认后，再延迟1分钟、观察30分钟，扣0.24%成本后的最大有利空间达到0.8%的占比仅{r5.netMFE_ge08_pct:.2f}%（{int(r5.completeOutcomeN)}个完整结果）；15分钟P95事件对应{r15.netMFE_ge08_pct:.2f}%（{int(r15.completeOutcomeN)}个）。这些是空间达标比例，不是交易胜率。",
           '- 结论支持把早期预警与买入门禁拆开；不支持把异常分位数直接变为买入条件。固定确认代理非常宽松，仅用于比较，后续必须验证更有效的确认规则。',
           '', '![波动与收益空间概览](overview.png)',
           '', '## 数据与完整性', '',
           f"样本：{a['sampleStartUTC']} 至 {a['endExclusiveUTC']}（右端不含），90天共129,600根已收盘分钟K线；额外1,440根用于24小时窗口预热。",
           f"数据核验：缺失{a['missing']}、重复{a['duplicates']}、无效{a['invalid']}；样本首根开盘{a['firstPrice']:,.2f}，最后收盘{a['lastPrice']:,.2f} USDT。",
           '数据来自已有本地Binance研究库存，并通过Binance公共REST补齐缺口。历史源抽检见source-check.json；非全量重新下载。详细来源与文件哈希见provenance.json、audit.json。',
           '', '## 统计定义（结果产生前固定）', '',
           '- 起止跌幅：当前分钟收盘相对N分钟前收盘的负收益，只对下跌样本计算分位数；downSharePct是全部窗口中下跌比例。',
           '- 高点回撤：最近N根分钟K线最高价到当前收盘的回撤，含零值计算分位数。两种定义不可混用。',
           '- 全部指标在分钟收盘采样：分钟内急跌又收回可能被遗漏；1分钟OHLC无法确定先高后低顺序，因此不将同柱high-low冒充可实时识别的先后跌幅。此报告不验证Tick级漏报率。',
           '- 事件：同一窗口/同一阈值内，距前一次命中超过5分钟才开启新事件（至少5个未命中分钟）。事件数是此去重口径下的统计单位，不代表经济或统计上完全独立。不同窗口和分位档位不能相加。',
           '- 分位阈值使用整个90天，专用于描述频率，存在样本内选阈值；不能据此宣称动态策略收益或投入生产。',
           '- 固定确认代理：事件后30分钟内，第一根阳线收盘突破前一分钟最高价；不等同于S1/S6最终买入确认。无确认不计算收益。',
           '- 参考入场：确认后下一分钟开盘；另测再延迟1/2分钟。无实际ask/bid、深度与手机操作时间，不能证明真实可成交。',
           '- MFE为持有窗口内最大有利价格空间，MAE为最大不利价格变化（负数）；净MFE扣参考成本。终点净收益是固定时限末收盘价收益。MFE达标率不是胜率、不是触及止盈先于止损的概率。',
           '- 结构空间代理：触发前max(窗口,60分钟)最高价作为已知目标，事件至确认的最低点作为风险参考。仅描述空间，不构成经验证的阻力/止损方案。',
           '- 样本尾部未满观察窗口的结果不参与相应统计，未补零；不同持有期分母可能不同。',
           '', '## 真实跌幅分布（百分比）', '']
    for metric,title in [('close_return_down','起止下跌幅度（仅下跌样本）'),('peak_drawdown','窗口高点回撤（全部窗口）')]:
        lines += ['### '+title,'',table(dist[dist.metric==metric][['windowMin','downSharePct','p50','p75','p90','p95','p99']]),'']
    lines += ['## 80,000–90,000 USDT价位子样本','',
              '以窗口末收盘价处于该区间筛选；是同一时期的条件分布，不能据此推断高价格本身导致低波动。完整两口径见price-band-distributions.csv。','',
              table(bands[bands.metric=='peak_drawdown'][['windowMin','sampleN','p50','p75','p90','p95','p99']]),'',
              '## 此前固定门槛对照：高点回撤','',
              '这些是需求文档/上一轮方案中的比较值，不是当前S1代码的完整策略触发，也不是新推荐阈值。','',
              table(fixed[fixed.metric=='peak_drawdown'].drop(columns='metric')),'']
    lines += ['## 独立事件频率：高点回撤P90/P95/P99','',table(freq[freq.metric=='peak_drawdown'].drop(columns=['metric'])),'',
              '完整两种口径频率见frequencies.csv。原始命中是分钟窗口数，不能当作独立预警次数。', '',
              '## 去重间隔敏感性：高点回撤P95','',
              table(sensitivity[(sensitivity.metric=='peak_drawdown')&(sensitivity.percentile==95)].drop(columns=['metric','percentile'])),'',
              '## 确认后收益空间：P95事件、延迟1分钟、成本0.24%','',
              '以下仅为可观察价格空间；数值单位为百分比。completeOutcomeN为有效分母。', '']
    selected=summary[(summary.percentile==95)&(summary.delayMinutes==1)&(summary.costPct==.24)]
    lines += [table(selected[['windowMin','horizonMinutes','eventN','confirmedN','completeOutcomeN','medianNetMFE','medianMAE','medianNetEnd','netMFE_ge08_pct','netMFE_gt1_pct']]),'',
              '## 延迟与成本敏感性：P95事件、30分钟观察期','',
              table(summary[(summary.percentile==95)&(summary.horizonMinutes==30)][['windowMin','delayMinutes','costPct','completeOutcomeN','medianNetMFE','netMFE_ge08_pct','structuralSpace_ge08_pct']]),'',
              '## 结论边界与下一步','',
              '本报告可以回答“真实波动有多大、重复触发合并后有多频繁、指定确认代理后还有多少价格空间”。不能回答最终策略胜率、净期望值、最大回撤或可保证利润。',
              '0.24%为现有项目保守成本下限（单边0.10%费用及约0.02%价差/滑点预算），0.40%/0.60%为压力情景，均非本次测得账户实际费用。价差已含预算，不重复扣。未假设BNB折扣。',
              '高MFE不代表可兑现：后续策略回测必须增加先验目标/止损、同柱顺序、持仓退出、真实成本与账户资金冲突。不能用未来最高点选止盈价。',
              '下一项再做只使用过去数据的90天滚动阈值、7/30天状态适配和时间顺序验证。本次不得将P95直接标记为最优。S6秒级可执行性仍缺盘口与端到端延迟证据。',
              '', '来源：[Binance市场数据REST](https://developers.binance.com/docs/binance-spot-api-docs/rest-api/market-data-endpoints)；本地研究库存。']
    (out/'报告.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


def chart(out,dist,summary):
    import os
    sys.path.append(str(ROOT/'.tmp'/'btc-report-deps'))
    os.environ.setdefault('MPLCONFIGDIR',str(ROOT/'.tmp'/'btc-mpl-config'))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.font_manager import FontProperties
    font=FontProperties(fname='C:/Windows/Fonts/msyh.ttc')
    plt.rcParams['axes.unicode_minus']=False
    fig,axes=plt.subplots(1,2,figsize=(13,5),layout='constrained')
    labels=['1m','3m','5m','15m','1h','4h','24h']
    d=dist[dist.metric=='peak_drawdown']
    for q in [90,95,99]:
        axes[0].plot(labels,d[f'p{q}'],marker='o',label=f'P{q}')
    axes[0].set_title('窗口高点至收盘回撤分位数',fontproperties=font)
    axes[0].set_ylabel('跌幅（%）',fontproperties=font)
    axes[0].legend();axes[0].grid(alpha=.2)
    for h in [30,240]:
        s=summary[(summary.percentile==95)&(summary.delayMinutes==1)&(summary.costPct==.24)&(summary.horizonMinutes==h)]
        axes[1].plot(labels,s.netMFE_ge08_pct,marker='o',label=f'{h} min')
    axes[1].set_title('确认后净最大空间 ≥0.8%的占比',fontproperties=font)
    axes[1].set_ylabel('空间达标比例（%，不是胜率）',fontproperties=font)
    axes[1].legend();axes[1].grid(alpha=.2)
    axes[1].set_xlabel('P95事件；延迟1分钟；参考成本0.24%',fontproperties=font)
    fig.suptitle('BTC 90天描述性研究｜2026-07-20—2026-10-18 UTC',fontproperties=font,fontsize=15)
    fig.savefig(out/'overview.png',dpi=160)
    plt.close(fig)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--end',required=True,help='UTC ISO exclusive minute boundary')
    parser.add_argument('--output',required=True)
    parser.add_argument('--verify-source',action='store_true')
    args=parser.parse_args()
    end=int(pd.Timestamp(args.end).timestamp()*1000)
    if end%MINUTE or end>int(pd.Timestamp.now(tz='UTC').timestamp()*1000)//MINUTE*MINUTE:
        raise ValueError('Cutoff must be a closed minute boundary')
    out=Path(args.output); out.mkdir(parents=True,exist_ok=True)
    df,p=load_data(out,end)
    a=audit(df,p)
    if args.verify_source:
        (out/'source-check.json').write_text(json.dumps(verify_source(df),indent=2),encoding='utf-8')
    a['csvSha256']=hashlib.sha256((out/'btc-1m.csv').read_bytes()).hexdigest()
    a['scriptSha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    (out/'audit.json').write_text(json.dumps(a,indent=2),encoding='utf-8')
    dist,freq,events,fixed,bands,sensitivity=study(df)
    summary=summarize(events)
    for name,frame in [('distributions',dist),('frequencies',freq),('events',events),('space-summary',summary),
                       ('fixed-threshold-frequency',fixed),('price-band-distributions',bands),('dedup-sensitivity',sensitivity)]:
        frame.to_csv(out/(name+'.csv'),index=False)
    report(out,a,dist,freq,summary,fixed,bands,sensitivity)
    chart(out,dist,summary)
    print(json.dumps(a,indent=2),flush=True)
    print('REPORT_READY',flush=True)


if __name__=='__main__':
    main()
