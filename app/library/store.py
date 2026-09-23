"""Small durable discovery ledger; each operation has its own SQLite connection."""
import json
import sqlite3
import time
from pathlib import Path
from contextlib import contextmanager

class Store:
    def __init__(self,path):
        self.path=str(path)
        with self.db() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE IF NOT EXISTS media(path TEXT PRIMARY KEY,state TEXT NOT NULL,updated REAL NOT NULL,payload TEXT NOT NULL)')
            db.execute('CREATE INDEX IF NOT EXISTS media_state ON media(state,updated)')
            db.execute('CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS baseline_media(path TEXT PRIMARY KEY,identity TEXT)')
            db.execute('CREATE INDEX IF NOT EXISTS baseline_identity ON baseline_media(identity)')

    @contextmanager
    def db(self):
        db=sqlite3.connect(self.path,timeout=10)
        try:
            with db:yield db
        finally:db.close()

    def get(self,path):
        with self.db() as db:
            row=db.execute('SELECT payload FROM media WHERE path=?',(str(path),)).fetchone()
            return json.loads(row[0]) if row else None

    def put(self,row):
        with self.db() as db:
            db.execute('INSERT INTO media VALUES(?,?,?,?) ON CONFLICT(path) DO UPDATE SET state=excluded.state,updated=excluded.updated,payload=excluded.payload',
                       (row['path'],row['state'],row['updated'],json.dumps(row,ensure_ascii=False)))

    def rows(self,states=None,limit=100,offset=0,oldest=False):
        where=' WHERE state IN ('+','.join('?' for _ in states)+')' if states else ''
        with self.db() as db:
            return [json.loads(x[0]) for x in db.execute('SELECT payload FROM media'+where+' ORDER BY '+("COALESCE(json_extract(payload, '$.priority'),0) DESC, updated ASC" if oldest else 'updated DESC')+' LIMIT ? OFFSET ?',tuple(states or [])+(limit,offset))]

    def counts(self):
        with self.db() as db:return dict(db.execute('SELECT state,count(*) FROM media GROUP BY state').fetchall())

    def waiting_ready(self,now,limit=100):
        """Retry oldest checked arrivals first; priority cannot pin a blocked page."""
        with self.db() as db:
            return [json.loads(row[0]) for row in db.execute(
                "SELECT payload FROM media WHERE state='waiting' "
                "AND COALESCE(json_extract(payload,'$.next_attempt_at'),0)<=? "
                "ORDER BY updated ASC, COALESCE(json_extract(payload,'$.priority'),0) DESC LIMIT ?",
                (now,limit))]

    def pending_refresh(self,limit=50):
        with self.db() as db:
            return [json.loads(row[0]) for row in db.execute(
                "SELECT payload FROM media WHERE state='done' AND json_extract(payload,'$.refresh_pending')=1 "
                "ORDER BY updated ASC LIMIT ?",(limit,))]

    def setting(self,key,default=None):
        with self.db() as db:
            row=db.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone()
            return json.loads(row[0]) if row else default

    def set_setting(self,key,value):
        self.set_settings({key:value})

    def set_settings(self,values):
        with self.db() as db:
            db.executemany('INSERT OR REPLACE INTO settings VALUES(?,?)',
                           [(key,json.dumps(value)) for key,value in values.items()])

    def baseline_contains(self,path,current=None):
        identity=json.dumps(current) if current else ''
        with self.db() as db:
            return db.execute('SELECT 1 FROM baseline_media WHERE path=? OR identity=? LIMIT 1',(str(path),identity)).fetchone() is not None

    def install_baseline(self,entries,roots,preserve_roots=()):
        """Commit a complete inventory atomically; a failed walk never seals a partial baseline."""
        now=time.time()
        with self.db() as db:
            entries=dict(entries)
            for path,payload in db.execute('SELECT path,payload FROM media'):
                if any(Path(path).is_relative_to(root) for root in roots) and not any(Path(path).is_relative_to(root) for root in preserve_roots):
                    entries.setdefault(path,json.loads(payload).get('fingerprint'))
            db.executemany('INSERT OR IGNORE INTO baseline_media VALUES(?,?)',
                           [(path,json.dumps(value) if value else None) for path,value in entries.items()])
            prior=db.execute("SELECT value FROM settings WHERE key='baseline'").fetchone()
            meta=json.loads(prior[0]) if prior else {'started_at':now,'roots':[]}
            meta.update(completed_at=now,roots=sorted(set(meta['roots'])|set(roots)),
                        count=db.execute('SELECT count(*) FROM baseline_media').fetchone()[0])
            db.execute("INSERT OR REPLACE INTO settings VALUES('baseline',?)",(json.dumps(meta),))

    def exclude_unstarted_outside_roots(self, roots):
        with self.db() as db:
            for path, payload in db.execute('SELECT path,payload FROM media').fetchall():
                if not json.loads(payload).get('project_id') and not any(Path(path).is_relative_to(root) for root in roots):
                    db.execute('DELETE FROM media WHERE path=?', (path,))

    def exclude_baseline_rows(self):
        """Keep genuine project history, removing only old discovery queue entries."""
        cancelled=[]
        with self.db() as db:
            rows=db.execute("SELECT m.path,m.payload FROM media m JOIN baseline_media b ON m.path=b.path WHERE m.state NOT IN ('done','cancelled')").fetchall()
            for path,payload in rows:
                row=json.loads(payload)
                if row.get('project_id'):
                    if row['state'] in {'translating','publishing'}:cancelled.append(row['project_id'])
                    row.update(state='cancelled',reason='现有视频不补翻译，任务已停止',updated=time.time())
                    db.execute('UPDATE media SET state=?,updated=?,payload=? WHERE path=?',
                               ('cancelled',row['updated'],json.dumps(row,ensure_ascii=False),path))
                else:db.execute('DELETE FROM media WHERE path=?',(path,))
        return cancelled
