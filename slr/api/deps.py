"""Paths and the per-request database connection.

Same defaults every config in this project uses (``data/slr.db``, ``runs``,
``prompts``), overridable by environment variable so tests can point the API
at a throwaway database instead of the real one.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from slr.db import connect

DB_PATH = Path(os.environ.get("SLR_DB_PATH", "data/slr.db"))
RUNS_DIR = Path(os.environ.get("SLR_RUNS_DIR", "runs"))
PROMPTS_DIR = Path(os.environ.get("SLR_PROMPTS_DIR", "prompts"))

MAX_LIVE_SCREEN = 15  # a live query is answered in a browser session, not left running


def get_conn() -> sqlite3.Connection:
    # check_same_thread=False: this connection is opened by this dependency's
    # own threadpool dispatch and used by the route body's separate one --
    # see the note on slr.db.connect.
    conn = connect(DB_PATH, check_same_thread=False)
    try:
        yield conn
    finally:
        conn.close()
