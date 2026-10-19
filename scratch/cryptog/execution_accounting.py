"""Actual fill cash flows. Prices already contain execution slippage."""
from decimal import Decimal

def execution_summary(fills):
    zero = Decimal('0')
    inventory = cost = realized = fees = bought = sold = invested = zero
    known, seen, slips = True, set(), []
    position = None
    for f in sorted(fills, key=lambda x: (x['executedAtMs'], x['fillId'])):
        if f['fillId'] in seen: raise ValueError('duplicate fillId')
        seen.add(f['fillId'])
        if position and position != f['positionId']: raise ValueError('mixed positions')
        position = f['positionId']
        price, qty = Decimal(str(f['price'])), Decimal(str(f['quantity']))
        commission = None if f['commission'] is None else Decimal(str(f['commission']))
        asset = f['commissionAsset']
        base_fee = (commission or zero) if asset == 'BTC' else zero
        rate = Decimal(1) if asset == 'USDT' else price if asset == 'BTC' else (None if f.get('commissionAssetUsdtRate') is None else Decimal(str(f['commissionAssetUsdtRate'])))
        converted = zero if commission == zero else None if commission is None or rate is None else commission*rate
        if converted is None: known = False
        else: fees += converted
        cash_fee = zero if asset == 'BTC' else (converted or zero)
        if f['side'] == 'BUY':
            inventory += qty-base_fee; cost += qty*price+cash_fee; bought += qty
            invested += qty*price+cash_fee
        else:
            used = qty+base_fee
            if inventory <= 0 or used > inventory + Decimal('0.0000000001'): raise ValueError('sell exceeds recorded BTC inventory')
            allocated = cost*min(used, inventory)/inventory
            realized += qty*price-cash_fee-allocated
            inventory = max(zero, inventory-used); cost -= allocated; sold += qty
        ref = f.get('referencePrice')
        slips.append({'fillId': f['fillId'], 'quoteDifferenceUsdt': None if ref is None else float((price-Decimal(str(ref)) if f['side']=='BUY' else Decimal(str(ref))-price)*qty),
                      'benchmarkAgeMs': None if f.get('referenceAtMs') is None else f['executedAtMs']-f['referenceAtMs']})
    return {'investedUsdt': float(invested) if known else None,
            'wholeTradeNetPct': float(realized / invested * 100) if known and invested > 0 and inventory < Decimal('0.0000000001') else None,
            'accountingVersion': 'actual-cashflow-v2.1', 'inventory': float(inventory) if known else None, 'inventoryBeforeUnknownFees': float(inventory),
            'remainingCostUsdt': float(cost) if known else None, 'realizedNetUsdt': float(realized) if known else None,
            'feeUsdt': float(fees) if known else None, 'feesKnown': known, 'bought': float(bought), 'sold': float(sold),
            'closed': known and bought>0 and inventory<Decimal('0.0000000001'), 'slippage': slips, 'source': 'MANUAL_UNVERIFIED'}



def paper_close_cost(action, previous):
    """Frozen entry cost allocated by remaining original notional, not today's cost."""
    cost = reserve = 0.0
    for row in previous:
        if row.get('alertId') != action['alertId'] or row.get('strategy') != 'QUICK_PAPER_V2':continue
        amount = float(row.get('positionSize') or 0)
        if row.get('recordType') == 'SIM_BUY':
            cost += amount
            reserve += amount * max(.24, (row.get('costSnapshot') or {}).get('frictionPct', .24)) / 100
        elif row.get('recordType') == 'USER_CLOSE' and cost > 0:
            reserve *= max(0, 1-amount/cost)
            cost -= amount
    amount = action['positionSize']
    if cost <= 0 or amount > cost + 1e-7:raise ValueError('simulation close exceeds recorded inventory')
    return reserve * amount / cost
