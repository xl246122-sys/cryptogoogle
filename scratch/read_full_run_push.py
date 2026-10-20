from pathlib import Path
txt = Path('/opt/shotcrypto/wave-observe-push-v1/scripts/run_wave_research_push.py').read_text(encoding='utf-8')
print("Lines count:", len(txt.splitlines()))
print(txt)
