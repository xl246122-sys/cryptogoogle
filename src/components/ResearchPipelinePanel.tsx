import React,{useEffect,useState} from 'react';
import {connection} from '../services/serverConnection';
import {ResearchEvidence} from './ResearchEvidence';
const states:Record<string,string>={READY:'已配置，等待候选',DISABLED:'已关闭',MISSING_KEY:'缺少凭据',NOT_CALLED:'尚无实际候选调用',CALLED:'已调用',TIMEOUT:'超时，按 PASS 回退',FORMAT:'格式错误，按 PASS 回退'};
const labels:Record<string,string>={DETECTED:'发现候选',SCREENED:'条件筛选',EXECUTABLE:'可执行候选',SUPPRESSED:'停止提示',TRANSPORT:'推送处理',DELIVERY:'平台回执',SETTLED:'影子结算',AI_REVIEW:'AI 复核',NO_PATTERN:'形态未成立',ENVIRONMENT_CLOSED:'环境未开放',DATA_UNAVAILABLE:'数据不可用',STOP_TOO_WIDE:'止损距离过大',STOP_DISTANCE:'止损距离不符',NET_RR:'净盈亏比不足',NET_TARGET:'净目标不足',ESCAPED:'价格超出范围',INVALIDATED:'结构失效',WAIT_RETEST:'等待回踩',EXPIRED:'已过期',STRUCTURE_REJECTED:'结构未通过',MANUAL_FILL:'手工成交',FILL_CORRECTION:'成交更正',PUSH_RECEIVED:'手机收到',PUSH_OPENED:'用户打开',PHONE_OPENED:'用户打开',PHONE_RECEIVED:'手机收到',ENTRY_REJECTED:'入场复核未通过',SIM_BUY:'模拟买入',USER_CLOSE:'记录平仓',AI_VETO:'AI 否决',SENT:'平台已接受',FAILED:'推送失败',RETRY:'推送待重试'};
export function ResearchPipelinePanel(){
 const [data,setData]=useState<any>(null);const [error,setError]=useState('');
 useEffect(()=>{let stopped=false,busy=false;const update=async()=>{if(busy)return;busy=true;const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),8000);
  try{const target=connection();const response=await fetch(`${target.url}/model-library/market-state`,{headers:{'X-Library-Token':target.token},signal:controller.signal});const value=await response.json();if(!response.ok||!value.ok||!value.runtimeHealthy||!Number.isFinite(value.snapshot?.atMs)||Date.now()-value.snapshot.atMs>10000||value.snapshot.atMs>Date.now()+2000)throw new Error('数据链路状态过期或不可用');if(!stopped && target.cacheScope===connection().cacheScope){setData(value);setError('');}}
  catch{if(!stopped){setError('数据链路状态不可用，请稍后刷新');setData(null);}}finally{clearTimeout(timer);busy=false;}};void update();const timer=setInterval(update,30000);return()=>{stopped=true;clearInterval(timer);};},[]);
 return <details className="my-3 rounded-xl border border-gray-700 p-3 text-xs space-y-2"><summary>研究数据与执行链路</summary>
  {error && <p>{error}</p>}
  <p>六周期闭合 K 线：{data?.spotResearch?.healthy?'持续写入正常':'待补齐或状态未知'}</p>
  {['1m','5m','15m','1h','4h','1d'].map(tf=>{const c=data?.spotResearch?.coverage?.[tf];return <p key={tf}>{tf}：{c?.count ?? '—'} 根；区间内缺失 {c?.missingBars ?? '—'} 根；尾部待补 {c?.tailMissingBars ?? '—'} 根</p>;})}
  <p>AI 第二意见：{states[data?.v2Review?.configuration?.state]||'未知'}；{states[data?.v2Review?.last?.state]||'尚无调用记录'}</p>
  <p>成交研究同步：已完成 {data?.executionMirror?.DONE ?? '未知'} 条；待重试 {data?.executionMirror?.ERROR ?? '未知'} 条。</p>
  <p>候选记录是独立阶段事件，不能当成成交笔数；推送平台接受不代表手机收到。</p>
  {data?.funnel?.counts?.map((r:any)=><p key={`${r.stage}:${r.reason}`}>{labels[r.stage]||'其他阶段'} · {labels[r.reason]||'已记录'}：{r.count}</p>)}
  <p>AI 效果仍未验证；需有效影子结算和分环境样本，不能由调用成功推断有效。</p>
  <ResearchEvidence data={data}/>
 </details>;
}
