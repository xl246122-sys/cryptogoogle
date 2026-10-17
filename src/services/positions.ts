import { connection } from './serverConnection';

export const exitLabels: Record<string,string> = {
  STOP_EXIT:'止损退出', INVALIDATION_EXIT:'结构失效退出', TP1_PARTIAL_EXIT:'第一目标分批退出',
  TP2_EXIT:'第二目标退出', TIME_EXIT:'持有时间到期', TIME_EXIT_APPROXIMATE:'按近似成交时间估算到期',
  BREAKEVEN_EXIT:'保本止损退出', ENV_EXIT:'环境急跌退出', TRAIL_EXIT:'均线跟踪退出',
  TIME_STOP_EXIT:'90分钟动能不足', STOP_NEAR_WARNING:'接近止损', STRUCTURE_WARNING:'结构失效预警',
};
export interface ExitNotice { id:string; kind:string; quantity:number; atMs:number; }
export interface PositionReport {
  positionId:string; status:string; remainingQuantity:number|null; atMs:number;
  reason:string|null; deadlineMs?:number; unresolvedNotices:ExitNotice[];
}
export interface PositionState { fresh:boolean; positions:PositionReport[]; pushEnabled:boolean; }
export function parsePositions(value:any, now=Date.now()):PositionState {
  if (value?.ok!==true || value.schema!==1 || !['SHADOW_EVENTS_ONLY','DEVICE_PUSH_UNVERIFIED'].includes(value.positionNotifications) || !Array.isArray(value.positions)) throw new Error('服务器尚未提供持仓退出监控');
  const positions = value.positions.map((p:any):PositionReport => {
    if (typeof p?.positionId!=='string' || !['MONITORING','CLOSED','UNMANAGED'].includes(p.status) || !Number.isFinite(p.atMs)
      || !(p.remainingQuantity===null || (Number.isFinite(p.remainingQuantity) && p.remainingQuantity>=0))
      || !Array.isArray(p.unresolvedNotices)) throw new Error('持仓状态不完整');
    const notices=p.unresolvedNotices.map((n:any):ExitNotice => {
      if (typeof n?.id!=='string' || !exitLabels[n.kind] || !Number.isFinite(n.quantity) || n.quantity<=0 || !Number.isFinite(n.atMs)) throw new Error('退出事件不完整');
      return {id:n.id,kind:n.kind,quantity:n.quantity,atMs:n.atMs};
    });
    return {positionId:p.positionId,status:p.status,remainingQuantity:p.remainingQuantity,atMs:p.atMs,
      reason:typeof p.reason==='string'?p.reason:null,deadlineMs:Number.isFinite(p.deadlineMs)?p.deadlineMs:undefined,unresolvedNotices:notices};
  });
  return {fresh:value.runtimeHealthy===true && Number.isFinite(value.snapshot?.atMs) && now-value.snapshot.atMs<=10000 && now-value.snapshot.atMs>=-5000
    && positions.every((p:PositionReport)=>now-p.atMs<=10000 && now-p.atMs>=-5000),positions,pushEnabled:value.positionNotifications==='DEVICE_PUSH_UNVERIFIED'};
}
async function request(path:string, body?:object) {
  const {url,token}=connection(); const controller=new AbortController();
  const timer=setTimeout(()=>controller.abort(),5000);
  try {
    const response=await fetch(`${url}/model-library/${path}`,{method:body?'POST':'GET',
      headers:{'X-Library-Token':token,'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined,
      signal:controller.signal,cache:'no-store'});
    const data=await response.json();
    if (!response.ok || data.ok!==true) throw new Error('服务器未确认，请刷新状态后重试');
    return data;
  } finally { clearTimeout(timer); }
}
export async function fetchPositions() { return parsePositions(await request('market-state')); }
export async function reviewNotice(noticeId:string) {
  const receipt=await request('position-review',{noticeId});
  if (receipt.noticeId!==noticeId || receipt.kind!=='USER_REVIEWED' || !Number.isFinite(receipt.serverReceivedAtMs)) throw new Error('确认响应不完整，请重试');
  return receipt.serverReceivedAtMs as number;
}
