import {type ExecutionFill,validateFill,summarizeFills} from './executionLedger';
/** Portable normalized fills; no credentials and no order placement. */
export function previewFillImport(raw:unknown,existing:ExecutionFill[]) {
 if(!Array.isArray(raw)||raw.length>1000)throw new Error('请选择最多 1000 笔的标准成交 JSON 数组');
 const added:ExecutionFill[]=[];let duplicates=0;
 const accepted=raw.filter(item=>item?.status!=='rejected');
 const replaced=new Set(accepted.map(item=>item?.action?.replacesEventId ?? item?.replacesEventId).filter(Boolean));
 for(const item of accepted){
  if(replaced.has(item?.action?.eventId ?? item?.eventId))continue;
  if ((item?.action?.recordType || item?.recordType) && !(item?.action?.fill || item?.fill)) continue;
  const fill=(item?.action?.fill ?? item?.fill ?? item) as ExecutionFill;
  const issue=validateFill(fill);if(issue)throw new Error(issue);
  const prior=[...existing,...added].find(f=>f.fillId===fill.fillId || (fill.exchangeTradeId && f.exchangeTradeId===fill.exchangeTradeId));
  if(prior){
   const fields=['positionId','side','price','quantity','executedAtMs','commission','commissionAsset','commissionAssetUsdtRate'] as const;
   if(fields.some(k=>prior[k]!==fill[k]))throw new Error('重复成交存在差异，请使用更正功能逐笔核对');
   duplicates++;continue;
  }
  added.push({...fill,source:'MANUAL'});
 }
 const positions=new Set(added.map(f=>f.positionId));
 for(const p of positions)summarizeFills([...existing,...added].filter(f=>f.positionId===p));
 return {fills:added.sort((a,b)=>a.executedAtMs-b.executedAtMs || a.fillId.localeCompare(b.fillId)),duplicates};
}
