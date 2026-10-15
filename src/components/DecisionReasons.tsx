import React, {useId,useState} from 'react';
import type {MacroTrendAnalysis} from '../types/crypto';
export function DecisionReasons({market:m}:{market:MacroTrendAnalysis}){
 const [open,setOpen]=useState(false);const id=useId();
 return <section className="rounded-xl border border-[#303744] bg-[#171a21] px-3 py-2" aria-label="本轮扫描依据">
  <button type="button" aria-expanded={open} aria-controls={id} onClick={()=>setOpen(!open)} className="w-full min-h-8 flex items-center justify-between text-xs text-gray-300">
   <span>扫描依据</span><span className="text-blue-300">{open?'收起详情 ▴':'查看详情 ▾'}</span>
  </button>
  {open && <div id={id} className="pt-2 space-y-2">
  {!m.dataReady?<p className="text-xs text-amber-300">行情不可用，暂停评估；不能据此判断没有机会。</p>:<>
   <p className="text-xs leading-relaxed text-amber-200">{m.rejectionReasons?.join('；') || '正式候选需核对有效入场区间与时效。'}</p>
   {!m.research?.length?<p className="text-[11px] text-gray-500">影子研究状态尚未提供</p>:m.research.map(r=><details key={r.label} className="text-[11px] text-gray-400">
    <summary className="cursor-pointer py-1">{r.label} · {r.status==='SHADOW_CANDIDATE'?'研究条件满足':r.status==='ERROR'?'研究异常':'未满足研究条件'}</summary>
    <p className="pt-1 leading-relaxed">{r.reasons.join('；') || '研究条件已满足；是否生成或发送实验候选以通知记录为准，盈利能力待验证。'}</p>
   </details>)}
  </>}
 </div>}
 </section>;
}
