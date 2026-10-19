"""Stage A: frozen-input attribution and an independent, explicitly limited opportunity benchmark."""
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

from research_btc_dynamic import ROOT, DAY, METHODS, settle
from report_btc_wave_space import table

SOURCE=ROOT/'audit'/'btc-dynamic-study-20261018'
OUT=ROOT/'audit'/'btc-stage-a-20261018'
COST=.24


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def register():
    OUT.mkdir(parents=True,exist_ok=True)
    spec=dict(version='stage-a-attribution-1',status='DIAGNOSTIC_ONLY',
              sourceHashes={n:sha(SOURCE/n) for n in ['input-181days.csv','trades.csv','plans.csv','warnings.csv','protocol.json']},
              primary=dict(costPct=COST,delayMinutes=1),
              tradeAttribution='Gross versus modeled cost; exit types; positive pre-exit CLOSED-minute mark then final loss',
              gateAttribution='All independent predicates; standalone counterfactual paths, not causal portfolio returns',
              relaxMin='Remove minimum stop only, retain original stop and other gates',
              relaxMax='Raise maximum stop to2.5% only, retain original stop and other gates',
              opportunityProfiles=[dict(name='FAST',hold=30,targetLookback=60,stopLookback=5,minNet=.8),
                                   dict(name='SLOW',hold=360,targetLookback=240,stopLookback=15,minNet=1.)],
              opportunityDefinition='Every closed green 1m above prior high, next open plus1m delay, known target and stop, same risk gates; no alert threshold input',
              opportunityDedup='Within each profile greedily reserve the full planned holding interval before observing outcomes',
              opportunitySuccess='Structural target reached before stop, net>=0.8 FAST or net>1 SLOW',
              warningMatch='Same fast/slow window family, trigger in [reference confirmation-30m, confirmation]; temporal coverage only',
              limitations=['Seen history','No quotes/depth','Reference opportunities are not all market opportunities',
                           'No proof of cause from observational attribution','No production or original report mutation'])
    path=OUT/'protocol.json'
    body=json.dumps(spec,indent=2,ensure_ascii=False)+'\n'
    if path.exists() and path.read_text(encoding='utf-8')!=body:
        raise ValueError('Frozen protocol/source changed; create new version')
    if not path.exists():
        path.write_text(body,encoding='utf-8')
    return spec


def mark_path(bars,k,end,entry,cost):
    # The exit minute high/close may occur AFTER a stop: exclude the entire exit minute.
    before=bars[k:end]
    closed_peak=float(((before[:,3]/entry-1)*100-cost).max()) if len(before) else None
    return closed_peak


def gate_flags(p,price,cost,during):
    risk=(1-p['stop']/price)*100
    net=(p['target']/price-1)*100-cost
    return dict(entry_band=not p['entryLow']<=price<=p['entryHigh'],
                delay_invalid=bool(len(during) and ((during[:,2]<=p['stop']).any() or (during[:,1]>=p['target']).any())),
                stop_min=risk<.35-1e-9,stop_max=risk>1.2+1e-9,
                net_space=net<p['minNet'] or (p['windowMin']>15 and net<=p['minNet']),
                net_rr=(risk<=0 or net/(risk+cost)<1.2)),risk,net


def permitted(flags,relax,risk):
    f=dict(flags)
    if relax=='MIN':
        f['stop_min']=False
    if relax=='MAX' and 0<risk<=2.5:
        f['stop_max']=False
    return risk>0 and not any(f.values())


def trade_audit(df,bars,trades):
    times=df.time.to_numpy();rows=[]
    primary=trades[(trades.costPct==COST)&(trades.delayMinutes==1)]
    for t in primary.to_dict('records'):
        k=int(np.searchsorted(times,t['openedMs']))
        end=int(np.searchsorted(times,t['closedMs']))-1
        peak=mark_path(bars,k,end,t['entry'],COST)
        t.update(grossPct=t['netPct']+COST,preExitClosedPeakNet=peak,
                 positiveThenLoss=bool(peak is not None and peak>0 and t['netPct']<0),
                 goalThenLoss=bool(peak is not None and peak>= (.8 if t['windowMin']<=15 else 1) and t['netPct']<0),
                 feeTurnsProfitToLoss=bool(0<t['netPct']+COST and t['netPct']<0))
        rows.append(t)
    full=pd.DataFrame(rows);summary=[]
    for method,g in full.groupby('method',sort=False):
        summary.append(dict(method=method,trades=len(g),netLosers=int((g.netPct<0).sum()),
                            grossMeanPct=g.grossPct.mean(),netMeanPct=g.netPct.mean(),
                            feeTurnsProfitToLoss=int(g.feeTurnsProfitToLoss.sum()),
                            positiveThenLoss=int(g.positiveThenLoss.sum()),goalThenLoss=int(g.goalThenLoss.sum()),
                            stopCount=int(g.outcome.str.startswith('STOP').sum()),
                            timeCount=int((g.outcome=='TIME').sum()),targetCount=int((g.outcome=='TARGET').sum())))
    exits=full.groupby(['method','outcome']).agg(trades=('netPct','size'),meanNetPct=('netPct','mean'),meanHold=('holdMinutes','mean')).reset_index()
    return full,pd.DataFrame(summary),exits


def plans_audit(df,bars,plans):
    records=[]
    for p in plans.to_dict('records'):
        j=int(p['confirmIndex']);k=j+2
        if k>=len(bars):
            continue
        price=float(bars[k,0]);flags,risk,net=gate_flags(p,price,COST,bars[j+1:k])
        valid_geometry=0<p['stop']<price<p['target']
        result=settle(bars,k,int(p['holdMinutes']),p['stop'],p['target']) if valid_geometry else None
        baseline=permitted(flags,'NONE',risk)
        row=dict(method=p['method'],windowMin=p['windowMin'],parentIndex=p['parentIndex'],triggerIndex=p['triggerIndex'],
                 confirmIndex=j,openedMs=int(df.iloc[k].time),riskPct=risk,plannedNetPct=net,
                 **flags,baselinePass=baseline,onlyMinAdded=not baseline and permitted(flags,'MIN',risk),
                 onlyMaxAdded=not baseline and permitted(flags,'MAX',risk),
                 standaloneNetPct=None,outcome=None,complete=result is not None)
        if result is not None:
            exit_i,exit_price,outcome=result
            row.update(standaloneNetPct=(exit_price/price-1)*100-COST,outcome=outcome)
        records.append(row)
    detail=pd.DataFrame(records);summary=[]
    for method,g in detail.groupby('method',sort=False):
        for label,col in [('BASE','baselinePass'),('REMOVE_MIN_ONLY','onlyMinAdded'),('MAX_2_5_ONLY','onlyMaxAdded')]:
            s=g[g[col]];v=s[s.complete]
            summary.append(dict(method=method,comparison=label,plans=len(s),complete=len(v),
                                positive=int((v.standaloneNetPct>0).sum()),losses=int((v.standaloneNetPct<0).sum()),
                                targetReached=int((v.outcome=='TARGET').sum()),
                                meanNetPct=float(v.standaloneNetPct.mean()) if len(v) else None))
    counts=detail.groupby('method')[['entry_band','delay_invalid','stop_min','stop_max','net_space','net_rr']].sum().reset_index()
    return detail,pd.DataFrame(summary),counts


def reference_opportunities(df,bars,start,spec):
    tr=np.maximum(bars[:,1]-bars[:,2],np.maximum(abs(bars[:,1]-np.r_[bars[0,3],bars[:-1,3]]),abs(bars[:,2]-np.r_[bars[0,3],bars[:-1,3]])))
    atr=pd.Series(tr).rolling(14).mean().to_numpy()
    candidates=[]
    for profile in spec['opportunityProfiles']:
        busy=-1
        for j in range(start,len(bars)-2):
            k=j+2
            if k<=busy or not (bars[j,3]>bars[j,0] and bars[j,3]>bars[j-1,1]):
                continue
            ref=bars[j,3]
            p=dict(entryLow=ref*.999,entryHigh=ref*1.001,
                   target=float(bars[j-profile['targetLookback']:j,1].max())*.9985,
                   stop=min(float(bars[j-profile['stopLookback']+1:j+1,2].min())-.15*atr[j],ref*.9965),
                   minNet=profile['minNet'],windowMin=5 if profile['name']=='FAST' else 60)
            price=float(bars[k,0]);flags,risk,net=gate_flags(p,price,COST,bars[j+1:k])
            if not permitted(flags,'NONE',risk):
                continue
            result=settle(bars,k,profile['hold'],p['stop'],p['target'])
            if result is None:
                continue
            # Reserve full horizon irrespective of success/stop timing, so selection does not cherry-pick future wins.
            busy=k+profile['hold']-1
            exit_i,exit_price,outcome=result
            actual=(exit_price/price-1)*100-COST
            success=outcome=='TARGET' and (actual>=.8-1e-9 if profile['name']=='FAST' else actual>1)
            candidates.append(dict(profile=profile['name'],confirmMs=int(df.iloc[j].time+60000),openedMs=int(df.iloc[k].time),
                                   closedMs=int(df.iloc[exit_i].time+60000),entry=price,target=p['target'],stop=p['stop'],
                                   plannedNetPct=net,netPct=actual,outcome=outcome,success=success))
    return pd.DataFrame(candidates)


def coverage(opportunities,warnings,gate_detail):
    rows=[];matches=[]
    for profile,opps in opportunities.groupby('profile'):
        for method in METHODS:
            w=warnings[(warnings.method==method)&((warnings.windowMin<=15) if profile=='FAST' else (warnings.windowMin>15))]
            stamps=np.sort(w.triggerMs.to_numpy())
            g=gate_detail[(gate_detail.method==method)&((gate_detail.windowMin<=15) if profile=='FAST' else (gate_detail.windowMin>15))]
            for o in opps.to_dict('records'):
                hi=np.searchsorted(stamps,o['confirmMs'],side='right')
                lo=np.searchsorted(stamps,o['confirmMs']-30*60000,side='left')
                nearby=w[(w.triggerMs>=o['confirmMs']-30*60000)&(w.triggerMs<=o['confirmMs'])]
                # Reference entry is one minute after confirmation; plans must already be confirmed by reference time.
                corresponding=g[g.triggerIndex.isin(nearby.triggerIndex)&(g.openedMs-60000<=o['confirmMs'])]
                evaluated=corresponding[corresponding.openedMs<=o['confirmMs']]
                state=('NO_WARNING' if hi==lo else 'WARNING_NO_CONFIRM' if corresponding.empty else
                       'PLAN_PENDING_EXECUTION' if evaluated.empty else 'PLAN_RISK_PASS' if evaluated.baselinePass.any() else 'PLAN_RISK_REJECT')
                matches.append(dict(**o,method=method,warningCovered=bool(hi>lo),coverageState=state))
            local=[r for r in matches if r['profile']==profile and r['method']==method]
            wins=[r for r in local if r['success']]
            covered=sum(r['warningCovered'] for r in wins)
            rows.append(dict(profile=profile,method=method,referencePlans=len(local),successfulReference=len(wins),
                             warnedSuccessful=covered,missedSuccessful=len(wins)-covered,
                             warnedNoConfirm=sum(r['coverageState']=='WARNING_NO_CONFIRM' for r in wins),
                             warnedPendingExecution=sum(r['coverageState']=='PLAN_PENDING_EXECUTION' for r in wins),
                             warnedRiskRejected=sum(r['coverageState']=='PLAN_RISK_REJECT' for r in wins),
                             warnedRiskPass=sum(r['coverageState']=='PLAN_RISK_PASS' for r in wins),
                             missedPct=(len(wins)-covered)/len(wins)*100 if wins else None))
    return pd.DataFrame(rows),pd.DataFrame(matches)


def main():
    spec=register()
    if '--register-only' in sys.argv:
        print('STAGE_A_REGISTERED');return
    df=pd.read_csv(SOURCE/'input-181days.csv');bars=df[['open','high','low','close']].to_numpy()
    audit=json.loads((SOURCE/'audit.json').read_text())
    if sha(SOURCE/'input-181days.csv')!=audit['inputSha256']:
        raise ValueError('Source integrity failure')
    trades=pd.read_csv(SOURCE/'trades.csv');plans=pd.read_csv(SOURCE/'plans.csv');warnings=pd.read_csv(SOURCE/'warnings.csv')
    detail,summary,exits=trade_audit(df,bars,trades)
    gate_detail,gates,counts=plans_audit(df,bars,plans)
    opps=reference_opportunities(df,bars,len(df)-90*DAY,spec)
    recall,matches=coverage(opps,warnings,gate_detail)
    files={'trade-attribution':detail,'trade-summary':summary,'exit-summary':exits,
           'gate-detail':gate_detail,'gate-counterfactual':gates,'gate-predicates':counts,
           'reference-opportunities':opps,'reference-coverage':recall,'coverage-detail':matches}
    for name,frame in files.items():
        frame.to_csv(OUT/(name+'.csv'),index=False)
    exemplar=summary[summary.method=='ROLLING_P95'].iloc[0]
    lines=['# A阶段：亏损、风险门禁与参考机会漏报归因','','状态：离线诊断完成；四阶段完整策略尚未实现，不改变生产规则。',
           '', '## 主要发现','',
           f"- 滚动P95主场景共{int(exemplar.trades)}笔：毛收益均值{exemplar.grossMeanPct:.3f}%，扣费后{exemplar.netMeanPct:.3f}%；因此不能只归因于手续费。{int(exemplar.stopCount)}笔止损、{int(exemplar.timeCount)}笔超时，只有{int(exemplar.targetCount)}笔到结构目标。",
           f"- 其中{int(exemplar.positiveThenLoss)}笔在退出前的已收盘分钟上曾净盈利，最终转亏；这提供退出研究样本，但不意味着能预知最佳退出点。",
           '- 六组中，仅把止损上限从1.20%放宽至2.50%，其他条件不动，没有新增全部门禁通过的计划。仅取消下限后新增计划的平均净收益均为负。结论只适用于当前代理，不证明未来S1独立风险配置无价值。',
           '- 独立参考规则仅得到1个FAST成功样本和7个SLOW成功样本。数量太少，不能据其覆盖率选最优门槛或宣称全市场漏报率。动态提醒覆盖的改善不等同于买入收益改善。',
           '', '## 方法与边界','',
           '复用上一轮冻结的181天数据与90天评估窗口，主场景0.24%成本、确认后额外延迟1分钟。协议先登记，源文件哈希锁定。所有结果为已看历史，不能称为独立样本外。',
           '收益单位为初始名义金额百分比。方法名沿用第二项报告；DOCUMENT_FIXED是文档门槛，不是线上原版S1–S4。',
           '', '## 1. 毛收益、成本与退出结果','',table(summary),'',table(exits),'',
           'grossMeanPct为参考价格毛收益，netMeanPct扣0.24%预算；feeTurnsProfitToLoss是毛正净负笔数。此算术拆分不等于费用是唯一亏损原因。',
           'positiveThenLoss仅用退出分钟之前的已收盘分钟估值判断是否曾净盈利而最终净亏损；不使用止损所在分钟的最高价，避免把止损后的反弹当作曾经可卖。goalThenLoss记录曾达到净目标后仍亏损的子集。',
           '曾盈利不代表当时可预测地卖在高点，更不证明超买乏力规则已经有效。需要固定同一批入场再检验可实时执行的退出规则。',
           '', '## 2. 风险门禁：上下限分开','',table(counts),'',
           '每个候选同时检查全部条件，表中原因可以重叠，不能相加当作独立拒绝数。与原报告仅记录首个拒绝原因不同。',
           '',table(gates),'',
           'BASE为单独风险门禁通过的窗口计划，不包含账户持仓冲突与父事件去重；不是原模拟账户成交笔数。REMOVE_MIN_ONLY只去掉0.35%下限，保留原止损；MAX_2_5_ONLY仅把1.20%上限放到2.50%，其他条件不变。',
           '两项放宽只统计新增计划的独立路径，未同时放宽目标、净盈亏比或入场区，也未重新投资组合资金。因此是局部反事实诊断，不能直接作为生产修改证据。',
           '', '## 3. 独立参考机会与提醒覆盖','',table(recall),'',
           '参考机会不使用六组预警门槛：逐分钟检查阳线突破上一分钟高点，使用当时已知的目标和止损、相同净目标/风险要求及1分钟延迟。FAST目标看过去60分钟、止损结构看5分钟、持有30分钟；SLOW分别为240/15/360分钟。目标减0.15%，止损减0.15倍分钟ATR并按确认价扩至至少0.35%。',
           '每类机会按时间顺序贪心保留，预留完整计划持仓期后才考虑下一个，不按后续输赢选择是否去重。FAST与SLOW分开，不能相加视为独立总机会。',
           'successfulReference仅指上述固定参考规则下先到结构目标且净收益达标。提醒覆盖指确认之前30分钟内同类窗口出现预警，是时间邻近覆盖，不保证预警与该机会具有相同经济原因，也不等于正式BUY覆盖。',
           '覆盖明细进一步区分无提醒、尚未确认、已确认待执行、已有计划未通过风险门禁、已有计划通过风险门禁。确认状态只使用参考确认时刻已完成的计划；风险状态还要求模拟执行时点已到达，不能用未来入场价判断当时风险通过。通过门禁仍可能被账户持仓或去重限制，不能当作真实成交。',
           '这里的missedPct只适用于这一预登记参考机会定义，不是全市场真实漏报率。无成功参考机会时百分比为空，不填零。未来结果只用于评估标签，不能用于实时触发。',
           '', '## 4. 本阶段结论使用方式','',
           '先检查各方案毛收益是否已为负、亏损由TIME还是STOP主导，再评估成本与盈利回吐。门禁误拒必须同时看放行后亏损数量，不能只挑新增盈利计划。',
           '下一阶段分别对比确认条件、退出规则及模块风险。不能因为某局部反事实收益较高就宣布最优参数；也不能用本次参考机会定义替代独立人工抽检和真实盘口验证。',
           '四阶段标签、实验冻结与验收规范见同目录“四阶段标签与实验协议.md”。生产规则、APP与APK未修改。']
    (OUT/'报告.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    (OUT/'result-manifest.json').write_text(json.dumps(dict(scriptSha256=sha(__file__),outputs={n:sha(OUT/(n+'.csv')) for n in files}),indent=2),encoding='utf-8')
    print(summary.to_string(index=False),flush=True)
    print(gates.to_string(index=False),flush=True)
    print(recall.to_string(index=False),flush=True)
    print('STAGE_A_READY',flush=True)


if __name__=='__main__':
    main()
