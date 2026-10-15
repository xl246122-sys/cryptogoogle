"""Versioned shadow hypotheses. Never returns or mutates a production signal."""
import math
from .features import TechnicalIndicators as TI
from .strategy import verify_micro_range_reversal, stable_range_box, observed_resistances
from .market_state import diagnose_cascade_downtrend
from .cost_risk import entry_contract
from .config import FRICTION_PCT, MIN_NET_TP1, MIN_NET_RR, TARGET_BUFFER_PCT

VERSION='recovery-shadow-v1'
from .session_research import session_context, shock_measure
NEW_VARIANTS=tuple((f'MINUTE_SHOCK_{w}',f'{w}分钟急跌恢复',90) for w in (3,5,10)) + (('SHORT_RANGE','32分钟稳定区间',60),('RANGE_REBUILD','破位后重建区间',120))
# Fixed pre-observation hypotheses, not validated optimal parameters.
VARIANTS=(('OVERSOLD_RECOVERY','普通超卖恢复',90),('BEAR_LOCAL_RANGE','空头局部企稳',120))

def evaluate_research(bars,ticker,book,macro,now):
    """Called only after common snapshot validation; only closed bars enter here."""
    one,five=bars['1m'],bars['5m']
    rsi=TI.rsi(five,14)
    previous=[TI.rsi(five[:-n],14) for n in range(1,7)]
    last=one[-1];ask=ticker['ask_price']
    cascade,why=diagnose_cascade_downtrend(one,ticker)
    reversal,reason,support,near=verify_micro_range_reversal(one,book,ticker)
    recent=one[-3:];prior=one[-6:-3]
    sell=lambda seq:sum(c['volume']-c['taker_buy_base'] for c in seq)
    ratio=lambda seq:sum(c['taker_buy_base'] for c in seq)/sum(c['volume'] for c in seq) if sum(c['volume'] for c in seq)>0 else 0
    checks=[('非瀑布',not cascade,why or '通过'),
            ('五类防飞刀',reversal,reason),
            ('停止创新低',min(c['low'] for c in recent)>=min(c['low'] for c in prior),'近3根1m低点不低于前3根'),
            ('抛压减弱',sell(recent)<=sell(prior),f"主动卖量 {sell(recent):.4f}（要求≤前段 {sell(prior):.4f}）"),
            ('主动买量改善',ratio(recent)>=.52 and ratio(recent)>ratio(prior),f"近3根买量占比 {ratio(recent)*100:.2f}%（要求≥52%且高于前段 {ratio(prior)*100:.2f}%）")]
    results=[]
    for variant,label,hold in VARIANTS+NEW_VARIANTS:
        row={'variant':variant,'label':label,'version':VERSION,'mode':'SHADOW','status':'REJECTED','atMs':now,'reasons':[],
             'parameters':{'minNetTp1':MIN_NET_TP1,'minNetRR':MIN_NET_RR,'assumedFrictionPct':FRICTION_PCT,'maxHoldMinutes':hold,'maxStopPct':1.2},'checks':[],'candidate':None}
        gates=list(checks);box=None
        if (variant,label,hold) in NEW_VARIANTS:
            row['version']='minute-session-shadow-v1'
            row['session']=session_context(now)
            volatility=TI.calculate_volatility_regime(bars['15m'],ask)
            row['realizedVolatility']={k:volatility[k] for k in ('level','quantile','sample_bars') if k in volatility}
            row['parameters'].update(holdComparisonMinutes=[10,30,60,90,120,240,360],shockThresholdPct=1.5)
            row['parameters']['holdComparisonOnly']=True
        if variant=='OVERSOLD_RECOVERY':
            gates += [('超卖后恢复',min(previous)<=30 and 30<=rsi<=55 and rsi-previous[0]>=3,
                       f"5m前6次RSI最低 {min(previous):.2f}（要求≤30）；当前 {rsi:.2f}（要求30–55）；回升 {rsi-previous[0]:.2f}（要求≥3）")]
        elif variant.startswith('MINUTE_SHOCK_'):
            shock=shock_measure(one,int(variant.rsplit('_',1)[1]));row['shock']=shock
            gates += [('分钟冲击',shock['dropPct']>=1.5,f"先高后低跌幅 {shock['dropPct']:.3f}%（研究阈值≥1.5%）"),('收复冲击结构',shock['reclaim'],'收盘价须收复冲击低点所在K线高点')]
        elif variant in ('SHORT_RANGE','RANGE_REBUILD'):
            box=stable_range_box(one[:-1],ask)
            old=one[-40:-32]; recent_box=one[-33:-1]
            broken=bool(old) and min(c['low'] for c in recent_box)<min(c['low'] for c in old)
            gates += [('32分钟稳定箱体',box is not None,'重复触边、低方向效率、下沿四分之一区域'),('结构类型',broken==(variant=='RANGE_REBUILD'),'旧支撑跌破后必须独立重建箱体' if variant=='RANGE_REBUILD' else '旧支撑未跌破'),('箱体仍有效',box is not None and last['low']>=box['low'],'最新已收盘1m不得跌穿箱体下沿')]
        else:
            box=stable_range_box(five,ask)
            gates += [('空头背景',macro.get('is_bearish') is True,'仅研究服务端空头背景'),
                      ('160分钟稳定箱体',box is not None,'32根5m，重复触边、低方向效率、下沿四分之一区域')]
        levels=observed_resistances(bars['15m'],bars['1h'])+[near]
        if box:levels += [box['mid'],box['high']]
        stop=math.floor((min(support,box['low'] if box else support)-.25*TI.atr(one,14))*100)/100
        invalidation=min(support,box['low'] if box else support)
        barriers=sorted(set(x for x in levels if math.isfinite(x) and x>ask))
        target=math.floor(barriers[0]*(1-TARGET_BUFFER_PCT/100)*100)/100 if barriers else None
        risk=(1-stop/ask)*100
        net=(target/ask-1)*100-FRICTION_PCT if target else None
        rr=net/(risk+FRICTION_PCT) if net is not None and risk+FRICTION_PCT>0 else None
        gates += [('结构止损',0<stop<=invalidation<ask and 0<risk<=1.2,f"结构风险 {risk:.3f}%（要求>0且≤1.20%）"),
                  ('最近阻力净空间',net is not None and net>=MIN_NET_TP1,f"净TP1 {net:.3f}%（要求≥{MIN_NET_TP1:.2f}%）" if net is not None else '无可用上方结构阻力'),
                  ('净盈亏比',rr is not None and rr>=MIN_NET_RR,f"净RR {rr:.3f}（要求≥{MIN_NET_RR:.2f}）" if rr is not None else '不可计算')]
        contract=entry_contract(ask,target,stop,last['close_time'],now_ms=now,reference_price=last['close'],invalidation_price=invalidation) if target else None
        gates += [('有效入场区间',contract is not None,'最新ask、收盘参考价、时效与固定目标复核')]
        row['checks']=[{'name':name,'passed':bool(ok),'detail':detail} for name,ok,detail in gates]
        row['reasons']=[name+'：'+detail for name,ok,detail in gates if not ok]
        if not row['reasons']:
            row['status']='SHADOW_CANDIDATE'
            row['candidate']={'id':f'{row["version"]}:{variant}:{last["close_time"]}','entry':ask,'stopLoss':stop,'invalidationPrice':invalidation,
                              'targetTP1':target,'netTP1':net,'netRR':rr,'maxHoldMinutes':hold,'confirmationTime':last['close_time'],**contract,
                              'exitRule':'结构失效/止损优先；TP1全部退出；到时退出。仅研究，不代表实际持仓或成交。'}
        results.append(row)
    return results

