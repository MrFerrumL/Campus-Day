"""Browser access without Telegram: a one-time link from the bot becomes a session.

Only SHA-256 hashes of link and session tokens are stored, so a copy of the
database cannot be used to sign in. A link works once, for ten minutes; a
browser session lasts thirty days and can be revoked from the app.
"""
import hashlib
import secrets
import time

LINK_SECONDS = 10 * 60
SESSION_SECONDS = 30 * 24 * 3600
TOUCH_SECONDS = 10 * 60
MAX_SESSIONS = 10
SCHEMA = """
CREATE TABLE IF NOT EXISTS login_links (hash TEXT PRIMARY KEY, actor INTEGER NOT NULL, expires INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS web_sessions (hash TEXT PRIMARY KEY, actor INTEGER NOT NULL, created INTEGER NOT NULL,
  seen INTEGER NOT NULL, expires INTEGER NOT NULL, agent TEXT NOT NULL DEFAULT '');
"""


def _digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _ready(store):
    store.db.executescript(SCHEMA)


SHARED_SESSION_SECONDS = 7 * 24 * 3600


def available(url):
    """Browser sign-in needs an HTTPS address of the app."""
    from urllib.parse import urlsplit
    return urlsplit(url or "").scheme == "https"


def session_seconds(url):
    """30 days on the app's own host; 7 days under a path of a shared origin,
    where scripts of the other site run on the same origin and could use the cookie."""
    from urllib.parse import urlsplit
    return SESSION_SECONDS if urlsplit(url or "").path in ("", "/") else SHARED_SESSION_SECONDS


def issue_link(store, actor, now=None):
    """A fresh one-time login token for this account; older unused links stop working."""
    now = int(time.time() if now is None else now)
    _ready(store)
    token = secrets.token_urlsafe(32)
    with store.db:
        store.db.execute("DELETE FROM login_links WHERE actor=? OR expires<?", (actor, now))
        store.db.execute("INSERT INTO login_links VALUES (?,?,?)", (_digest(token), actor, now + LINK_SECONDS))
    return token


def redeem(store, token, authorized, agent="", now=None, lifetime=SESSION_SECONDS):
    """Exchange a link token for (session token, actor). The link is spent either way."""
    now = int(time.time() if now is None else now)
    _ready(store)
    if not isinstance(token, str) or not 20 <= len(token) <= 100:
        raise PermissionError("Ссылка недействительна. Получите новую командой /web в боте.")
    with store.db:
        row = store.db.execute("SELECT actor, expires FROM login_links WHERE hash=?", (_digest(token),)).fetchone()
        # The delete is the gate: of two simultaneous requests with one link only one removes the row.
        spent = store.db.execute("DELETE FROM login_links WHERE hash=?", (_digest(token),)).rowcount
        store.db.execute("DELETE FROM login_links WHERE expires<?", (now,))
        if not row or spent != 1 or row[1] < now or row[0] not in authorized:
            raise PermissionError("Ссылка устарела или уже использована. Получите новую командой /web в боте.")
        session = secrets.token_urlsafe(32)
        store.db.execute("DELETE FROM web_sessions WHERE expires<?", (now,))
        # Sessions of disconnected accounts must not come back if the account is linked again.
        marks = ",".join("?" * len(authorized)) or "NULL"
        store.db.execute(f"DELETE FROM web_sessions WHERE actor NOT IN ({marks})", tuple(authorized))
        store.db.execute("INSERT INTO web_sessions VALUES (?,?,?,?,?,?)",
                         (_digest(session), row[0], now, now, now + lifetime, str(agent)[:160]))
        # Keep the newest sessions only.
        store.db.execute("""DELETE FROM web_sessions WHERE actor=? AND hash NOT IN
                            (SELECT hash FROM web_sessions WHERE actor=? ORDER BY created DESC LIMIT ?)""",
                         (row[0], row[0], MAX_SESSIONS))
    return session, row[0]


def session_actor(store, token, authorized, now=None):
    """The account of a valid browser session, or None."""
    now = int(time.time() if now is None else now)
    if not isinstance(token, str) or not 20 <= len(token) <= 100:
        return None
    _ready(store)
    row = store.db.execute("SELECT actor, expires, seen FROM web_sessions WHERE hash=?", (_digest(token),)).fetchone()
    if not row or row[1] < now or row[0] not in authorized:
        if row and row[0] not in authorized:
            revoke(store, row[0], everywhere=True)
        return None
    if now - row[2] > TOUCH_SECONDS:
        with store.db:
            store.db.execute("UPDATE web_sessions SET seen=? WHERE hash=?", (now, _digest(token)))
    return row[0]


def sessions(store, actor, current=None):
    _ready(store)
    rows = store.db.execute("SELECT hash, created, seen, agent FROM web_sessions WHERE actor=? AND expires>=? "
                            "ORDER BY seen DESC", (actor, int(time.time()))).fetchall()
    mine = _digest(current) if current else None
    return [dict(id=h[:12], created=c, seen=s, agent=a, current=h == mine) for h, c, s, a in rows]


def revoke(store, actor, session_id=None, token=None, everywhere=False):
    """End one session (by its short id or own token), or every session of the account when asked."""
    _ready(store)
    with store.db:
        if token:
            store.db.execute("DELETE FROM web_sessions WHERE actor=? AND hash=?", (actor, _digest(token)))
        elif session_id:
            if not isinstance(session_id, str) or len(session_id) != 12:
                raise ValueError("Неизвестное устройство")
            store.db.execute("DELETE FROM web_sessions WHERE actor=? AND substr(hash,1,12)=?", (actor, session_id))
        elif everywhere:
            store.db.execute("DELETE FROM web_sessions WHERE actor=?", (actor,))
