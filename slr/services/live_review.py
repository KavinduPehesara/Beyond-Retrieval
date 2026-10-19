"""Ad-hoc review records, deliberately isolated from benchmark tables."""
from datetime import datetime, timezone
from functools import lru_cache
import json
from pathlib import Path
import sqlite3
from threading import Lock
from uuid import uuid4


STORE = Path(__file__).resolve().parents[2] / "data" / "live_reviews.sqlite3"
EMBED_LOCK = Lock()


def _connect():
    STORE.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(STORE, timeout=30)
    conn.execute("CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS actions (id INTEGER PRIMARY KEY, session_id TEXT, work_id TEXT, payload TEXT, created_at TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS maps (session_id TEXT PRIMARY KEY, payload TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS session_owners (session_id TEXT PRIMARY KEY, account_id TEXT NOT NULL, created_at TEXT NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS removed_projects (session_id TEXT PRIMARY KEY)")
    return conn


def create_session(payload, owner_id=None):
    session_id = uuid4().hex
    payload = {**payload, "session_id": session_id}
    with _connect() as conn:
        conn.execute("INSERT INTO sessions VALUES (?, ?)", (session_id, json.dumps(payload)))
        if owner_id:
            conn.execute("INSERT INTO session_owners VALUES (?,?,?)", (session_id, owner_id, datetime.now(timezone.utc).isoformat()))
    return payload


def require_owner(session_id, account_id):
    with _connect() as conn:
        row = conn.execute("SELECT 1 FROM session_owners WHERE session_id=? AND account_id=? AND session_id NOT IN (SELECT session_id FROM removed_projects)", (session_id, account_id)).fetchone()
    if not row:
        raise KeyError("Review not found in your account")


def list_sessions(account_id):
    with _connect() as conn:
        rows = conn.execute("SELECT s.id,s.payload,o.created_at FROM sessions s JOIN session_owners o ON o.session_id=s.id WHERE o.account_id=? AND s.id NOT IN (SELECT session_id FROM removed_projects) ORDER BY o.created_at DESC", (account_id,)).fetchall()
    return [dict(session_id=r[0], query=json.loads(r[1])["query"], name=json.loads(r[1]).get("project_name", json.loads(r[1])["query"]), n_found=len(json.loads(r[1])["papers"]), created_at=r[2]) for r in rows]


def read_session(session_id):
    with _connect() as conn:
        row = conn.execute("SELECT payload FROM sessions WHERE id=?", (session_id,)).fetchone()
        if not row:
            raise KeyError("Review session not found")
        session = json.loads(row[0])
        events = conn.execute("SELECT work_id,payload,created_at FROM actions WHERE session_id=? ORDER BY id", (session_id,)).fetchall()
    session["reviewer_actions"] = [dict(work_id=r[0], **json.loads(r[1]), saved_at=r[2]) for r in events]
    session["reviewer_latest"] = {e["work_id"]: e for e in session["reviewer_actions"]}
    return session


@lru_cache(maxsize=1)
def _embedder():
    from slr.adapters.embed import Specter2Embedder
    return Specter2Embedder()


def update_project(session_id, account_id, **changes):
    require_owner(session_id, account_id)
    with _connect() as conn:
        payload = json.loads(conn.execute("SELECT payload FROM sessions WHERE id=?", (session_id,)).fetchone()[0])
        payload.update(changes)
        conn.execute("UPDATE sessions SET payload=? WHERE id=?", (json.dumps(payload), session_id))
    return read_session(session_id)


def save_search(session_id, account_id, results):
    previous = read_session(session_id)
    history = previous.get("search_history", [])
    if previous.get("papers"):
        history = [*history, {k: v for k, v in previous.items() if k != "search_history"}]
    return update_project(session_id, account_id, **{**{k: v for k, v in results.items() if k != "session_id"}, "search_history": history, "fulltext": None})


def remove_project(session_id, account_id):
    require_owner(session_id, account_id)
    with _connect() as conn:
        conn.execute("INSERT OR IGNORE INTO removed_projects VALUES (?)", (session_id,))


def save_fulltext(session_id, account_id, result):
    previous = read_session(session_id).get("fulltext") or {}
    papers = {p["work_id"]: p for p in previous.get("papers", [])}
    papers.update({p["work_id"]: p for p in result["papers"]})
    combined = dict(papers=list(papers.values()), n_requested=len(papers), n_with_full_text=sum(bool(p.get("found")) for p in papers.values()))
    update_project(session_id, account_id, fulltext=combined)
    return combined
