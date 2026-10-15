"""Temporary localhost TLS integration test; no production secrets or production writes."""
import datetime
import hashlib
import json
import os
import pathlib
import ssl
import sys
import tempfile
import urllib.request
import urllib.error
import socket
from types import SimpleNamespace
root=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'tests'))
from offline_daemon import daemon as m
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

directory=pathlib.Path(tempfile.mkdtemp(prefix='cryptog-tls-test-'))
key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'localhost')])
now=datetime.datetime.now(datetime.timezone.utc)
cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
      .serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(minutes=1))
      .not_valid_after(now+datetime.timedelta(hours=1)).add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost')]),critical=False)
      .sign(key,hashes.SHA256()))
cert_path=directory/'cert.pem';key_path=directory/'key.pem';auth_path=directory/'devices.json'
cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
token='integration_test_device_'+'a'*40
auth_path.write_text(json.dumps({'test':{'sha256':hashlib.sha256(token.encode()).hexdigest(),'write':True}}))
os.environ.update(CRYPTOG_TLS_CERT=str(cert_path),CRYPTOG_TLS_KEY=str(key_path),CRYPTOG_DEVICE_AUTH_FILE=str(auth_path),CRYPTOG_API_BIND='127.0.0.1')
m.LIBRARY_PORT=0
server=m.start_model_library_server()
context=ssl.create_default_context(cafile=str(cert_path))
base='https://localhost:'+str(server.server_port)+'/model-library/'
checks=[]
def request(path, payload=None, credential=token):
    req=urllib.request.Request(base+path,headers={'X-Library-Token':credential,'Content-Type':'application/json'},data=None if payload is None else json.dumps(payload).encode())
    try:
        with urllib.request.urlopen(req,context=context,timeout=5) as r: return r.status,json.load(r)
    except urllib.error.HTTPError as exc: return exc.code,json.load(exc)
try:
    status,data=request('capabilities');assert status==200 and data['userActionProtocol']==2;checks.append('TLS capabilities')
    with socket.create_connection(('127.0.0.1',server.server_port),timeout=2):
        assert request('capabilities')[0]==200
    checks.append('stalled TLS client does not block other devices')
    assert request('capabilities',credential='bad')[0]==401;checks.append('unauthorized rejected')
    payload={'recordType':'PHONE_RECEIVED','eventId':'local-tls-test','alertId':'local-only','actedAtMs':int(now.timestamp()*1000)}
    first=request('action',payload);second=request('action',payload)
    assert first[0]==second[0]==200 and first[1]['eventId']==second[1]['eventId'];checks.append('idempotent action ACK')
    status,data=request('records?alertId=local-only');assert status==200 and len(data['records']['user_actions'])==1;checks.append('one durable action')
    status,data=request('market-state');assert status==200 and data['snapshot'] is None;checks.append('unknown state without runtime')
    from cryptog.storage import EventStore
    from cryptog.exit_delivery import ExitDelivery
    from test_positions import check, fill, NOW
    store=EventStore(str(directory/'position-test.sqlite3'))
    m.RUNTIME=SimpleNamespace(store=store,exit_delivery=ExitDelivery(store),exit_enabled=False)
    notice=store.reconcile_positions([check([fill()],97)],NOW+1000)[0]['notice']['id']
    first=request('position-review',{'noticeId':notice});second=request('position-review',{'noticeId':notice})
    assert first[0]==200 and first==second;checks.append('idempotent position review ACK over TLS')
    assert request('position-review',{'noticeId':'missing'})[0]==409;checks.append('unknown position notice rejected')
    status,data=request('exit-device',{'token':'local-test-push-token-'+('a'*40)})
    assert status==200 and data['registered'] and not data['pushEnabled'];checks.append('device enrollment remains shadow')
    status,data=request('exit-device-status',{'token':'local-test-push-token-'+('a'*40)})
    assert status==200 and data=={'ok':True,'registered':True,'matchesCurrentDevice':True,'pushEnabled':False};checks.append('authenticated matching device status')
    assert request('exit-device-status',{'token':'other-device-token-'+('b'*40)})[1]['matchesCurrentDevice'] is False
    assert request('exit-device-status',{'token':None})[1]['matchesCurrentDevice'] is None
    assert request('exit-device-status',{'token':'short'})[0]==400;checks.append('other unknown and malformed device status')
    delivery=m.RUNTIME.exit_delivery;delivery.sync(NOW);item=delivery.claim(NOW)
    receipt={'deliveryId':item['id'],'kind':'OPENED','clientAtMs':NOW+100}
    first=request('exit-receipt',receipt);second=request('exit-receipt',receipt)
    assert first[0]==200 and first==second;checks.append('exit receipt durable duplicate ACK')
    assert request('exit-receipt',{**receipt,'deliveryId':'missing'})[0]==400;checks.append('unknown exit receipt rejected')
    assert request('exit-device',{'token':None})[1]['registered'] is False;checks.append('device unbind cancels pending sends')
    assert delivery.health()['outbox']=={'CANCELLED':1}
    auth_path.write_text(json.dumps({'test':{'sha256':hashlib.sha256(token.encode()).hexdigest(),'write':False}}))
    assert request('position-review',{'noticeId':notice})[0]==401;checks.append('read-only device cannot review')
    assert store.db.execute('SELECT state FROM position_notices WHERE id=?',(notice,)).fetchone()[0]=='ACTIVE';checks.append('review never closes risk notice')
    m.RUNTIME=None;store.close()
finally:
    server.shutdown();server.server_close()
report={'checks':checks,'passed':len(checks),'network':'localhost TLS only','productionWrites':False}
(root/'audit/stage1').mkdir(exist_ok=True)
(root/'audit/stage1/https-integration.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report))
