import json
with open('scratch/audit_report_data.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

for mod, info in data.items():
    print(f"=== {mod} ===")
    print("Candidates:", info.get('candidates'))
    print("Filled:", info.get('filled'))
    fs = info.get('fullSample') or {}
    print("FullSample:", {k: fs.get(k) for k in ('trades', 'winRate', 'expectancyPct', 'profitFactor', 'meanHoldingMinutes')})
    oos = info.get('outOfSample') or {}
    print("OOS:", {k: oos.get(k) for k in ('trades', 'winRate', 'expectancyPct', 'profitFactor')})
