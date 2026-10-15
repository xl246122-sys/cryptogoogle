import type {LibraryAction, JournalEntry} from './modelLibrary';
export const PAPER_STRATEGY='QUICK_PAPER_V1';
export function paperSummary(rows:JournalEntry[]) {
 let quantity=0,cost=0,realized=0;
 for(const {action:a,status} of rows){
  if(a.strategy!==PAPER_STRATEGY || status==='rejected')continue;
  if(a.recordType==='SIM_BUY' && a.entryPrice && a.positionSize){quantity+=a.positionSize/a.entryPrice;cost+=a.positionSize;}
  if(a.recordType==='USER_CLOSE' && a.entryPrice && a.exitPrice && a.positionSize){
   const sold=a.positionSize/a.entryPrice;quantity-=sold;cost-=a.positionSize;
   realized+=sold*a.exitPrice-a.positionSize-(sold*a.exitPrice+a.positionSize)*.00055;
  }
 }
 return {quantity:Math.max(0,quantity),cost:Math.max(0,cost),realized};
}
export function paperAction(side:'BUY'|'SELL',price:number,quoteAt:number,now:number,rows:JournalEntry[],id:string):LibraryAction {
 if(!Number.isFinite(price)||price<=0||!Number.isFinite(quoteAt)||now-quoteAt>10000||now<quoteAt)throw new Error('行情过期或不可用，请等待更新');
 const s=paperSummary(rows);
 const common={alertId:id,actedAtMs:now,quoteAtMs:quoteAt,strategy:PAPER_STRATEGY,note:'一键模拟；按最新成交价估算，非实际成交；双边费用假设0.11%，未模拟盘口冲击'};
 if(side==='BUY')return {...common,recordType:'SIM_BUY',entryPrice:price,positionSize:500};
 if(s.quantity<=1e-12)throw new Error('暂无可卖出的模拟持仓');
 const quantity=Math.min(s.quantity,500/price);
 return {...common,recordType:'USER_CLOSE',entryPrice:s.cost/s.quantity,exitPrice:price,positionSize:quantity*(s.cost/s.quantity),exitSource:'APP_BUTTON'};
}
