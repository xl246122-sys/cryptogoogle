"""Append an auditable correction for legacy single-trial defaults; preserve raw runs."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

for source in sorted((ROOT/'model_library/stage-d/D-20261018-002/trials').glob('*.result.json')):
    report = json.loads(source.read_text(encoding='utf-8'))
    for module in report['modules'].values():
        module['diagnosticStatistics'].update(nTrials=None, dsr=None, selectionCorrectionStatus='UNKNOWN_TRIAL_HISTORY')
    report['metadataCorrection'] = dict(originalFile=source.name, originalSha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                                      reason='Legacy summary helper default was not a verified trial count; all trade outcomes unchanged')
    target = source.with_name(source.name.replace('.result.json', '.reviewed.json'))
    with target.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(target)
