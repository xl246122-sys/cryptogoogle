"""Explicitly authorized one-shot test to each bound owner device; no retries."""
import datetime, json, sqlite3, uuid
from pathlib import Path
import firebase_admin
from firebase_admin import credentials, messaging

registry = json.loads(Path('/etc/shotcrypto/devices.json').read_text())
db = sqlite3.connect('file:/opt/shotcrypto/model_library/monitor-v1.sqlite3?mode=ro', uri=True)
firebase_admin.initialize_app(credentials.Certificate('/opt/shotcrypto/serviceAccountKey.json'))
seen = set()
for device in ('owner-phone', 'owner-samsung-s24plus'):
    item = registry.get(device)
    row = db.execute('SELECT token FROM exit_devices WHERE device=?', (item['sha256'],)).fetchone() if item and item.get('write') else None
    if not row:
        print(json.dumps({'target':device, 'status':'NOT_BOUND_NOT_SENT'})); continue
    if row[0] in seen:
        print(json.dumps({'target':device, 'status':'DUPLICATE_TOKEN_NOT_SENT'})); continue
    seen.add(row[0])
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
    identity = 'manual-two-phone-' + uuid.uuid4().hex[:12]
    report = {'testId':identity, 'target':device, 'requestedAtCst':now.isoformat(), 'status':'STARTED', 'phoneDeliveryVerified':False}
    path = Path('/opt/shotcrypto/logs') / (identity + '.json')
    with path.open('x') as f: json.dump(report, f)
    message = messaging.Message(token=row[0], notification=messaging.Notification(
        title='Crypto-G 推送测试（非买入信号）',
        body='锁屏通知测试 ' + now.strftime('%H:%M:%S') + '。仅检查通知、声音和振动，不需要交易。'),
        data={'eventType':'DIAGNOSTIC_TEST','testId':identity},
        android=messaging.AndroidConfig(priority='high', ttl=datetime.timedelta(seconds=120),
        notification=messaging.AndroidNotification(channel_id='shot_crypto_signals_v2', sound='default', default_vibrate_timings=True, tag=identity)))
    try:
        report.update(status='FCM_ACCEPTED', messageId=messaging.send(message))
    except Exception as exc:
        report.update(status='SEND_FAILED', errorType=type(exc).__name__)
    finally:
        path.write_text(json.dumps(report, indent=2))
    print(json.dumps(report))
db.close()
