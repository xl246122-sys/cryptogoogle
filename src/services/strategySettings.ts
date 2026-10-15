import {connection} from './serverConnection';
export const families=['BURST_BREAKOUT','FLASH_CRASH_REBOUND','RANGE_OSCILLATION'];
export async function strategySettings(body?:object){const c=connection();const r=await fetch(c.url+'/model-library/strategy-settings',{method:body?'POST':'GET',headers:{'X-Library-Token':c.token,'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined,signal:AbortSignal.timeout(7000)});const v=await r.json();if(!r.ok||!v.ok)throw new Error(v.error||'云端配置不可用');return v as {revision:number;activeStrategies:Record<string,boolean>};}
