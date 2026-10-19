"""Read-only authenticated endpoint acceptance; never print device credentials."""
import json
import time
from pathlib import Path
import urllib.request
import urllib.error

config = json.loads(Path('.private/Crypto-G V1.13设备配置.json').read_text())
url = config['url'] + '/model-library/market-state'
try:
    urllib.request.urlopen(url, timeout=15)
    raise AssertionError('Unauthenticated request accepted')
except urllib.error.HTTPError as error:
    assert error.code == 401

report = {'publicTrustedTLS': True, 'unauthenticatedStatus': 401, 'views': {}}
for view in ('full', 'radar'):
    request = urllib.request.Request(url + ('?view=radar' if view == 'radar' else ''),
                                     headers={'X-Library-Token': config['token']})
    with urllib.request.urlopen(request, timeout=15) as response:
        value = json.load(response)
    now = int(time.time()*1000)
    assert value['ok'] and value['runtimeHealthy'] and value['feedHealthy']
    snapshot = value['snapshot']
    assert -2000 <= now-snapshot['atMs'] <= 10000
    evidence = value['decisionContext']
    assert evidence['atMs'] == snapshot['atMs']
    for frame in ('d1', 'h4', 'h1'):
        row = evidence['frames'][frame]
        assert 0 < row['closeTime'] < snapshot['atMs']
        assert row['state'] in ('UP', 'DOWN', 'ABOVE_99', 'BELOW_99')
    assert all(type(evidence['gates'][m]) is bool for m in ('S1', 'S2', 'S3', 'S4'))
    item = {'snapshotAgeMs': now-snapshot['atMs'], 'decisionContext': evidence,
            'runtimeHealthy': value['runtimeHealthy'], 'feedHealthy': value['feedHealthy']}
    if view == 'full':
        summary = value['researchSummary']
        assert summary['qualification'] == 'UNVERIFIED'
        assert 0 <= now-summary['atMs'] < 40000 and isinstance(summary['groups'], list)
        assert value['notificationHealthy'] and value['exitNotificationHealthy']
        item.update(researchSummary=summary, notificationHealthy=True, exitNotificationHealthy=True)
    report['views'][view] = item
report['atMs'] = int(time.time()*1000)
Path('audit/stage-e-public-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'publicTrustedTLS': True, 'unauthenticatedStatus': 401,
                  'verifiedViews': list(report['views']), 'atMs': report['atMs']}))
