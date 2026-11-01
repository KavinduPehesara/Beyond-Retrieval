"""Google identities, expiring OAuth state and revocable application sessions."""
import hashlib
import os
import secrets
import time
from uuid import uuid4
from slr.services import live_review

def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def allowed_emails() -> set[str]:
    """Who may sign in, from ALLOWED_EMAILS: a comma-separated list.

    Unset means anyone Google will vouch for, which is the right default on
    a laptop and the wrong one anywhere with a public address: the model
    keys are the server's, so an open sign-in is an open invitation to spend
    them. Set it before putting this behind a domain.
    """
    raw = os.getenv("ALLOWED_EMAILS", "")
    return {e.strip().casefold() for e in raw.split(",") if e.strip()}

#: The browser deletes the session cookie when it closes; this caps how long
#: a browser that is never closed stays signed in.
SESSION_SECONDS = 7 * 86400


def _add_column(conn, table, column, spec):
    """Add a column to a table that is already in somebody's database.

    CREATE TABLE IF NOT EXISTS does nothing at all to a table that already
    exists, so a column added later has to be migrated in separately or
    every install made before today keeps reading the old shape.
    """
    existing = {row[1] for row in conn.execute("PRAGMA table_info(%s)" % table)}
    if column not in existing:
        conn.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, column, spec))


def connect():
    conn = live_review._connect()
    conn.execute("CREATE TABLE IF NOT EXISTS google_accounts (id TEXT PRIMARY KEY, subject TEXT UNIQUE NOT NULL, email TEXT NOT NULL, name TEXT NOT NULL, picture TEXT NOT NULL DEFAULT '')")
    _add_column(conn, "google_accounts", "picture", "TEXT NOT NULL DEFAULT ''")
    conn.execute("CREATE TABLE IF NOT EXISTS account_tokens (digest TEXT PRIMARY KEY, account_id TEXT NOT NULL, expires REAL NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS oauth_states (digest TEXT PRIMARY KEY, nonce TEXT NOT NULL, verifier TEXT NOT NULL, expires REAL NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS login_tickets (digest TEXT PRIMARY KEY, binding TEXT NOT NULL, account_id TEXT NOT NULL, expires REAL NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS browser_sessions (digest TEXT PRIMARY KEY, account_id TEXT NOT NULL, expires REAL NOT NULL)")
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

def issue_ticket(claims, session=None):
    if not claims.get("sub") or claims.get("email_verified") is not True or not claims.get("email"):
        raise ValueError("Google must verify your email address.")
    allowed = allowed_emails()
    if allowed and claims["email"].casefold() not in allowed:
        # Refused before the account row is written, so a stranger who gets
        # this far leaves nothing behind but a log line.
        raise ValueError("This deployment is limited to invited accounts.")
    ticket, binding = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    with connect() as conn:
        row = conn.execute("SELECT id FROM google_accounts WHERE subject=?", (claims["sub"],)).fetchone()
        account_id = row[0] if row else uuid4().hex
        # Columns named rather than positional: this table gains one here,
        # and VALUES (?,?,?,?) would have kept inserting into the old shape.
        # The picture is Google's own URL, so the browser fetches it from
        # Google when the menu opens; nothing of the image is stored here.
        conn.execute(
            "INSERT INTO google_accounts (id,subject,email,name,picture) VALUES (?,?,?,?,?) "
            "ON CONFLICT(subject) DO UPDATE SET email=excluded.email,name=excluded.name,picture=excluded.picture",
            (account_id, claims["sub"], claims["email"],
             claims.get("name", claims["email"]), claims.get("picture") or ""))
        conn.execute("DELETE FROM login_tickets WHERE expires <= ?", (time.time(),))
        conn.execute("INSERT INTO login_tickets VALUES (?,?,?,?)", (digest(ticket), digest(binding), account_id, time.time()+120))
        if session:
            conn.execute("DELETE FROM browser_sessions WHERE expires <= ?", (time.time(),))
            conn.execute("INSERT INTO browser_sessions VALUES (?,?,?)", (digest(session), account_id, time.time()+SESSION_SECONDS))
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
        row = conn.execute("SELECT a.id,a.email,a.name,a.picture FROM account_tokens t JOIN google_accounts a ON a.id=t.account_id WHERE t.digest=? AND t.expires>?", (digest(token), time.time())).fetchone()
    if not row:
        raise ValueError("Your login expired. Please sign in again.")
    return dict(id=row[0], email=row[1], name=row[2], picture=row[3] or "")

def logout(token):
    with connect() as conn:
        conn.execute("DELETE FROM account_tokens WHERE digest=?", (digest(token),))

def resume(session):
    """Sign a browser back in from its session cookie, with a fresh token.

    The cookie is set at the Google callback, so only the browser that
    signed in holds it; only its digest is stored here.
    """
    with connect() as conn:
        row = conn.execute("SELECT account_id FROM browser_sessions WHERE digest=? AND expires>?", (digest(session), time.time())).fetchone()
        if not row:
            raise ValueError("This browser session has ended. Please sign in again.")
        token = secrets.token_urlsafe(32)
        conn.execute("INSERT INTO account_tokens VALUES (?,?,?)", (digest(token), row[0], time.time()+86400))
    return {"token": token, **authenticate(token)}

def end_session(session):
    with connect() as conn:
        conn.execute("DELETE FROM browser_sessions WHERE digest=?", (digest(session),))
