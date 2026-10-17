"""User-authorized experimental promotion. Shadow journal remains intact."""
from .cost_risk import entry_is_valid
from .config import MIN_NET_TP1

def experimental_signal(decision,ticker):
    for row in decision.get('research',[]):
        c=row.get('candidate')
        if row.get('status')!='SHADOW_CANDIDATE' or not c:continue
        model='RANGE' if 'RANGE' in row['variant'] else 'REBOUND'
        entry=c['entry'];target=c['targetTP1'];stop=c['stopLoss']
        gain=(target/entry-1)*100;risk=(1-stop/entry)*100
        sig=dict(symbol='BTCUSDT',coin_name='Bitcoin',signal_type='BUY',decision_status='BUY_CANDIDATE',
          strategy='RANGE_OSCILLATION' if model=='RANGE' else 'FLASH_CRASH_REBOUND',model=model,
          rule_version='experimental-v2',experimental_variant=row['variant'],max_hold_minutes=c['maxHoldMinutes'],
          min_net_tp1=MIN_NET_TP1,max_net_target=None,invalidation_price=c['invalidationPrice'],tp1_fraction=1.,
          target_basis='最近已确认结构阻力',exit_rule='结构失效或止损退出；TP1全部退出；最长持有时间到期退出。',
          strategy_name_zh='实验模型 · '+row['label'],entry_price=entry,target_tp1=target,target_tp2=target,stop_loss=stop,
          profit_pct1=gain,profit_pct2=gain,stop_loss_pct=risk,net_tp1=c['netTP1'],net_tp2=c['netTP1'],net_rr=c['netRR'],
          risk_reward=gain/risk,time_horizon=f"最长{c['maxHoldMinutes']}分钟，失效提前退出",rule_score=0,
          rule_score_breakdown='未评分',reason_zh='用户授权实测；盈利能力未验证。'+row['label']+'；'+c['exitRule'],
          structure_support=stop,volatility_level=(decision.get('volatility') or {}).get('level','UNKNOWN'),
          quantile_pct=(decision.get('volatility') or {}).get('quantile',0),regime=(decision.get('macro') or {}).get('trend','UNKNOWN'),
          confirmation_time=c['confirmationTime'],timestamp=decision['atMs'],entry_min=c['entry_min'],entry_max=c['entry_max'],
          expires_at=c['expires_at'],breakout_level=None)
        if entry_is_valid(sig,ticker,decision['atMs']):return sig
    return None
