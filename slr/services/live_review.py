"""Ad-hoc review records, deliberately isolated from benchmark tables."""
from datetime import datetime, timezone
from functools import lru_cache
import json
from pathlib import Path
import sqlite3
from threading import Lock
from uuid import uuid4

import numpy as np
from slr.services.verify import verify_span

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


def record_action(session_id, work_id, action):
    session = read_session(session_id)
    paper = next((p for p in session["papers"] if p["work_id"] == work_id), None)
    if paper is None:
        raise KeyError("Paper not found in this session")
    coded = bool(action.get("technique") or action.get("domain"))
    if coded and not (action.get("technique") and action.get("domain")):
        raise ValueError("Supply both technique and domain to code a paper")
    if coded and not verify_span(action.get("quote"), paper.get("abstract")).verified:
        raise ValueError("Coding evidence must match the stored abstract")
    with _connect() as conn:
        conn.execute("INSERT INTO actions(session_id,work_id,payload,created_at) VALUES (?,?,?,?)",
                     (session_id, work_id, json.dumps(action), datetime.now(timezone.utc).isoformat()))
    return read_session(session_id)


def coverage(session):
    rows = []
    for paper in session["papers"]:
        action = session["reviewer_latest"].get(paper["work_id"], {})
        if action.get("decision") == "exclude" or not action.get("technique") or not action.get("domain"):
            continue
        gap = paper.get("gap") or {}
        gap_quote = gap.get("quote") if gap.get("status") == "gap_stated" else ""
        if not verify_span(gap_quote, paper.get("abstract")).verified:
            gap_quote = ""
        rows.append(dict(work_id=paper["work_id"], title=paper.get("title"), source_url=paper.get("source_url"),
                         technique=action["technique"], domain=action["domain"], quote=action["quote"], gap_quote=gap_quote))
    techniques = sorted({r["technique"] for r in rows})
    domains = sorted({r["domain"] for r in rows})
    cells = [dict(technique=t, domain=d, papers=sum(r["technique"] == t and r["domain"] == d for r in rows),
                  gap_statements=sum(r["technique"] == t and r["domain"] == d and bool(r["gap_quote"]) for r in rows))
             for t in techniques for d in domains]
    return dict(cells=cells, evidence=rows, n_coded=len(rows))


@lru_cache(maxsize=1)
def _embedder():
    from slr.adapters.embed import Specter2Embedder
    return Specter2Embedder()


def semantic_map(session_id, embedder=None):
    session = read_session(session_id)
    with _connect() as conn:
        cached = conn.execute("SELECT payload FROM maps WHERE session_id=?", (session_id,)).fetchone()
    if cached:
        return json.loads(cached[0])
    papers = [p for p in session["papers"] if p.get("abstract")]
    if len(papers) < 3:
        raise ValueError("At least three papers with abstracts are needed for a two-dimensional map")
    texts = [(p.get("title") or "") + " [SEP] " + p["abstract"] for p in papers]
    with EMBED_LOCK:
        vectors = np.asarray((embedder or _embedder()).encode(texts), dtype=float)
    if vectors.ndim != 2 or vectors.shape[0] != len(papers) or not np.isfinite(vectors).all():
        raise ValueError("Embedding model returned invalid vectors")
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    vectors = vectors / np.maximum(norms, 1e-12)
    centered = vectors - vectors.mean(axis=0)
    u, s, _ = np.linalg.svd(centered, full_matrices=False)
    xy = u[:, :2] * s[:2]
    if xy.shape[1] < 2:
        raise ValueError("Embeddings do not support a two-dimensional map")
    variance = float((s[:2] ** 2).sum() / (s ** 2).sum()) if (s ** 2).sum() else 0.0
    result = dict(model="SPECTER2 proximity", projection="PCA of normalized embeddings", variance_explained=variance,
                  points=[dict(work_id=p["work_id"], title=p.get("title"), source_url=p.get("source_url"),
                               x=float(xy[i, 0]), y=float(xy[i, 1])) for i, p in enumerate(papers)])
    with _connect() as conn:
        conn.execute("INSERT OR REPLACE INTO maps VALUES (?,?)", (session_id, json.dumps(result)))
    return result


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
