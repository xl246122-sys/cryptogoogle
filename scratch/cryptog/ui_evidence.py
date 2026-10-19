"""Read-only UI evidence. Does not participate in evaluation or promotion."""
import copy
import json
import math


def decision_context(snapshot, decision):
    ctx = snapshot.get('context') or {}
    env = (decision.get('shortHorizonV2') or {}).get('env')
    if not env or not ctx:
        return None
    return {'atMs': snapshot['atMs'], 'contextAtMs': ctx.get('atMs'),
            'frames': {tf: {'closeTime': (ctx.get(tf) or {}).get('close_time'),
                            'state': (env.get('states') or {}).get(tf)} for tf in ('d1', 'h4', 'h1')},
            'gates': copy.deepcopy(env.get('gates', {})),
            'reasons': list(decision.get('reasons') or [])}


def research_summary(ledger, now):
    if ledger is None:
        return None
    with ledger.lock:
        rows = ledger.store.db.execute('''SELECT p.kind,c.module,c.rule_version,p.opened_ms,
            p.closed_ms,l.net_pct,l.payload FROM labels l
            JOIN shadow_positions p ON p.id=l.position_id
            LEFT JOIN candidates c ON c.id=l.candidate_id
            WHERE p.closed_ms IS NOT NULL ORDER BY p.closed_ms,p.id''').fetchall()
    groups = {}
    excluded = 0
    for kind, module, rule, opened, closed, net, raw in rows:
        label = json.loads(raw)
        cost = label.get('costSnapshot') or {}
        version = label.get('executionModelVersion')
        friction = cost.get('frictionPct')
        floor = .19 if cost.get('bnbDiscount') is True and cost.get('bnbVerified') is True else .24
        if (rule != 'short-horizon-v2' or version != 'settlement-v2.1'
                or label.get('eligibleForValidation') is not True
                or not isinstance(net, (int, float)) or not math.isfinite(net)
                or not cost.get('costModelVersion')
                or not isinstance(friction, (int, float)) or not math.isfinite(friction) or friction < floor):
            excluded += 1
            continue
        key = (kind, module, rule, version, cost['costModelVersion'], cost.get('frictionPct'))
        group = groups.setdefault(key, {'kind': kind, 'module': module, 'ruleVersion': rule,
            'executionVersion': version, 'costVersion': cost['costModelVersion'],
            'frictionPct': cost.get('frictionPct'), 'fromMs': opened, 'toMs': closed,
            'values': []})
        group['fromMs'] = min(group['fromMs'], opened)
        group['toMs'] = max(group['toMs'], closed)
        group['values'].append(net)
    for group in groups.values():
        values = group.pop('values')
        balance = peak = drawdown = streak = longest = 0
        for value in values:
            balance += value
            peak = max(peak, balance)
            drawdown = max(drawdown, peak - balance)
            streak = streak + 1 if value < 0 else 0
            longest = max(longest, streak)
        group.update(trades=len(values), winRate=sum(v > 0 for v in values)/len(values),
                     targetRate=sum(v >= .8 for v in values)/len(values),
                     expectancyPct=sum(values)/len(values), sumNetDrawdownPct=drawdown,
                     maxConsecutiveLosses=longest)
    return {'atMs': now, 'groups': list(groups.values()), 'excluded': excluded,
            'scope': 'ELIGIBLE_SIMULATED_CLOSED_LABELS', 'qualification': 'UNVERIFIED'}
