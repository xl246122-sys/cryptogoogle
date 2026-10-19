"""One explicitly authorized device test; no BUY or position event is generated."""
import datetime,json,sqlite3,uuid
from pathlib import Path
import firebase_admin
from firebase_admin import credentials,messaging
identity='manual-samsung-buy-test-20261018-'+uuid.uuid4().hex[:12]
registry=json.loads(Path('/etc/shotcrypto/devices.json').read_text())
owner=registry['owner-samsung-s24plus'];assert owner.get('write') is True
c=sqlite3.connect('file:/opt/shotcrypto/model_library/monitor-v1.sqlite3?mode=ro',uri=True)
row=c.execute('SELECT token FROM exit_devices WHERE device=?',(owner['sha256'],)).fetchone()
assert row and row[0], 'Owner phone is not bound'
c.close()
now=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
report={'testId':identity,'requestedAtCst':now.isoformat(),'target':'owner-samsung-s24plus','channel':'shot_crypto_signals_v2','route':'DIRECT_DEVICE','status':'STARTED','phoneDeliveryVerified':False}
path=Path('/opt/shotcrypto/logs')/(identity+'.json')
with path.open('x') as f:json.dump(report,f)
firebase_admin.initialize_app(credentials.Certificate('/opt/shotcrypto/serviceAccountKey.json'))
message=messaging.Message(token=row[0],notification=messaging.Notification(title='Crypto-G 买入预警测试（非真实信号）',body='买入预警通道测试 '+now.strftime('%H:%M:%S')+'。仅检查通知、声音和振动，不需要交易。'),data={'eventType':'DIAGNOSTIC_TEST','testId':identity},android=messaging.AndroidConfig(priority='high',ttl=datetime.timedelta(seconds=120),notification=messaging.AndroidNotification(channel_id='shot_crypto_signals_v2',sound='default',default_vibrate_timings=True,tag=identity)))
try:
 result=messaging.send(message)
 report.update(status='FCM_ACCEPTED',messageId=result)
except Exception as exc:
 report.update(status='SEND_FAILED',errorType=type(exc).__name__)
finally:
 path.write_text(json.dumps(report,indent=2))
print(json.dumps(report))
