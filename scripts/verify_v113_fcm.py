"""Validate Firebase credentials and Android payload without sending to a phone."""
import datetime
import json
import firebase_admin
from firebase_admin import credentials,messaging
firebase_admin.initialize_app(credentials.Certificate('/opt/shotcrypto/serviceAccountKey.json'))
message=messaging.Message(topic='shot_crypto_signals',
    notification=messaging.Notification(title='Crypto-G 发布自检',body='仅验证请求，不发送到手机。'),
    data={'eventType':'RELEASE_VALIDATION','version':'1.13'},
    android=messaging.AndroidConfig(priority='high',ttl=datetime.timedelta(seconds=60),
        notification=messaging.AndroidNotification(channel_id='cryptog_position_exits_v1',visibility='private')))
messaging.send(message,dry_run=True)
print(json.dumps({'fcmDryRunAccepted':True,'actualPhoneSend':False,'phoneDeliveryVerified':False}))
