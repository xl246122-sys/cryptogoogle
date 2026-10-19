"""Authorized token-only, read-only HTTPS acceptance. Never prints private data."""
import http.client
import argparse
from email.utils import parsedate_to_datetime
import json
from pathlib import Path
import ssl
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',default='audit/wave-stage-c-20261018/v158-public-verification.json')
    args=parser.parse_args()
    config = json.loads((ROOT / '.private/Crypto-G 新绑定配置-20261018.json').read_text(encoding='utf-8-sig'))
    url = urlsplit(config['url'])
    assert url.scheme == 'https' and url.hostname == '43.163.203.127'
    assert not url.username and not url.password
    token = config['token']
    assert isinstance(token, str) and token

    def fetch(auth):
        connection = http.client.HTTPSConnection(url.hostname, url.port or 443,
            context=ssl.create_default_context(), timeout=15)
        try:
            connection.request('GET', '/model-library/market-state',
                headers={'X-Library-Token': token} if auth else {})
            response = connection.getresponse()
            body = response.read()
            date=response.getheader('Date')
            server_ms=int(parsedate_to_datetime(date).timestamp()*1000) if date else None
            return response.status, json.loads(body) if response.status == 200 else {}, server_ms
        finally:
            connection.close()

    status, _, _ = fetch(False)
    assert status == 401, 'Unauthenticated endpoint must return 401'
    samples = []
    keys = ('ok', 'runtimeHealthy', 'feedHealthy', 'notificationHealthy', 'exitNotificationHealthy')
    for attempt in range(20):
        status, last, server_ms = fetch(True)
        assert status == 200, f'Authenticated HTTP status: {status}'
        now = int(time.time() * 1000)
        timestamp = (last.get('snapshot') or {}).get('atMs')
        age = now - timestamp if isinstance(timestamp, (int, float)) else None
        # HTTP Date and snapshot share the server clock. Date has one-second resolution.
        lower=server_ms-timestamp if server_ms is not None and isinstance(timestamp,(int,float)) else None
        upper=lower+1000 if lower is not None else None
        healthy = all(last.get(key) is True for key in keys) and lower is not None and -1000 <= lower and upper <= 10000
        samples.append(dict(atMs=now, healthy=healthy, localClockDifferenceMs=age,
            serverDateMs=server_ms,serverSnapshotAgeBoundsMs=[lower,upper]))
        if len(samples) >= 5 and all(s['healthy'] for s in samples[-5:]):
            break
        time.sleep(2)
    report = dict(atMs=int(time.time()*1000), host=url.hostname, trustedTLS=True,
        unauthenticatedStatus=401, authenticatedStatus=status,
        health={key: last.get(key) for key in keys}, mode=last.get('mode'),
        waveResearch=last.get('waveResearch'), samples=samples)
    report['passed'] = len(samples) >= 5 and all(s['healthy'] for s in samples[-5:]) and report['waveResearch'] == {'mode': 'DISABLED', 'tradeEligible': False}
    output = ROOT / args.output
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=True))
    assert report['passed'], 'Live acceptance did not pass; see sanitized report'

if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('Verification failed:', type(error).__name__)
        raise SystemExit(1)
