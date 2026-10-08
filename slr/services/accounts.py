"""Google identities, expiring OAuth state and revocable application sessions."""
import hashlib
import secrets
import time
from uuid import uuid4
from slr.services import live_review

def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()

def connect():
    conn = live_review._connect()
    conn.execute("CREATE TABLE IF NOT EXISTS google_accounts (id TEXT PRIMARY KEY, subject TEXT UNIQUE NOT NULL, email TEXT NOT NULL, name TEXT NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS account_tokens (digest TEXT PRIMARY KEY, account_id TEXT NOT NULL, expires REAL NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS oauth_states (digest TEXT PRIMARY KEY, nonce TEXT NOT NULL, verifier TEXT NOT NULL, expires REAL NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS login_tickets (digest TEXT PRIMARY KEY, binding TEXT NOT NULL, account_id TEXT NOT NULL, expires REAL NOT NULL)")
    return conn

def begin():
    state, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(3))
    with connect() as conn:
        conn.execute("DELETE FROM oauth_states WHERE expires <= ?", (time.time(),))
        conn.execute("INSERT INTO oauth_states VALUES (?,?,?,?)", (digest(state), nonce, verifier, time.time()+600))
    return state, nonce, verifier

def consume_state(state):
    with connect() as conn:
        row = conn.execute("SELECT nonce,verifier,expires FROM oauth_states WHERE digest=?", (digest(state),)).fetchone()
        conn.execute("DELETE FROM oauth_states WHERE digest=?", (digest(state),))
    if not row or row[2] <= time.time():
        raise ValueError("Sign-in expired. Please try again.")
    return row[0], row[1]

def issue_ticket(claims):
    if not claims.get("sub") or claims.get("email_verified") is not True or not claims.get("email"):
        raise ValueError("Google must verify your email address.")
    ticket, binding = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    with connect() as conn:
        row = conn.execute("SELECT id FROM google_accounts WHERE subject=?", (claims["sub"],)).fetchone()
        account_id = row[0] if row else uuid4().hex
        conn.execute("INSERT INTO google_accounts VALUES (?,?,?,?) ON CONFLICT(subject) DO UPDATE SET email=excluded.email,name=excluded.name", (account_id, claims["sub"], claims["email"], claims.get("name", claims["email"])))
        conn.execute("DELETE FROM login_tickets WHERE expires <= ?", (time.time(),))
        conn.execute("INSERT INTO login_tickets VALUES (?,?,?,?)", (digest(ticket), digest(binding), account_id, time.time()+120))
    return ticket, binding

def exchange_ticket(ticket, binding):
    with connect() as conn:
        row = conn.execute("SELECT account_id FROM login_tickets WHERE digest=? AND binding=? AND expires>?", (digest(ticket), digest(binding), time.time())).fetchone()
        if not row:
            raise ValueError("Sign-in link expired or belongs to another browser.")
        conn.execute("DELETE FROM login_tickets WHERE digest=?", (digest(ticket),))
        token = secrets.token_urlsafe(32)
        conn.execute("INSERT INTO account_tokens VALUES (?,?,?)", (digest(token), row[0], time.time()+86400))
    return {"token": token, **authenticate(token)}

def authenticate(token):
    with connect() as conn:
        row = conn.execute("SELECT a.id,a.email,a.name FROM account_tokens t JOIN google_accounts a ON a.id=t.account_id WHERE t.digest=? AND t.expires>?", (digest(token), time.time())).fetchone()
    if not row:
        raise ValueError("Your login expired. Please sign in again.")
    return dict(id=row[0], email=row[1], name=row[2])

def logout(token):
    with connect() as conn:
        conn.execute("DELETE FROM account_tokens WHERE digest=?", (digest(token),))
