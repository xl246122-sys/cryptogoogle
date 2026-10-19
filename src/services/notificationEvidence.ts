/** Device observations only. No credentials, message contents or inferred delivery. */
export type NotificationOrigin='received'|'opened';
export interface NotificationEvidence {id:string;eventType:string;revision:number|null;origin:NotificationOrigin;clientAtMs:number}
const KEY='cryptog_notification_evidence_v1';
export function notificationEvidence():NotificationEvidence[] {
 try {const rows=JSON.parse(localStorage.getItem(KEY)||'[]');return Array.isArray(rows)?rows.filter(r=>
  typeof r?.id==='string'&&typeof r.eventType==='string'&&['received','opened'].includes(r.origin)
  &&Number.isFinite(r.clientAtMs)&&(r.revision===null||Number.isInteger(r.revision))).slice(-300):[];}catch{return [];}
}
export function recordNotificationEvidence(data:any,origin:NotificationOrigin,now=Date.now()) {
 try {
  const id=String(data?.eventId||data?.id||data?.testId||data?.deliveryId||'unknown').slice(0,180);
  const revision=Number.isInteger(Number(data?.revision))&&Number(data?.revision)>0?Number(data.revision):null;
  const rows=notificationEvidence();
  if(rows.some(r=>r.id===id&&r.revision===revision&&r.origin===origin))return;
  rows.push({id,eventType:String(data?.eventType||'UNSPECIFIED').slice(0,60),revision,origin,clientAtMs:now});
  localStorage.setItem(KEY,JSON.stringify(rows.slice(-300)));
  if(typeof window!=='undefined')window.dispatchEvent(new Event('cryptog-notification-evidence'));
 }catch{ /* Diagnostic storage failure must not block inbox ingestion. */ }
}
export function notificationEvidenceReport() {
 return {schema:1,createdAtMs:Date.now(),observations:notificationEvidence(),
  interpretation:'received仅表示APP前台回调；opened仅表示点击。锁屏展示、铃声、单向送达延迟需单独验收。',
  serverDeliveryVerified:false};
}

/** Native cold-start callbacks can arrive before React subscribes. Inbox is persisted separately. */
export class NotificationRelay {
 private callback:((data:any,origin:NotificationOrigin)=>unknown)|null=null;
 private pending:{data:any;origin:NotificationOrigin}[]=[];
 private deliver(data:any,origin:NotificationOrigin) {
  try {void Promise.resolve(this.callback?.(data,origin)).catch(()=>{});}catch{/* Inbox remains available. */}
 }
 emit(data:any,origin:NotificationOrigin) {
  if(this.callback)this.deliver(data,origin);
  else {this.pending.push({data,origin});this.pending=this.pending.slice(-100);}
 }
 subscribe(callback:(data:any,origin:NotificationOrigin)=>unknown) {
  this.callback=callback;
  const queued=this.pending;this.pending=[];
  for(const item of queued)this.deliver(item.data,item.origin);
  return ()=>{if(this.callback===callback)this.callback=null;};
 }
}
