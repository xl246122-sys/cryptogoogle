"""Private-device exit inbox transport; no BUY gate, cooldown or order execution."""
import hashlib
import threading
import time
import uuid


class ExitDelivery:
    def __init__(self, store):
        self.store = store
        with store.lock, store.db:
            store.db.executescript('''
            CREATE TABLE IF NOT EXISTS exit_devices(device TEXT PRIMARY KEY, token TEXT NOT NULL, generation TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS exit_outbox(id TEXT PRIMARY KEY, notice_id TEXT NOT NULL, device TEXT NOT NULL,
              generation TEXT NOT NULL, state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
              due INTEGER NOT NULL DEFAULT 0, updated_ms INTEGER NOT NULL, error TEXT);
            CREATE TABLE IF NOT EXISTS exit_receipts(id TEXT PRIMARY KEY, delivery_id TEXT NOT NULL, kind TEXT NOT NULL,
              client_ms INTEGER NOT NULL, server_ms INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS exit_attempts(delivery_id TEXT NOT NULL, attempt INTEGER NOT NULL,
              started_ms INTEGER NOT NULL, finished_ms INTEGER, result TEXT, PRIMARY KEY(delivery_id,attempt));
            ''')

    def register(self, device, token, now):
        if token is not None and (not isinstance(token,str) or not 20<=len(token)<=4096 or any(c.isspace() for c in token)):
            raise ValueError('Invalid push token')
        with self.store.lock, self.store.db:
            if token is None:
                self.store.db.execute('DELETE FROM exit_devices WHERE device=?',(device,))
            else:
                old=self.store.db.execute('SELECT token,generation FROM exit_devices WHERE device=?',(device,)).fetchone()
                generation=old[1] if old and old[0]==token else uuid.uuid4().hex
                other=self.store.db.execute('SELECT device FROM exit_devices WHERE token=? AND device<>?',(token,device)).fetchone()
                if other: raise ValueError('Push token already bound; revoke old binding first')
                self.store.db.execute('INSERT OR REPLACE INTO exit_devices VALUES(?,?,?)',(device,token,generation))
            self._cancel(now)

    def device_status(self, device, token=None):
        if token is not None and (not isinstance(token,str) or not 20<=len(token)<=4096):
            raise ValueError('Invalid push token')
        with self.store.lock:
            row=self.store.db.execute('SELECT token FROM exit_devices WHERE device=?',(device,)).fetchone()
        return {'registered':row is not None,
                'matchesCurrentDevice':None if token is None else bool(row and row[0]==token)}

    def _cancel(self, now):
        self.store.db.execute("""UPDATE exit_outbox SET state='CANCELLED',updated_ms=? WHERE state IN ('PENDING','SENDING')
            AND (NOT EXISTS(SELECT 1 FROM position_notices n WHERE n.id=notice_id AND n.state='ACTIVE')
            OR NOT EXISTS(SELECT 1 FROM exit_devices d WHERE d.device=exit_outbox.device AND d.generation=exit_outbox.generation))""",(now,))

    def sync(self, now):
        with self.store.lock, self.store.db:
            self._cancel(now)
            rows=self.store.db.execute("SELECT n.id,d.device,d.generation FROM position_notices n CROSS JOIN exit_devices d WHERE n.state='ACTIVE'").fetchall()
            for notice,device,generation in rows:
                identity='exit-delivery-'+hashlib.sha256((notice+'|'+device+'|'+generation).encode()).hexdigest()
                self.store.db.execute("INSERT OR IGNORE INTO exit_outbox(id,notice_id,device,generation,state,updated_ms) VALUES(?,?,?,?,'PENDING',?)",
                    (identity,notice,device,generation,now))

    def claim(self, now):
        with self.store.lock, self.store.db:
            self._cancel(now)
            row=self.store.db.execute("""SELECT o.id,o.notice_id,o.device,d.token,o.attempts FROM exit_outbox o
                JOIN exit_devices d ON d.device=o.device AND d.generation=o.generation
                WHERE o.state IN ('PENDING','SENDING') AND o.due<=? ORDER BY o.updated_ms,o.id LIMIT 1""",(now,)).fetchone()
            if not row:return None
            identity,notice,device,token,attempts=row
            attempt=attempts+1
            self.store.db.execute("UPDATE exit_outbox SET state='SENDING',attempts=?,due=?,updated_ms=? WHERE id=?",(attempt,now+180000,now,identity))
            self.store.db.execute('INSERT INTO exit_attempts(delivery_id,attempt,started_ms) VALUES(?,?,?)',(identity,attempt,now))
            return {'id':identity,'noticeId':notice,'device':device,'token':token,'attempt':attempt}

    def finish(self, item, now, state, error=None):
        if state not in ('FCM_ACCEPTED','PENDING','CANCELLED'):raise ValueError('Invalid exit state')
        with self.store.lock, self.store.db:
            self._cancel(now)
            self.store.db.execute('UPDATE exit_attempts SET finished_ms=?,result=? WHERE delivery_id=? AND attempt=? AND finished_ms IS NULL',
                (now,state,item['id'],item['attempt']))
            self.store.db.execute("UPDATE exit_outbox SET state=?,due=?,updated_ms=?,error=? WHERE id=? AND state='SENDING' AND attempts=?",
                (state,now+min(300000,5000*2**min(item['attempt']-1,6)),now,error,item['id'],item['attempt']))

    def receipt(self, device, delivery_id, kind, client_ms, now):
        if kind not in ('FOREGROUND_RECEIVED','OPENED') or isinstance(client_ms,bool) or not isinstance(client_ms,int) or client_ms<=0:
            raise ValueError('Invalid receipt')
        identity=hashlib.sha256((delivery_id+'|'+kind).encode()).hexdigest()
        with self.store.lock, self.store.db:
            row=self.store.db.execute('SELECT device,attempts FROM exit_outbox WHERE id=?',(delivery_id,)).fetchone()
            if not row or row[0]!=device or row[1]<1:raise ValueError('Unknown delivery')
            self.store.db.execute('INSERT OR IGNORE INTO exit_receipts VALUES(?,?,?,?,?)',(identity,delivery_id,kind,client_ms,now))
            client,server=self.store.db.execute('SELECT client_ms,server_ms FROM exit_receipts WHERE id=?',(identity,)).fetchone()
            return {'ok':True,'deliveryId':delivery_id,'kind':kind,'clientAtMs':client,'serverReceivedAtMs':server}

    def health(self):
        with self.store.lock:
            return {'devices':self.store.db.execute('SELECT count(*) FROM exit_devices').fetchone()[0],
                'outbox':dict(self.store.db.execute('SELECT state,count(*) FROM exit_outbox GROUP BY state').fetchall()),
                'receipts':dict(self.store.db.execute('SELECT kind,count(*) FROM exit_receipts GROUP BY kind').fetchall())}


class ExitWorker(threading.Thread):
    def __init__(self, delivery, stop, send, authorized, ready, enabled=False):
        super().__init__(name='position-exit-outbox',daemon=True)
        self.delivery,self.stop,self.send,self.authorized,self.ready,self.enabled=delivery,stop,send,authorized,ready,enabled
        self.heartbeat_ms=0;self.error=None

    def step(self, now):
        self.heartbeat_ms=now
        if not self.enabled or not self.ready():return
        self.delivery.sync(now)
        item=self.delivery.claim(now)
        if not item:return
        if not self.authorized(item['device']):
            self.delivery.register(item['device'],None,now)
            return
        try:
            # Inbox hint only: payload does not contain private inventory or execution prices.
            data={'eventType':'POSITION_EXIT_NOTICE','deliveryId':item['id'],'noticeId':item['noticeId'],
                  'issuedAtMs':str(now),'expiresAtMs':str(now+300000)}
            success=self.send(item['token'],data)
            self.error=None if success else 'FCM_FAILED'
            self.delivery.finish(item,int(time.time()*1000),'FCM_ACCEPTED' if success else 'PENDING',self.error)
        except Exception as exc:
            self.error=type(exc).__name__
            self.delivery.finish(item,now,'PENDING',self.error)

    def run(self):
        while not self.stop.is_set():
            try:self.step(int(time.time()*1000))
            except Exception as exc:self.error=type(exc).__name__
            self.stop.wait(.5)
