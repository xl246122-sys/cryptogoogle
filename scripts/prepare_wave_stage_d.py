"""Seal independent four-stage prospective research; never promotes production."""
import csv
import hashlib
import json
from pathlib import Path
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scratch'))
from cryptog.config import V2_OOS_MS, V2_EMBARGO_MS
from cryptog.research_protocol import DAY_MS, save_once


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    prior = ROOT/'audit/btc-stage-b-20261018'
    manifest = json.loads((prior/'result-manifest.json').read_text(encoding='utf-8'))
    spec = json.loads((prior/'protocol.json').read_text(encoding='utf-8'))
    assert sha(prior/'protocol.json') == manifest['protocolSha256']
    assert sha(ROOT/'scripts/research_btc_stage_b.py') == manifest['scriptSha256']
    for name, digest in manifest['outputs'].items():
        assert sha(prior/(name+'.csv')) == digest, name
    for name, digest in spec['sources'].items():
        assert sha(ROOT/name) == digest, name
    with (prior/'summary.csv').open(encoding='utf-8-sig', newline='') as stream:
        rows = [row for row in csv.DictReader(stream) if row['segment']=='ALL90'
                and float(row['costPct'])==.24 and int(row['delayMinutes'])==1]
    assert len(rows)==7
    now = int(time.time()*1000)
    # UTC boundaries match frozen research daily calibration; display CST explicitly.
    start = (now//DAY_MS+1)*DAY_MS
    dest = ROOT/'model_library/wave-stage-d/WAVE-D-20261018-001'
    dest.mkdir(parents=True, exist_ok=False)
    sources = list((ROOT/'scratch/cryptog').glob('*.py'))
    sources += [ROOT/'scripts'/name for name in ['research_btc_stage_b.py',
        'research_btc_dynamic.py', 'report_btc_wave_space.py', 'prepare_wave_stage_d.py']]
    sources += [prior/'protocol.json', prior/'result-manifest.json', prior/'summary.csv',
                ROOT/'audit/wave-stage-c-20261018/manifest.json', ROOT/'AGENTS.md']
    hashes = {p.relative_to(ROOT).as_posix(): sha(p) for p in sources}
    with zipfile.ZipFile(dest/'source.zip', 'x', zipfile.ZIP_DEFLATED) as archive:
        for path in sources:
            archive.write(path, path.relative_to(ROOT).as_posix())
    protocol = dict(experimentId=dest.name, status='REGISTERED_NOT_RUNNING', frozenAtMs=now,
        sourceHashes=hashes, archiveSha256=sha(dest/'source.zip'),
        groups=spec['groups'], scenarios=spec['scenarios'], primaryScenario=dict(costPct=.24, delayMinutes=1),
        prospective=dict(startMs=start, endExclusiveMs=start+V2_OOS_MS,
            trainingLabelsMustEndByMs=start-V2_EMBARGO_MS, boundaryTimezone='UTC',
            historicalViewedData='DIAGNOSTIC_ONLY', automaticPromotion=False),
        trialHistory=dict(knownGroups=7, knownScenarios=63, completeHistoricalCount=None, pbo=None, dsr=None),
        production=dict(newTradeTierEnabled=False, newPushSenderConnected=False, shadowRunning=False),
        gates=dict(minTrades=60, minMeanNetPct=.10, bootstrap95LowerAbove=0,
            minWinRatePct=52, minProfitFactor=1.30, maxPboExclusive=.30,
            dsrAboveIfTrialsOver20=.95, frequencyPerDay=[.5,6],
            minFirstThirdCoverageOfWavesAtLeast1_5Pct=.5, shadowDays=14, trialDays=14),
        execution=dict(costFloorPct=.24, discountedFloorPct=.19,
            realQuotesRequired=True, actualLatencyRequired=True,
            missingEvidence='EXCLUDE_FROM_TRADE_QUALIFICATION', sharedInitialUSDT=500),
        developmentResults=rows,
        blockers=['All seven primary development groups have negative mean net returns',
            'No complete live detector, executable quote and actual delivery receipt integration',
            'No prospective outcomes yet; do not reuse seen history as OOS',
            'Incomplete historical trial inventory and aligned PBO/DSR evidence',
            '14-day shadow and 14-day trial not completed'],
        nextSteps=['Connect frozen detector in isolated shadow runner, with restart and causal tests',
            'Collect bid/ask, source/receive/decision times and delivery receipts; flag data gaps',
            'Replay frozen groups on prospective interval without tuning or early winner selection',
            'Report net outcomes, coverage, execution differences and every promotion gate',
            'Register any changed implementation as a new experiment before evaluating it'])
    digest = save_once(dest/'protocol.json', protocol)
    save_once(dest/'seal.json', dict(protocolSha256=digest, sealedAtMs=now))
    print(json.dumps(dict(directory=str(dest), protocolSha256=digest,
        status=protocol['status'], prospective=protocol['prospective']), ensure_ascii=False))


if __name__ == '__main__':
    main()
