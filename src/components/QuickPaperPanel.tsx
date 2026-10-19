import React,{useEffect,useRef,useState} from 'react';
import type {MarketTicker} from '../types/crypto';
import {libraryJournal,rememberAction,newEventId,flushLibraryQueue} from '../services/modelLibrary';
import {paperAction,paperSummary,PAPER_STRATEGY,LEGACY_PAPER_STRATEGY} from '../services/quickPaper';
import {fetchMarketState} from '../services/marketState';
export function QuickPaperPanel({ticker}:{ticker?:MarketTicker}){
 const [rows,setRows]=useState(()=>libraryJournal());const [message,setMessage]=useState('');const [busy,setBusy]=useState(false);const lock=useRef(false);
 useEffect(()=>{const refresh=()=>setRows(libraryJournal());window.addEventListener('library-journal-changed',refresh);window.addEventListener('storage',refresh);const timer=setInterval(()=>void flushLibraryQueue(),15000);return()=>{clearInterval(timer);window.removeEventListener('library-journal-changed',refresh);window.removeEventListener('storage',refresh);};},[]);
 const s=paperSummary(rows);const legacy=paperSummary(rows,LEGACY_PAPER_STRATEGY);const price=ticker?.price||0;const journal=rows.filter(r=>r.action.strategy===PAPER_STRATEGY);const pending=journal.filter(r=>r.status==='pending').length;const rejected=journal.filter(r=>r.status==='rejected').length;
 const trade=async(side:'BUY'|'SELL')=>{
  if(lock.current)return;lock.current=true;setBusy(true);
  try{let id=localStorage.getItem('cryptog_quick_paper_id');if(!id){id='paper-'+newEventId();localStorage.setItem('cryptog_quick_paper_id',id);}
   const market=await fetchMarketState();
   if(!market.costSnapshot || Date.now()-market.costSnapshot.applicableAtMs>10000)throw new Error('等待云端最新成本快照后再模拟');
   const action=paperAction(side,price,ticker?.lastUpdate||0,Date.now(),libraryJournal(),id+'-v2',market.costSnapshot);rememberAction(action);setRows(libraryJournal());setMessage(side==='BUY'?'已记录模拟买入 500 USDT':'已记录模拟卖出（最多 500 USDT）');
  }catch(e){setMessage(e instanceof Error?e.message:String(e));}
  finally{setTimeout(()=>{lock.current=false;setBusy(false);},700);}
 };
 return <section className="rounded-2xl border border-[#303744] bg-[#1c2029] p-3 space-y-3" aria-label="一键模拟交易">
  <div className="flex items-center justify-between"><h2 className="text-sm font-semibold">BTC 一键模拟</h2><span className="text-xs text-gray-400">{price>0?`${price.toLocaleString()} USDT`:'等待行情'}</span></div>
  <div className="grid grid-cols-3 gap-2 text-xs">
   <div className="rounded-lg bg-black/20 p-2"><p className="text-gray-400">模拟持仓</p><p className="mt-1">{s.quantity.toFixed(8)} BTC</p></div>
   <div className="rounded-lg bg-black/20 p-2"><p className="text-gray-400">持仓市值</p><p className="mt-1">{price>0?(s.quantity*price).toFixed(2):'—'} USDT</p></div>
   <div className="rounded-lg bg-black/20 p-2"><p className="text-gray-400">已实现净收益*</p><p className={s.realized>=0?'mt-1 text-emerald-300':'mt-1 text-red-300'}>{s.realized.toFixed(2)} USDT</p></div>
  </div>
  <div className="grid grid-cols-2 gap-3"><button disabled={busy||price<=0} onClick={()=>trade('BUY')} className="rounded-xl bg-emerald-600 py-3 font-semibold disabled:opacity-40">买入 500 USDT</button><button disabled={busy||price<=0||s.quantity<=1e-12} onClick={()=>trade('SELL')} className="rounded-xl bg-rose-600 py-3 font-semibold disabled:opacity-40">卖出 500 USDT</button></div>
  <p role="status" className="text-xs text-blue-200">{message||'点击即记录；不足 500 USDT 时卖出全部剩余模拟持仓。'}</p>
  <p className="text-[10px] text-gray-400">仅模拟，不向币安下单。*参考行情价格；费用、滑点按买入时云端成本快照计入，下限 0.24%。旧版 0.11% 记录单独保留。</p>
  <p className="text-[10px] text-gray-400">旧版模拟：剩余 {legacy.quantity.toFixed(8)} BTC；已实现 {legacy.realized.toFixed(2)} USDT（0.11% 旧口径）</p>
  <details className="text-xs text-gray-400"><summary>实验记录 {journal.length} · 待同步 {pending} · 被拒绝 {rejected}</summary><div className="max-h-48 overflow-auto">{journal.slice(-20).reverse().map(r=><p className="py-2 border-b border-gray-700" key={r.action.eventId}>{new Date(r.action.actedAtMs).toLocaleString()} · {r.action.recordType==='SIM_BUY'?'模拟买入':'模拟卖出'} · {r.action.entryPrice && ((r.action.positionSize||0)/r.action.entryPrice).toFixed(8)} BTC · {r.status==='acked'?'已同步':r.status==='pending'?'待同步':'被拒绝'}{r.error?`：${r.error}`:''}</p>)}</div></details>
 </section>;
}
