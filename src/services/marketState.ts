import type { MacroTrendAnalysis } from '../types/crypto';
import { connection } from './serverConnection';

export function unknownMarket(reason = '服务器不可用、未配置或行情过期，暂停解释买入机会'): MacroTrendAnalysis {
  return {hourlyTrend:'RANGING',hourlyMa20:0,hourlyMa50:0,hourlyRsi:0,trendDriftPercent:0,
    allowLongBreakout:false,regime:'UNKNOWN',dataReady:false,regimeNameZh:'服务端状态未知',regimeDescription:reason,biasZh:'请勿根据本地价格推断服务端正在正常扫描'};
}
export function parseMarketState(value: any, now = Date.now()): MacroTrendAnalysis {
  const s=value?.snapshot, m=s?.macro;
  if (value?.schema!==1 || value?.ok!==true || value.runtimeHealthy!==true || value.feedHealthy!==true || !s || !Number.isFinite(s.atMs) || now-s.atMs>10000 || s.atMs-now>5000 || s.ruleVersion!=='three-models-v1' || typeof s.engineVersion!=='string') return unknownMarket();
  if (s.status==='BLOCK_ENTRY' || !m) return unknownMarket(`行情校验未通过：${Array.isArray(s.reasons)?s.reasons.join('；'):'数据不足'}`);
  if (!['BULLISH','BEARISH','RANGING'].includes(m.trend) || !Number.isFinite(m.ma20) || m.ma20<=0 || !Number.isFinite(m.rsi) || m.rsi<0 || m.rsi>100) return unknownMarket('服务端状态字段不完整');
  const title={BULLISH:'多头背景',BEARISH:'空头背景',RANGING:'震荡背景'}[m.trend as 'BULLISH'|'BEARISH'|'RANGING'];
  const reasons=Array.isArray(s.reasons)?s.reasons.filter((r:unknown)=>typeof r==='string').join('；'):'';
  const shadow=value.mode==='SHADOW';
  return {hourlyTrend:m.trend,isStronglyBearish:m.is_strongly_bearish===true,hourlyMa20:m.ma20,
    rejectionReasons:s.signal?[]:Array.isArray(s.reasons)?s.reasons.filter((x:unknown)=>typeof x==='string'):[],
    research:Array.isArray(s.research)?s.research.filter((x:any)=>x?.mode==='SHADOW' && typeof x.label==='string' && ['REJECTED','SHADOW_CANDIDATE','ERROR'].includes(x.status) && Array.isArray(x.reasons)).map((x:any)=>({label:x.label,status:x.status,reasons:x.reasons.filter((r:unknown)=>typeof r==='string')})):undefined,
    hourlyMa50:0,hourlyRsi:m.rsi,trendDriftPercent:0,allowLongBreakout:false,
    regime:m.trend==='BULLISH'?'TRENDING_BULL':m.trend==='BEARISH'?'TRENDING_BEAR':'MEAN_REVERTING_RANGE',dataReady:true,
    regimeNameZh:`${title} · ${shadow?'研究观察，不推送新买入':'基线监控'}`,
    regimeDescription:`${typeof m.reason==='string'?m.reason:''} ${reasons || (shadow?'观察到候选，仍需验证':'候选需打开复核')}`,
    biasZh:`${s.engineVersion} / ${s.ruleVersion} · ${new Date(s.atMs).toLocaleTimeString()} · 收盘结构；目标以具体信号为准`};
}
export async function fetchMarketState(): Promise<MacroTrendAnalysis> {
  const controller=new AbortController();
  const timeout=setTimeout(()=>controller.abort(),5000);
  try {
    const {url,token}=connection();
    const response=await fetch(`${url}/model-library/market-state`,{headers:{'X-Library-Token':token},signal:controller.signal,cache:'no-store'});
    return response.ok?parseMarketState(await response.json()):unknownMarket();
  } catch {return unknownMarket();}
  finally {clearTimeout(timeout);}
}
