"""Assemble scoped release review without promoting research or inventing metrics."""
import hashlib
import json
from pathlib import Path
import subprocess
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'audit/wave-stage-f-20261018'
def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
production=read(OUT/'production.json')
shadow=read(OUT/'shadow-acceptance.json')
evidence=read(OUT/'shadow-evidence.json')
public=read(OUT/'public-https-verified.json')
v158=read(ROOT/'release/V1.58-release-status.json')
v159=read(ROOT/'release/V1.59-release-status.json')
assert production['service']=='active' and not production['qualifiedTradeModules']
assert public['passed'] and shadow['passed']
for name,hashes in v158['backendFiles'].items():assert production['hashes'][name]==hashes['new']
assert sha(ROOT/'release/Crypto-G V1.59.apk')==v159['apkSha256']
assert production['flags']['CRYPTOG_ENABLE_BASELINE_ALERTS']=='1'
assert production['flags']['CRYPTOG_ENABLE_EXIT_ALERTS']=='1'
subprocess.run(['git','apply','--check','release/V1.59-E回退代码.patch'],cwd=ROOT,check=True)
metrics={
 'falsePositiveRate':dict(value=None,status='NOT_ESTABLISHED',reason='No qualified prospective outcomes'),
 'missedOpportunityRate':dict(value=None,status='NOT_ESTABLISHED',reason='Independent future opportunity denominator not yet available'),
 'actualCostDeviation':dict(value=None,status='NOT_ESTABLISHED',reason='Sampled quote models are not actual fills'),
 'newWavePhoneLatency':dict(value=None,status='NOT_MEASURED',reason='New-wave sender not connected'),
 'performanceDegradation':dict(value=None,status='NO_LONGITUDINAL_CONCLUSION',reason='Current service/heartbeat/quote samples passed; long-term comparison pending')}
result=dict(scope='EXISTING_BASELINE_AND_ISOLATED_RESEARCH_DEPLOYMENT',
    operationalReviewPassed=True,fullUpgradeAcceptancePassed=False,
    apkVersion='1.59',backendDeployment='V1.58 integration files',shadowExperiment='WAVE-D-20261018-002',
    tradeTierEnabled=False,qualifiedTradeModules=[],
    phoneDiagnosticsPassed=['LOCKSCREEN','APP_COLD_START','PHONE_RESTART_USER_CONFIRMED'],
    prospectiveStartMs=evidence['startMs'],warmupQuotes=evidence['quoteCounts'].get('warmup',0),
    qualifiedOosTrades=evidence['qualifiedOosTrades'],metrics=metrics,
    rollback=dict(shadow='sudo systemctl disable --now cryptog-wave-shadow.service',
        backendBackup=v158['deployment']['backup'],
        apkSourcePatch='release/V1.59-E回退代码.patch',apkPatchCheckPassed=True,
        apkRollbackRequiresHigherVersionCode=True,rollbackExecuted=False),
    outstanding=['New four-stage actual mobile sender and position lifecycle acceptance',
        'Prospective qualified outcomes and promotion gates',
        'Offline recovery, long retention and remaining E tests',
        'Longitudinal false/missed alert, actual-cost and performance measurements'],
    evidenceHashes={p.name:sha(p) for p in OUT.glob('*.json') if p.name!='review.json'})
(OUT/'review.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(dict(operationalReviewPassed=True,fullUpgradeAcceptancePassed=False,warmupQuotes=result['warmupQuotes'],qualifiedOosTrades=result['qualifiedOosTrades'])))
