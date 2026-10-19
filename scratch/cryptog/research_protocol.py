"""Stage D evidence preparation. Never changes trading parameters or release tiers."""
import hashlib
import json
import math
import random
from pathlib import Path

DAY_MS = 86400000


def save_once(path, body):
    """Exclusive creation: a seen result or sealed plan cannot silently be replaced."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(body, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    with path.open('x', encoding='utf-8') as stream:
        stream.write(text)
    return hashlib.sha256(text.encode()).hexdigest()


def register_trial(directory, trial_id, manifest_sha256, config, started_ms):
    """Register BEFORE running; failed and abandoned trials remain in the family."""
    if not trial_id or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in trial_id):
        raise ValueError('Invalid trial ID')
    return save_once(Path(directory)/f'{trial_id}.trial.json',
                     dict(trialId=trial_id, manifestSha256=manifest_sha256,
                          config=config, startedMs=started_ms, status='REGISTERED'))


def trial_inventory(directory, historical_count=None):
    rows = [json.loads(p.read_text(encoding='utf-8')) for p in sorted(Path(directory).glob('*.trial.json'))]
    return dict(registered=len(rows), trialIds=[r['trialId'] for r in rows],
                historicalCount=historical_count,
                nTrials=None if historical_count is None else historical_count+len(rows),
                complete=historical_count is not None)


def block_bootstrap_lower(trades, iterations=2000, seed=20261018):
    """Resample CST entry-day clusters, weighting every trade inside a sampled day.

    A sensitivity check, not a replacement for the required IID bootstrap gate.
    At least two occupied days are needed; empty days are not invented trades.
    """
    groups = {}
    for row in trades:
        value = row['netPct']
        if not math.isfinite(value):
            raise ValueError('Nonfinite return')
        day = (int(row['openedMs']) + 8*3600000)//DAY_MS
        groups.setdefault(day, []).append(value)
    blocks = list(groups.values())
    if len(blocks) < 2:
        return None
    if iterations < 1:
        raise ValueError('iterations must be positive')
    rng = random.Random(seed)
    means = []
    for _ in range(iterations):
        chosen = [blocks[rng.randrange(len(blocks))] for _ in blocks]
        means.append(sum(sum(b) for b in chosen)/sum(len(b) for b in chosen))
    means.sort()
    return means[int(.05*(iterations-1))]


def whole_trade_metrics(trades):
    """Keep uncertain outcomes visible and separate from eligible 0.8% evidence."""
    rows = list(trades)
    valid = [r for r in rows if r.get('eligibleForValidation') is True
             and r.get('closedMs') is not None and isinstance(r.get('netPct'), (int, float))
             and math.isfinite(r['netPct'])]
    count = len(valid)
    return dict(total=len(rows), eligible=count, excluded=len(rows)-count,
                wholeTradeTargetPct=.8,
                achievementRate=None if not count else sum(r['netPct'] >= .8 for r in valid)/count,
                blockBootstrapLower95=block_bootstrap_lower(valid),
                sensitivity='CST entry-day cluster bootstrap; uncertain trades remain separately counted')
