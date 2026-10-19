/** Explicitly non-tradable research protocol. Never converts to a TradeSignal. */
export const WAVE_VERSION='wave-state-v3-research';
export const wavePhases=['DOWN_START','SELL_EXHAUSTION','REBOUND_CONFIRMED','INVALIDATED','HOLDING_EXHAUSTION'] as const;
export interface WaveMessage {
 eventType:'WAVE_STATE_RESEARCH';ruleVersion:typeof WAVE_VERSION;eventId:string;parentEventId:string;
 revision:number;phase:typeof wavePhases[number];issuedAtMs:number;decisionTime:number;featureAsOfTime:number;
 tradeEligible:false;signalType:'OBSERVE';tier:'RESEARCH';lifecycle:'ACTIVE'|'INVALIDATED';
 module:string;branch:string;reason?:string|null;expiresAt:number|null;evidence:Record<string,unknown>;
 plan:null|{entryLow:number;entryHigh:number;stop:number;target:number;expiresAt:number};
 risk:null|{status:string;reason?:string|null;netTargetPct?:number;stopDistancePct?:number;netRR?:number;costPct?:number};
 position:null|{positionId:string;revision:string;remainingQuantity:number;remainingCostUsdt:number;costReserveUsdt:number;
   estimatedNetUsdt:number;estimatedNetPct:number|null;bid:number;latestActionMs:number;costVersion:string};
}
const finite=(n:unknown):n is number=>typeof n==='number'&&Number.isFinite(n);
export function parseWaveMessage(raw:any):WaveMessage|null {
 if(raw?.eventType!=='WAVE_STATE_RESEARCH'||raw.ruleVersion!==WAVE_VERSION)return null;
 try {
  const d={...raw};for(const k of ['plan','risk','position','evidence'])if(typeof d[k]==='string')d[k]=JSON.parse(d[k]);
  for(const k of ['revision','issuedAtMs','decisionTime','featureAsOfTime'])d[k]=Number(d[k]);
  d.expiresAt=d.expiresAt==null||d.expiresAt==='null'?null:Number(d.expiresAt);
  if(!['eventId','parentEventId','module','branch'].every(k=>typeof d[k]==='string'&&d[k].length>0)
    ||!wavePhases.includes(d.phase)||!Number.isInteger(d.revision)||d.revision<1
    ||!['issuedAtMs','decisionTime','featureAsOfTime'].every(k=>finite(d[k])&&d[k]>0)
    ||d.featureAsOfTime>d.decisionTime||d.issuedAtMs!==d.decisionTime
    ||![false,'false'].includes(d.tradeEligible)||d.signalType!=='OBSERVE'||d.tier!=='RESEARCH'
    ||!['ACTIVE','INVALIDATED'].includes(d.lifecycle)||!d.evidence||typeof d.evidence!=='object'||Array.isArray(d.evidence))return null;
  if(d.plan && (!['entryLow','entryHigh','stop','target','expiresAt'].every(k=>finite(d.plan[k])&&d.plan[k]>0)
    ||!(d.plan.stop<d.plan.entryLow&&d.plan.entryLow<=d.plan.entryHigh&&d.plan.entryHigh<d.plan.target)))return null;
  if(d.expiresAt!==null && (!finite(d.expiresAt)||d.expiresAt<=0))return null;
  if(d.risk && !['BLOCKED','PASS_RESEARCH_ONLY'].includes(d.risk.status))return null;
  if(d.phase==='REBOUND_CONFIRMED' && !d.risk)return null;
  if(d.phase==='REBOUND_CONFIRMED' && d.risk?.status==='PASS_RESEARCH_ONLY' && (!d.plan||d.expiresAt!==d.plan.expiresAt))return null;
  if(d.position && (!['positionId','revision','costVersion'].every(k=>typeof d.position[k]==='string'&&d.position[k])
    ||!['remainingQuantity','remainingCostUsdt','costReserveUsdt','bid','estimatedNetUsdt','latestActionMs'].every(k=>finite(d.position[k]))
    ||d.position.remainingQuantity<0||d.position.remainingCostUsdt<0||d.position.latestActionMs>d.decisionTime))return null;
  if(d.phase==='HOLDING_EXHAUSTION'&&!d.position)return null;
  return {...d,tradeEligible:false};
 } catch{return null;}
}
export function waveStatus(d:WaveMessage,now=Date.now()) {
 if(d.lifecycle==='INVALIDATED'||d.phase==='INVALIDATED')return '已撤销';
 if(d.expiresAt!==null&&d.expiresAt<=now)return '已过期';
 if(d.risk?.status==='BLOCKED')return '风险筛选未通过';
 return '研究观察·未验证';
}
export function waveTitle(d:WaveMessage) {
 if(d.lifecycle==='INVALIDATED'&&d.position)return '【持仓已结束·提醒失效】';
 if(d.phase==='HOLDING_EXHAUSTION') {
  if(['STOP','INVALIDATION','TIME'].includes(String(d.evidence.priority)))return '【持仓风险退出提醒】';
  return (d.position?.estimatedNetUsdt??0)>0?'【超买乏力·止盈提醒】':'【上涨乏力·风险退出提醒】';
 }
 return {DOWN_START:'【下跌行情预警】',SELL_EXHAUSTION:'【超卖乏力·关注企稳】',REBOUND_CONFIRMED:'【反弹确认·研究候选】',INVALIDATED:'【研究候选已撤销】'}[d.phase];
}
export function waveBody(d:WaveMessage) {
 const parts=['研究联调记录，未经收益验证；不代表已成交。'];
 if(d.phase==='DOWN_START'||d.phase==='SELL_EXHAUSTION')parts.push('仅行情观察；入场、止损和目标尚未形成。');
 if(d.risk)parts.push(`风险检查：${d.risk.status==='PASS_RESEARCH_ONLY'?'研究条件通过，未开放交易':d.risk.reason||'未通过'}`);
 if(d.reason)parts.push(`状态原因：${d.reason}`);
 return parts.join('\n');
}
