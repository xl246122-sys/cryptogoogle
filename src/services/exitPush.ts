import {connection} from './serverConnection';

const QUEUE='cryptog_exit_receipts_v1', BINDING='cryptog_exit_binding_v1';
interface Receipt {deliveryId:string;kind:'FOREGROUND_RECEIVED'|'OPENED';clientAtMs:number;scope:string}
async function scope() {
  const config=connection();
  const bytes=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(`${config.url}|${config.token}`));
  return {config,key:Array.from(new Uint8Array(bytes),b=>b.toString(16).padStart(2,'0')).join('')};
}
async function post(config:ReturnType<typeof connection>,path:string,body:object) {
  const control=new AbortController();const timer=setTimeout(()=>control.abort(),5000);
  try {
    const response=await fetch(`${config.url}/model-library/${path}`,{method:'POST',headers:{'Content-Type':'application/json','X-Library-Token':config.token},body:JSON.stringify(body),signal:control.signal});
    const value=await response.json();if(!response.ok || value.ok!==true)throw new Error('退出通知服务未确认，请重试');
    return value;
  } finally{clearTimeout(timer);}
}
function readQueue():Receipt[] {
  const raw=localStorage.getItem(QUEUE);if(!raw)return [];
  const rows=JSON.parse(raw);
  if(!Array.isArray(rows) || rows.some(r=>typeof r?.deliveryId!=='string' || !['FOREGROUND_RECEIVED','OPENED'].includes(r.kind) || !Number.isFinite(r.clientAtMs) || typeof r.scope!=='string'))throw new Error('退出回执记录损坏，请保留本地数据排查');
  return rows;
}
export function parseExitPush(data:any) {
  if(data?.eventType!=='POSITION_EXIT_NOTICE')return null;
  if(typeof data.deliveryId!=='string' || typeof data.noticeId!=='string' || !/^exit-delivery-[a-f0-9]{64}$/.test(data.deliveryId) || !/^exit-[a-f0-9]{64}$/.test(data.noticeId)
    || !Number.isFinite(Number(data.issuedAtMs)) || !Number.isFinite(Number(data.expiresAtMs))
    || Number(data.expiresAtMs)<=Number(data.issuedAtMs))return null;
  return {deliveryId:data.deliveryId as string,noticeId:data.noticeId as string};
}
export async function recordExitPush(data:any, origin:'received'|'opened') {
  const parsed=parseExitPush(data);if(!parsed)return false;
  const clientAtMs=Date.now();const current=await scope();const rows=readQueue();
  const kind=origin==='opened'?'OPENED':'FOREGROUND_RECEIVED';
  if(!rows.some(r=>r.deliveryId===parsed.deliveryId && r.kind===kind && r.scope===current.key)) {
    if(rows.length>=2000)throw new Error('退出回执队列已满，需恢复服务器同步');
    rows.push({deliveryId:parsed.deliveryId,kind,clientAtMs,scope:current.key});
    localStorage.setItem(QUEUE,JSON.stringify(rows));
  }
  return true;
}
let flushing=false;
export async function flushExitReceipts() {
  if(flushing)return;flushing=true;
  try {
    const current=await scope();
    for(const row of readQueue().filter(r=>r.scope===current.key)) {
      const ack=await post(current.config,'exit-receipt',row);
      if(ack.deliveryId!==row.deliveryId || ack.kind!==row.kind || !Number.isFinite(ack.serverReceivedAtMs))throw new Error('退出回执确认不匹配');
      // Re-read to preserve receipts queued while the request was in flight.
      localStorage.setItem(QUEUE,JSON.stringify(readQueue().filter(r=>!(r.deliveryId===row.deliveryId && r.kind===row.kind && r.scope===row.scope))));
    }
  } finally {flushing=false;}
}
export async function bindExitDevice(token:string|null, remember=true) {
  const current=await scope();const result=await post(current.config,'exit-device',{token});
  if(result.registered!==(token!==null))throw new Error('设备绑定确认不匹配');
  if(remember){if(token)localStorage.setItem(BINDING,current.key);else localStorage.removeItem(BINDING);}
  return result.pushEnabled===true;
}
export async function refreshExitDevice(token:string) {
  const current=await scope();
  if(localStorage.getItem(BINDING)===current.key)await bindExitDevice(token,false);
}
