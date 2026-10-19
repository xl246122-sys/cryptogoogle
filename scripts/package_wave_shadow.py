"""New implementation registration linked to the prior future-window protocol."""
import hashlib
import json
from pathlib import Path
import time
import zipfile
ROOT=Path(__file__).resolve().parents[1]

def main():
    previous=ROOT/'model_library/wave-stage-d/WAVE-D-20261018-001/protocol.json'
    protocol=json.loads(previous.read_text(encoding='utf-8'))
    dest=ROOT/'model_library/wave-stage-d/WAVE-D-20261018-002'
    dest.mkdir(parents=True,exist_ok=False)
    protocol.update(experimentId=dest.name,status='IMPLEMENTATION_REGISTERED_BEFORE_UNSEEN_WINDOW',
        frozenAtMs=int(time.time()*1000),parentProtocolRawSha256=hashlib.sha256(previous.read_bytes()).hexdigest(),
        implementation=dict(calibrationBoundary='UTC midnight, past90 days excluding boundary',
            quoteSource='Read-only production WS journal, every available evaluation',
            replayCatchup='Late signals rejected, no historical quote invention',
            delivery='Existing baseline exit transport receipts only; no new-wave sender',
            model='63 scenario accounts, sampled ask/bid, full registered friction on top of spread',
            qualification='Modeled outcomes are diagnostic, not actual fills or qualified trade evidence',
            exit='sampled bid stop first, target, scheduled E1/E2, time; tick extremes between samples unknown'),
        production=dict(newTradeTierEnabled=False,newPushSenderConnected=False,shadowRunning=False))
    protocol.pop('sourceHashes',None)
    protocol.pop('archiveSha256',None)
    (dest/'protocol.json').write_bytes((json.dumps(protocol,ensure_ascii=False,indent=2)+'\n').encode())
    paths=list((ROOT/'scratch/cryptog').glob('*.py'))
    paths += [ROOT/'scripts'/name for name in ['run_wave_shadow.py','research_btc_stage_b.py',
        'research_btc_dynamic.py','report_btc_wave_space.py','verify_wave_shadow_detector.py']]
    paths += [ROOT/'tests/test_wave_shadow.py']
    files={p.relative_to(ROOT).as_posix():p.read_bytes() for p in paths}
    files['protocol.json']=(dest/'protocol.json').read_bytes()
    files['seed.csv']=(ROOT/'audit/btc-dynamic-study-20261018/input-181days.csv').read_bytes()
    manifest=dict(registeredMs=int(time.time()*1000),experimentId=dest.name,
        files={n:hashlib.sha256(b).hexdigest() for n,b in files.items()})
    raw=(json.dumps(manifest,indent=2)+'\n').encode()
    files['deployment-manifest.json']=raw
    (dest/'deployment-manifest.json').write_bytes(raw)
    target=ROOT/'release/wave-shadow-d002.zip'
    with zipfile.ZipFile(target,'x',zipfile.ZIP_DEFLATED) as archive:
        for name,body in files.items():archive.writestr(name,body)
    print(json.dumps(dict(package=str(target),sha256=hashlib.sha256(target.read_bytes()).hexdigest(),bytes=target.stat().st_size)))

if __name__=='__main__':main()
