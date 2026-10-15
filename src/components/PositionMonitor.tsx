import React, {useEffect,useState} from 'react';
import {exitLabels,fetchPositions,reviewNotice,type PositionState} from '../services/positions';

const reasons:Record<string,string>={QUOTE_UNAVAILABLE:'行情不可用，无法判断价格退出',NO_VERIFIED_EXIT_PLAN:'缺少关联退出计划',INVALID_EXIT_PLAN:'退出计划无效',BTC_FEE_UNKNOWN:'BTC 手续费未知，剩余数量无法确认',INVALID_INVENTORY:'成交库存不一致',POSITION_LINK_CONFLICT:'关联机会冲突'};
export function PositionMonitor() {
  const [state,setState]=useState<PositionState|null>(null);
  const [error,setError]=useState('');
  const [receipts,setReceipts]=useState<Record<string,number>>({});
  const [pending,setPending]=useState<string|null>(null);
  const [reviewError,setReviewError]=useState('');
  useEffect(()=>{
    const receiptError=()=>setReviewError('退出推送回执尚未同步，请保持连接；收到/打开不代表成交。');
    window.addEventListener('cryptog-exit-receipt-error',receiptError);
    let stopped=false,busy=false;
    const refresh=async()=>{
      if(busy)return;busy=true;
      try {const next=await fetchPositions();if(!stopped){setState(next);setError('');}}
      catch(e){if(!stopped){setError(e instanceof Error?e.message:'持仓服务不可用');setState(old=>old?{...old,fresh:false}:null);}}
      finally{busy=false;}
    };
    void refresh();const timer=setInterval(()=>void refresh(),3000);
    return()=>{stopped=true;clearInterval(timer);window.removeEventListener('cryptog-exit-receipt-error',receiptError);};
  },[]);
  const review=async(id:string)=>{
    setPending(id);setReviewError('');
    try{const at=await reviewNotice(id);setReceipts(old=>({...old,[id]:at}));}
    catch(e){setReviewError(e instanceof Error?e.message:'确认失败，请重试');}
    finally{setPending(null);}
  };
  return <section className="mb-3 rounded-2xl border border-amber-700/50 bg-[#1c2029] p-3 text-xs space-y-2" aria-label="实际持仓退出监控">
    <h2 className="font-semibold text-amber-200">实际持仓 · 退出观察</h2>
    <p className="text-amber-200">{state?.pushEnabled?'服务端已启用设备推送，手机投递效果仍待实测。':'影子验证中，服务端未启用退出推送。'} 提醒不代表成交，请自行管理风险。</p>
    {(error || !state?.fresh) && <p role="status" className="text-red-300">{error || '持仓状态过期'}；保留的数据仅供核对，不能视为正在保护持仓。</p>}
    {state?.fresh && state.positions.length===0 && <p>服务端暂无已同步的手工成交持仓记录。</p>}
    {state?.positions.map(p=><article key={p.positionId} className="border-t border-gray-700 pt-2 space-y-1">
      <p className="break-all">{p.positionId} · {p.status==='CLOSED'?'已记录平仓':p.status==='MONITORING'?'按记录观察':'无法管理'}</p>
      <p>剩余 BTC：{p.remainingQuantity??'未知'} · 更新：{new Date(p.atMs).toLocaleString()}</p>
      {p.deadlineMs && <p>持有到期：{new Date(p.deadlineMs).toLocaleString()}</p>}
      {p.reason && <p className="text-amber-200">{reasons[p.reason]||'退出状态需核对'}</p>}
      {p.unresolvedNotices.map(n=><div key={n.id} className="p-2 bg-red-950/30 rounded-lg space-y-1">
        <p>{exitLabels[n.kind]} · 待核对数量 {n.quantity} BTC</p>
        <p>首次触发 {new Date(n.atMs).toLocaleString()}；历史触发不表示当前价格仍满足条件。</p>
        <button className="underline disabled:opacity-50" disabled={!state.fresh || pending!==null || !!receipts[n.id]} onClick={()=>void review(n.id)}>
          {receipts[n.id]?'服务器已记录查阅（未记录卖出）':pending===n.id?'正在确认…':'我已查阅（不代表卖出）'}
        </button>
      </div>)}
    </article>)}
    {reviewError && <p role="alert" className="text-red-300">{reviewError}</p>}
  </section>;
}
