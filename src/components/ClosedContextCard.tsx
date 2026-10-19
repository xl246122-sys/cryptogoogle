import React from 'react';
import type {MacroTrendAnalysis} from '../types/crypto';
export function ClosedContextCard({market}:{market:MacroTrendAnalysis}) {
 const evidence=market.decisionContext;
 const cached=market.stateSource==='CACHE';
 return <details className="rounded-xl border border-[#383e4c] p-3 text-xs text-gray-300 space-y-2">
  <summary className="font-semibold">收盘决策环境 · {cached?'历史缓存':evidence?'云端快照':'等待证据'}</summary>
  <p>上方趋势随现价变化；模块准入使用以下已收盘数据。时间为本机时区。</p>
  {evidence ? <><div className="grid grid-cols-3 gap-2">{[['d1','1D'],['h4','4H'],['h1','1H']].map(([tf,name])=><div key={tf} className="rounded-lg bg-[#171a21] p-2"><p>{name} · {evidence.frames[tf].state}</p><p className="mt-1 text-[10px]">{new Date(evidence.frames[tf].closeTime).toLocaleString()}</p></div>)}</div>
   <p>环境准入：{Object.entries(evidence.gates).filter(([m])=>['S1','S2','S3','S4'].includes(m)).map(([m,on])=>`${m} ${on?'开放':'关闭'}`).join(' · ')}。开放仍需形态、成本及风险门槛。</p>
   {cached && <p>缓存仅供回看，当前准入状态待同步。</p>}
   <p>快照：{new Date(evidence.atMs).toLocaleString()}</p>
  </>:<p>接口尚未提供与决策匹配的收盘时间，状态未知。</p>}
  <p>S1–S4 仍为观察级·未验证；S5 仅研究，不发买入提示。</p>
 </details>;
}
