import React from 'react';
import type {TradeSignal} from '../types/crypto';
import {netPlan,percent} from '../services/tradePresentation';
export function NetPlanCard({signal,amount}:{signal:TradeSignal;amount:number}){
 const p=netPlan(signal,amount);
 if(!p)return <p className="text-xs text-amber-200">缺少当前 v2 成本或入场区间，不能计算整笔分批净收益。旧版计划单独保留。</p>;
 const money=(n:number)=>n.toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
 return <section aria-label="整笔分批净收益情景" className="rounded-xl border border-teal-700/50 bg-teal-950/20 p-3 space-y-2 text-xs">
  <h3 className="font-semibold text-teal-200">整笔分批净收益情景</h3>
  <p className="text-gray-300">按入场带上沿 {money(p.entry)} USDT、来回工作成本 {p.cost.toFixed(2)}% 计算。TP1 卖出 50%，余仓按计划退出。</p>
  <div className="grid grid-cols-2 gap-2">
   <div className="rounded-lg bg-black/20 p-2"><p className="text-gray-400">TP1 后余仓净保本</p><p className="mt-1 font-mono">{percent(p.wholeBreakeven)}</p></div>
   <div className="rounded-lg bg-black/20 p-2"><p className="text-gray-400">TP1 + 余仓 TP2</p><p className="mt-1 font-mono">{percent(p.wholeTp2)}</p><p>{p.wholeTp2Usdt===null?'本金未知':`${money(p.wholeTp2Usdt)} USDT`}</p></div>
  </div>
  <p>全部止损情景：{percent(-p.stopNetPct)}；按试算本金约 {p.stopUsdt===null?'未知':money(p.stopUsdt)+' USDT'}。这不是账户 0.5% 风险预算，账户权益需另行核对。</p>
  <p className="text-amber-200">整笔净赚 0.8%：若半仓在 TP1 退出，余仓需净收益 {percent(p.remainingNetForTarget)}，对应退出价约 {money(p.requiredRemainderPrice)} USDT。{p.targetInsidePlan?'该情景价格在 TP2 以内，能否到达尚未知。':'超出现有 TP2，当前计划空间不足；不会据此抬高目标或延长持有。'}</p>
  <p className="text-[11px] text-gray-400">按初始本金加权的计划情景，不是预测收益或实际成交；费用、跳空与成交价格可能使实际结果更差。TP1 后止损移至保本加成本，余仓跟踪 15m EMA20 或 TP2；90 分钟检查、最长 6 小时。</p>
 </section>;
}
