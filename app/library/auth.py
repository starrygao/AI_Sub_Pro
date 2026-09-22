"""Opaque, revocable browser sessions; existing account hashes remain authoritative."""
import hashlib
import json
import secrets
import sqlite3
import threading
import time
from collections import OrderedDict
from pathlib import Path

COOKIE_NAME = 'aisub_session'
SESSION_SECONDS = 7 * 24 * 3600


def account_identity(account):
    return hashlib.sha256(json.dumps(account,sort_keys=True).encode()).hexdigest()


class Sessions:
    def __init__(self,path):
        self.path=Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(self.path) as db:
            self.path.chmod(0o600)
            db.execute('CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, account TEXT NOT NULL, expires REAL NOT NULL)')

    def create(self,account):
        token=secrets.token_urlsafe(32)
        with sqlite3.connect(self.path) as db:
            db.execute('DELETE FROM sessions WHERE expires<=?',(time.time(),))
            db.execute('INSERT INTO sessions VALUES(?,?,?)',
                       (hashlib.sha256(token.encode()).hexdigest(),account_identity(account),time.time()+SESSION_SECONDS))
        return token

    def valid(self,token,account):
        if not token or len(token)>128:return False
        with sqlite3.connect(self.path) as db:
            row=db.execute('SELECT account,expires FROM sessions WHERE token_hash=?',
                           (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        return bool(row and secrets.compare_digest(row[0],account_identity(account)) and row[1]>time.time())

    def revoke(self,token):
        if not token:return
        with sqlite3.connect(self.path) as db:
            db.execute('DELETE FROM sessions WHERE token_hash=?',(hashlib.sha256(token.encode()).hexdigest(),))


class LoginAttempts:
    """Bound both password hashing work and the in-memory address ledger."""
    def __init__(self):
        self.entries=OrderedDict()
        self.lock=threading.Lock()

    def allow(self,address):
        now=time.monotonic()
        with self.lock:
            times=[t for t in self.entries.pop(address,[]) if now-t<60]
            allowed=len(times)<10
            if allowed:times.append(now)
            self.entries[address]=times
            while len(self.entries)>2048:self.entries.popitem(last=False)
            return allowed
