import React, {useEffect, useRef, useState} from 'react';
import {connection, saveConnection, clearConnection, editedConnection, ServerConnection} from '../services/serverConnection';
import {notificationService} from '../services/notificationService';
import {bindExitDevice} from '../services/exitPush';
import {inspectConnection, ConnectionStatus} from '../services/connectionStatus';
function savedConnection(){try{return connection();}catch{return null;}}
export function ServerConnectionPanel() {
  const [saved,setSaved]=useState(savedConnection);
  const [url,setUrl]=useState(()=>savedConnection()?.url??'https://43.163.203.127:8788');
  const [token,setToken]=useState('');
  const [expanded,setExpanded]=useState(false);
  const [status,setStatus]=useState<ConnectionStatus|null>(null);
  const [message,setMessage]=useState('');
  const [error,setError]=useState('');
  const [busy,setBusy]=useState(false);
  const [permission,setPermission]=useState(false);
  const working=useRef(false),mounted=useRef(true);
  async function check(){
    try{const granted=await notificationService.refreshPermission();const next=await inspectConnection(notificationService.getDeviceToken());if(mounted.current){setStatus(next);setPermission(granted);}return next;}
    catch(e){if(mounted.current)setStatus(null);throw e;}
  }
  async function run(action:()=>Promise<void>,quiet=false){
    if(working.current)return;working.current=true;setBusy(true);
    if(!quiet){setError('');setMessage('');}
    try{await action();if(mounted.current){setError('');if(quiet)setMessage('');}}
    catch(e){if(mounted.current)setError(e instanceof Error?e.message:'检测失败，请重试');}
    finally{working.current=false;if(mounted.current)setBusy(false);}
  }
  async function bind(){
    const pushToken=await notificationService.ensureDeviceToken();
    await bindExitDevice(pushToken);
    const next=await check();
    if(next.binding!=='bound')throw new Error('尚未确认本机绑定，请重新检测');
    setMessage(next.pushEnabled?'本机绑定成功':'本机绑定成功，服务端推送未开启');
  }
  async function setup(value:ServerConnection){
    saveConnection(value);setSaved(connection());setUrl(connection().url);setToken('');setStatus(null);
    setMessage('凭据已保存，正在验证连接…');
    await check();setExpanded(false);setMessage('连接验证通过，正在绑定本机…');await bind();
  }
  useEffect(()=>{
    mounted.current=true;
    const refresh=()=>{if(savedConnection() && document.visibilityState!=='hidden')void run(async()=>{await check();},true);};
    refresh();const timer=setInterval(refresh,10000);document.addEventListener('visibilitychange',refresh);
    return()=>{mounted.current=false;clearInterval(timer);document.removeEventListener('visibilitychange',refresh);};
  },[]);
  const bound=status?.binding==='bound' && permission;
  const backend=!saved?'未配置':!status?'待验证':status.backendHealthy?'正常':'行情暂不可用';
  const phone=!saved?'未绑定':!status?'待验证':status.binding==='bound'?(permission?'已绑定':'通知权限未开启'):status.binding==='other'?'绑定了其他设备':status.binding==='unknown'?'待核对本机':'未绑定';
  const hint=error || (status && !status.pushEnabled?'服务端推送未开启':status && !status.exitWorkerHealthy?'退出通知后台待恢复':message || (saved?'凭据已保存；绑定状态不代表通知必达':'请配置服务器并绑定本机'));
  return <section className="rounded-2xl border border-[#303744] bg-[#1c2029] p-3 space-y-2" aria-label="云端连接">
    <div className="flex items-center justify-between gap-2">
      <div className="flex items-center gap-2"><h2 className="text-sm font-semibold">云端连接</h2>{saved && <span className="text-[11px] text-gray-400">凭据已保存</span>}</div>
      <button className="text-xs text-blue-300 min-h-8 px-2" aria-expanded={expanded} onClick={()=>setExpanded(!expanded)}>{expanded?'收起':'配置'}</button>
    </div>
    <div className="grid grid-cols-2 gap-2 text-xs">
      <div className="rounded-lg bg-black/20 px-2 py-2 flex justify-between gap-1"><span className="text-gray-400">后端</span><span className={status?.backendHealthy?'text-emerald-400':'text-amber-300'}>{backend}</span></div>
      <div className="rounded-lg bg-black/20 px-2 py-2 flex justify-between gap-1"><span className="text-gray-400">本机通知</span><span className={bound?'text-emerald-400':'text-amber-300'}>{phone}</span></div>
    </div>
    <div className="flex items-center gap-2">
      <p role={error?'alert':'status'} className={`flex-1 min-w-0 text-[11px] break-words ${error?'text-amber-300':'text-gray-400'}`}>{hint}</p>
      <button disabled={busy||!saved} onClick={()=>void run(async()=>{await check();setMessage('状态检测完成');})} className="text-xs min-h-9 px-2 text-blue-300 disabled:opacity-40">{busy?'处理中…':'检测'}</button>
      {!bound && saved && <button disabled={busy} onClick={()=>void run(bind)} className="text-xs min-h-9 px-2 rounded-lg bg-blue-900 disabled:opacity-40">绑定本机</button>}
    </div>
    {expanded && <div className="border-t border-gray-700 pt-3 space-y-3">
      <label className="block text-xs text-gray-400">HTTPS 地址<input disabled={busy} aria-label="HTTPS 地址" className="block mt-1 w-full p-2 rounded-lg bg-gray-900 text-sm text-white" value={url} onChange={e=>setUrl(e.target.value)}/></label>
      <label className="block text-xs text-gray-400">设备访问凭据<input disabled={busy} aria-label="设备访问凭据" type="password" autoComplete="off" className="block mt-1 w-full p-2 rounded-lg bg-gray-900 text-sm text-white" value={token} placeholder={saved?'已保存凭据 · 留空沿用':'输入设备访问凭据'} onChange={e=>setToken(e.target.value)}/></label>
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <button disabled={busy} className="p-2 min-h-9 bg-blue-900 rounded-lg disabled:opacity-40" onClick={()=>void run(()=>setup(editedConnection(url,token)))}>保存并绑定</button>
        <label className={`p-2 text-blue-300 ${busy?'opacity-40':''}`}>导入并绑定<input disabled={busy} type="file" accept="application/json,.json" className="sr-only" onChange={e=>{
          const file=e.currentTarget.files?.[0];e.currentTarget.value='';if(!file)return;
          void run(async()=>{if(file.size>8192)throw new Error('配置文件过大');await setup(JSON.parse(await file.text()));});
        }}/></label>
        {saved && <button disabled={busy} className="p-2 text-gray-400" onClick={()=>void run(async()=>{
          await bindExitDevice(null);clearConnection();setSaved(null);setStatus(null);setToken('');setMessage('已解绑并移除连接，本地成交记录保留');
        })}>解绑并移除</button>}
      </div>
      <p className="text-[11px] text-gray-500">每个凭据绑定一台手机。凭据隐藏保存；更换手机后需重新绑定。</p>
    </div>}
  </section>;
}
