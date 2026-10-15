import React,{useEffect,useState} from 'react';
import {messages,readMessage,syncInbox,InboxMessage} from '../services/inbox';
export function MessagePanel(){
 const [open,setOpen]=useState(false);
 const [rows,setRows]=useState(messages);const [history,setHistory]=useState(false);const [category,setCategory]=useState('全部');const [selected,setSelected]=useState<InboxMessage|null>(null);
 useEffect(()=>{const refresh=()=>setRows(messages());window.addEventListener('cryptog-inbox',refresh);void syncInbox();const timer=setInterval(()=>void syncInbox(),15000);return()=>{clearInterval(timer);window.removeEventListener('cryptog-inbox',refresh);};},[]);
 const visible=rows.filter(m=>m.read===history&&(category==='全部'||category===m.category));
 return <section className="rounded-xl border border-gray-700 bg-[#171a21] p-3 space-y-2" aria-label="消息中心">
 <div className="flex justify-between text-xs"><button aria-expanded={open} className="min-h-11 flex-1 text-left" onClick={()=>setOpen(!open)}><strong>消息 · {rows.filter(m=>!m.read).length} 未读 {open?'▴':'▾'}</strong></button><button className="text-blue-300 min-h-8" onClick={()=>{setOpen(true);setHistory(!history);setSelected(null);}}>{history?'返回未读':'消息历史'}</button></div>
 {open&&<div className="space-y-2"><div className="grid grid-cols-4 gap-2">{['全部','观察','接近','入场','失效','摘要','退出','测试'].map(c=><button className={`min-h-11 px-2 py-2 rounded-lg text-xs ${category===c?'bg-blue-900 text-white':'text-gray-400 bg-gray-800'}`} key={c} onClick={()=>setCategory(c)}>{c}</button>)}</div>
 {(history?visible:visible.slice(0,5)).map(m=><button className="block w-full text-left border-t border-gray-700 py-2" key={m.id} onClick={()=>{setSelected(m);readMessage(m.id);}}><div className="flex justify-between text-[10px] text-gray-400"><span>{m.category}</span><time>{new Date(m.at).toLocaleString()}</time></div><p className="text-xs mt-1 text-gray-200">{m.title}</p><p className="text-[11px] truncate text-gray-400">{m.body}</p></button>)}
 {!visible.length&&<p className="text-xs text-gray-500 py-2">{history?'暂无已读历史':'暂无未读消息'}</p>}
 {!history&&visible.length>5&&<p className="text-[10px] text-gray-400">显示最新5条，已读后显示其余未读消息。</p>}
 {selected&&<div role="dialog" aria-label="消息详情" className="rounded-lg bg-gray-800 p-3 text-xs space-y-2"><strong>{selected.title}</strong><p className="whitespace-pre-wrap leading-relaxed">{selected.body}</p><p className="text-[10px] text-gray-400">已标记已读并保存到消息历史。观察/接近消息不代表买入指令。</p><button className="text-blue-300 min-h-8" onClick={()=>setSelected(null)}>关闭详情</button></div>}
 </div>}
 </section>;
}
