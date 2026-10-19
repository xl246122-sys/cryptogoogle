"""Seal a prospective protocol and source snapshot without inspecting future results."""
import hashlib
import argparse
import json
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scratch'))
from cryptog import config
from cryptog.input_contract import INPUT_CONTRACT
from cryptog.research_protocol import DAY_MS, save_once


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--experiment-id', default='D-20261018-001')
    args = parser.parse_args()
    if not args.experiment_id or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in args.experiment_id):
        raise ValueError('Invalid experiment ID')
    now = int(time.time()*1000)
    dest = ROOT/'model_library'/'stage-d'/args.experiment_id
    dest.mkdir(parents=True, exist_ok=False)
    sources = sorted((ROOT/'scratch'/'cryptog').glob('*.py')) + sorted((ROOT/'tests').glob('test_*.py'))
    sources += [ROOT/'scripts'/'audit_stage_d_data.py', ROOT/'scripts'/'backfill_stage_d.py',
                Path(__file__).resolve(), ROOT/'AGENTS.md', ROOT/'tests'/'run_python_offline.py']
    hashes = {}
    with zipfile.ZipFile(dest/'source.zip', 'x', zipfile.ZIP_DEFLATED) as archive:
        for path in sources:
            name = path.relative_to(ROOT).as_posix()
            data = path.read_bytes()
            hashes[name] = hashlib.sha256(data).hexdigest()
            archive.writestr(name, data)
    observations = {}
    for label in ('local', 'live', 'diagnostic'):
        path = ROOT/'audit'/f'stage-d-{label}-data.json'
        body = json.loads(path.read_text(encoding='utf-8-sig'))
        save_once(dest/f'{label}-coverage.json', body)
        observations[label] = body
    start = (now//DAY_MS+1)*DAY_MS
    constants = {k: v for k, v in vars(config).items() if k.startswith('V2_')
                 and isinstance(v, (str, int, float, bool, list, dict, tuple))}
    protocol = dict(experimentId=dest.name, status='PREPARED_NOT_VALIDATED', frozenAtMs=now,
                    sourceHashes=hashes, sourceArchiveSha256=hashlib.sha256((dest/'source.zip').read_bytes()).hexdigest(),
                    constants=constants, inputContract=INPUT_CONTRACT,
                    historicalDataUse='DIAGNOSTIC_ONLY: previously viewed intervals cannot qualify as independent OOS',
                    prospective=dict(startMs=start, endMs=start+config.V2_OOS_MS,
                                     trainingLabelsMustEndByMs=start-config.V2_EMBARGO_MS,
                                     status='SEALED_FUTURE_INTERVAL', automaticPromotion=False),
                    execution=dict(resolution='1m minimum', entry='after measured notification/manual latency; touch alone is not proof of fill',
                                   latencyStatus='NOT_MEASURED', uncertain='exclude from formal labels and report conservative sensitivity',
                                   capital='500 USDT shared cash ledger; enforce overlap and cash constraints',
                                   replay='same production evaluate; historical quote assumptions must be diagnostic'),
                    trials=dict(historicalCount=None, status='INCOMPLETE_HISTORY', registeredRuns=0,
                                pbo=None, dsr=None, reason='No complete aligned actual trial matrix; do not invent trials'),
                    outstanding=['diagnostic replay and capital simulation results',
                                 'measured delivery/manual latency and fill evidence', 'full trial history and aligned PBO/DSR inputs',
                                 'future independent interval', 'qualifying shadow 14 days and trial 14 days'])
    digest = save_once(dest/'protocol.json', protocol)
    print(json.dumps(dict(directory=str(dest), protocolSha256=digest, prospective=protocol['prospective']), indent=2))


if __name__ == '__main__':
    main()
