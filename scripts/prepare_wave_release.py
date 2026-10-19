"""Prepare reviewed V1.58 backend package; no network or secret access."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[1]
def sha(data):return hashlib.sha256(data).hexdigest()

runtime=(ROOT/'scratch/cryptog/runtime.py').read_text(encoding='utf-8')
old=runtime.replace("        self.wave = None\n        if os.environ.get('CRYPTOG_ENABLE_WAVE_RESEARCH') == '1':\n            from .wave_integration import WaveIntegration\n            self.wave = WaveIntegration(str(Path(library.LIBRARY_DIR)/'wave-research.sqlite3'))\n",'')
old=old.replace("        wave = getattr(self, 'wave', None)\n        if wave is not None:\n            wave.expire(now)\n",'')
old=old.replace("        return {'observationMessages':observation_messages,\n                'waveResearch':{'mode':'RESEARCH_ONLY' if wave is not None else 'DISABLED','tradeEligible':False},\n                'waveMessages':wave.messages() if wave is not None else [],\n                'ok':True,'schema':1,'mode':'BASELINE' if self.live else 'SHADOW',", "        return {'observationMessages':observation_messages,'ok':True,'schema':1,'mode':'BASELINE' if self.live else 'SHADOW',")
old=old.replace("                if getattr(self, 'wave', None) is not None:\n                    self.wave.close()\n",'')
assert 'self.wave' not in old and 'waveResearch' not in old
# Earlier deployments used local file bytes. Match the existing CRLF source format.
old_bytes=old.replace('\n','\r\n').encode()
manifest={}
for name in ['cryptog/runtime.py','cryptog/wave_integration.py']:
    manifest[name]={'old':sha(old_bytes) if name.endswith('runtime.py') else None,
                    'new':sha((ROOT/'scratch'/name).read_bytes())}
package=ROOT/'release/Crypto-G V1.58 backend.zip'
with zipfile.ZipFile(package,'w',zipfile.ZIP_DEFLATED) as z:
    z.writestr('manifest.json',json.dumps(manifest,indent=2))
    for name in manifest:z.write(ROOT/'scratch'/name,name)
    z.write(ROOT/'tests/test_wave_integration.py','test_wave_integration.py')
script=(ROOT/'scripts/deploy_audit_stage_e.py').read_text(encoding='utf-8')
script=script.replace('cryptog-stage-e-20261018.zip','cryptog-wave-v158.zip').replace('cryptog-stage-e-','cryptog-wave-v158-')
script=script.replace('test_audit_stage_e.py','test_wave_integration.py').replace('audit-stage-e-','wave-v158-')
script=script.replace("        subprocess.run(['systemctl', 'start', 'shotcrypto.service'], check=True)\n    except Exception:",
    "        subprocess.run(['systemctl', 'start', 'shotcrypto.service'], check=True)\n        __import__('time').sleep(5)\n        subprocess.run(['systemctl', 'is-active', '--quiet', 'shotcrypto.service'], check=True)\n    except Exception:")
script=script.replace("            if (backup/name).exists():\n                shutil.copy2(backup/name, ROOT/name)\n", "            if (backup/name).exists():\n                shutil.copy2(backup/name, ROOT/name)\n            elif manifest[name]['old'] is None:\n                (ROOT/name).unlink(missing_ok=True)\n")
(ROOT/'release/deploy-wave-v158.py').write_text(script,encoding='utf-8')
report=dict(versionName='1.58',versionCode=158,apkSha256=sha((ROOT/'release/Crypto-G V1.58.apk').read_bytes()),
    packageSha256=sha(package.read_bytes()),backendFiles=manifest,deployed=False,
    deploymentBlocker='SSH_CREDENTIAL_UNAVAILABLE',newTradeTierEnabled=False,
    expectedBaseNote='Reconstructed pre-C local CRLF runtime; server hash must match. Do not override mismatch without diff review.')
(ROOT/'release/V1.58-release-status.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report))
