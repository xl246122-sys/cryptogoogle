import {connection} from './serverConnection';
export interface InboxMessage {id:string;title:string;body:string;at:number;category:string;read:boolean}
const KEY='cryptog_inbox_v1';
export function messages():InboxMessage[]{return JSON.parse(localStorage.getItem(KEY)||'[]');}
function save(rows:InboxMessage[]){localStorage.setItem(KEY,JSON.stringify(rows));window.dispatchEvent(new Event('cryptog-inbox'));}
export function ingestMessage(data:any){
 const id=data?.eventId||data?.id||data?.testId||data?.deliveryId;if(typeof id!=='string')return;
 const title=String(data.title||data.strategyNameZh||'Crypto-G 通知');const body=String(data.body||data.reasonZh||'请查看最新状态');
 const category=data.signalType==='BUY'?'入场':data.eventType==='POSITION_EXIT_NOTICE'?'退出':/测试/.test(title)?'测试':/失效/.test(title)?'失效':/摘要/.test(title)?'摘要':/接近/.test(title)?'接近':'观察';
 const rows=messages();if(rows.some(r=>r.id===id))return;
 const at=Number(data.issuedAtMs||data.timestamp||Number(data.expiresAt)-90000)||Date.now();
 save([{id,title,body,at,category,read:false},...rows].sort((a,b)=>b.at-a.at));
}
export function readMessage(id:string){save(messages().map(m=>m.id===id?{...m,read:true}:m));}
export async function syncInbox(){try{const c=connection();const response=await fetch(c.url+'/model-library/market-state',{headers:{'X-Library-Token':c.token},signal:AbortSignal.timeout(7000)});if(!response.ok)return;const value=await response.json();for(const m of value.observationMessages||[])ingestMessage(m);}catch{/* Offline messages remain stored. */}}
