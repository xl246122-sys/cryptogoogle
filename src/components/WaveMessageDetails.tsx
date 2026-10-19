import React from 'react';
import {parseWaveMessage,waveStatus} from '../services/waveState';
export function WaveMessageDetails({data,now=Date.now()}:{data:any;now?:number}) {
 const d=parseWaveMessage(data);if(!d)return null;
 const p=d.position;const fmt=(v:unknown)=>typeof v==='number'&&Number.isFinite(v)?v.toFixed(3):'未提供';
 return <section aria-label="四阶段研究详情" className="rounded-xl border border-slate-700 bg-slate-950 p-3 space-y-2 text-xs text-slate-300">
  <p className="font-semibold text-amber-300">{waveStatus(d,now)} · 不可作为正式买入指令</p>
  <p>模块：{d.module} / {d.branch} · 状态版本 {d.revision}</p>
  <p>数据时间：{new Date(d.featureAsOfTime).toLocaleString()}</p>
  {d.plan?<><p>计划参考区间：{fmt(d.plan.entryLow)}–{fmt(d.plan.entryHigh)} USDT</p>
   <p>结构止损：{fmt(d.plan.stop)} · 结构目标：{fmt(d.plan.target)}</p>
   <p>预计扣费净空间：{fmt(d.risk?.netTargetPct)}% · 止损距离：{fmt(d.risk?.stopDistancePct)}%</p>
   <p>来回成本预算：{fmt(d.risk?.costPct)}% · 净盈亏比：{fmt(d.risk?.netRR)}</p>
   <p>截止：{new Date(d.plan.expiresAt).toLocaleString()}；目标空间不是保证收益。</p></>:
   !p&&<p>入场、止损与目标：尚未形成</p>}
  {p&&<><p>关联模拟仓位：{p.positionId}</p><p>当时剩余：{p.remainingQuantity.toFixed(8)} BTC · 剩余成本：{fmt(p.remainingCostUsdt)} USDT</p>
   <p>参考可卖价：{fmt(p.bid)} · 预计净盈亏：{fmt(p.estimatedNetUsdt)} USDT（{fmt(p.estimatedNetPct)}%）</p>
   <p>成本按买入快照分摊，只扣一次。以上为提醒时快照，请核对最新余仓；提醒不会自动卖出。</p></>}
  <details><summary>触发依据与追溯</summary><pre className="whitespace-pre-wrap break-all">{JSON.stringify(d.evidence,null,2)}</pre><p className="break-all">事件：{d.eventId} · 父事件：{d.parentEventId}</p></details>
 </section>;
}
