import {connection} from './serverConnection';
export interface ConnectionStatus {
  backendHealthy:boolean; binding:'bound'|'unbound'|'other'|'unknown'; pushEnabled:boolean;
  exitWorkerHealthy:boolean; checkedAt:number;
}
export function parseConnectionStatus(market:any, device:any, now=Date.now()):ConnectionStatus {
  if(market?.ok!==true || market.schema!==1 || device?.ok!==true || typeof device.registered!=='boolean'
    || ![true,false,null].includes(device.matchesCurrentDevice) || typeof device.pushEnabled!=='boolean')throw new Error('后台状态不完整，请更新后重试');
  const at=market.snapshot?.atMs;
  return {backendHealthy:market.runtimeHealthy===true && market.feedHealthy===true && Number.isFinite(at) && now-at>=-5000 && now-at<=10000,
    binding:!device.registered?'unbound':device.matchesCurrentDevice===true?'bound':device.matchesCurrentDevice===false?'other':'unknown',
    pushEnabled:device.pushEnabled,exitWorkerHealthy:market.exitNotificationHealthy===true,checkedAt:now};
}
export async function inspectConnection(token:string|null):Promise<ConnectionStatus> {
  const config=connection();const control=new AbortController();const timer=setTimeout(()=>control.abort(),7000);
  async function read(path:string,body?:object){
    const response=await fetch(`${config.url}/model-library/${path}`,{method:body?'POST':'GET',
      headers:{'X-Library-Token':config.token,'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined,
      signal:control.signal,cache:'no-store'});
    if(response.status===401)throw new Error('凭据无效或无权限，请重新配置');
    if(response.status===404)throw new Error('后台需更新设备状态接口');
    if(!response.ok)throw new Error('后端暂不可用，请重试');
    return response.json();
  }
  try {
    const [market,device]=await Promise.all([read('market-state'),read('exit-device-status',{token})]);
    return parseConnectionStatus(market,device);
  } finally {clearTimeout(timer);}
}
