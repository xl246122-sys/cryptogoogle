import React,{useEffect,useState} from 'react';
import {notificationEvidence,notificationEvidenceReport} from '../services/notificationEvidence';
export function NotificationEvidencePanel(){
 const [rows,setRows]=useState(notificationEvidence),[note,setNote]=useState('');
 useEffect(()=>{const refresh=()=>setRows(notificationEvidence());window.addEventListener('cryptog-notification-evidence',refresh);
  return ()=>window.removeEventListener('cryptog-notification-evidence',refresh);},[]);
 return <details className="rounded-xl border border-slate-700 bg-slate-900 p-3 text-xs text-slate-300">
  <summary className="min-h-8 cursor-pointer font-semibold">本机通知验收记录 · {rows.length} 条</summary>
  <p className="my-2 text-amber-300">前台接收、点击分别记录。没有接收回调不代表锁屏未送达；铃声和弹窗请在手机上确认。</p>
  <p>仅保留最近300条本机记录；不包含访问凭据或消息正文。</p>
  {!rows.length&&<p className="my-3">尚无本机通知回调记录，等待手机测试。</p>}
  <ol className="my-3 space-y-2">{rows.slice(-10).reverse().map(r=><li key={`${r.id}:${r.revision}:${r.origin}`} className="rounded bg-black/20 p-2 break-all">
   <p>{r.origin==='opened'?'点击通知':'APP前台收到'} · {new Date(r.clientAtMs).toLocaleString()}</p>
   <p>{r.eventType} · {r.id}{r.revision!==null?` · 版本${r.revision}`:''}</p>
  </li>)}</ol>
  <button className="min-h-10 rounded bg-blue-900 px-3" onClick={()=>void navigator.clipboard.writeText(JSON.stringify(notificationEvidenceReport(),null,2)).then(()=>setNote('已复制本机验收记录')).catch(()=>setNote('复制失败，请记录上方事件编号和时间'))}>复制验收记录</button>
  <span role="status" className="ml-2">{note}</span>
 </details>;
}
