"""Small durable discovery ledger; each operation has its own SQLite connection."""
import json
import sqlite3
from contextlib import contextmanager

class Store:
    def __init__(self,path):
        self.path=str(path)
        with self.db() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE IF NOT EXISTS media(path TEXT PRIMARY KEY,state TEXT NOT NULL,updated REAL NOT NULL,payload TEXT NOT NULL)')
            db.execute('CREATE INDEX IF NOT EXISTS media_state ON media(state,updated)')
            db.execute('CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL)')

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

    def setting(self,key,default=None):
        with self.db() as db:
            row=db.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone()
            return json.loads(row[0]) if row else default

    def set_setting(self,key,value):
        with self.db() as db:db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(key,json.dumps(value)))
