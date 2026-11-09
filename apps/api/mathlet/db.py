import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[3]


def data_dir() -> Path:
    path = Path(os.environ.get("MATHLET_DATA_DIR", ROOT / "data")).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def uid() -> str:
    return uuid4().hex


@contextmanager
def connect():
    conn = sqlite3.connect(data_dir() / "mathlet.sqlite3", timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with connect() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript("""
        CREATE TABLE IF NOT EXISTS documents (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL,
          category TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS blocks (
          id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id),
          ordinal INTEGER NOT NULL, locator TEXT NOT NULL, text TEXT NOT NULL,
          preview TEXT NOT NULL, assets TEXT NOT NULL, warnings TEXT NOT NULL,
          verified INTEGER NOT NULL DEFAULT 0, revision INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS jobs (
          id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id),
          kind TEXT NOT NULL, status TEXT NOT NULL, message TEXT NOT NULL,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS drafts (
          id TEXT PRIMARY KEY, title TEXT NOT NULL, content TEXT NOT NULL,
          source_ids TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
          approved_revision INTEGER, reviewer TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS comments (
          id TEXT PRIMARY KEY, draft_id TEXT NOT NULL REFERENCES drafts(id),
          revision INTEGER NOT NULL, author TEXT NOT NULL, body TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS releases (
          id TEXT PRIMARY KEY, draft_id TEXT NOT NULL REFERENCES drafts(id),
          revision INTEGER NOT NULL, snapshot TEXT NOT NULL, created_at TEXT NOT NULL
        );
        """)


def block_json(row):
    result = dict(row)
    for key in ("assets", "warnings"):
        result[key] = json.loads(result[key])
    result["verified"] = bool(result["verified"])
    return result


def draft_json(row):
    result = dict(row)
    result["source_ids"] = json.loads(result["source_ids"])
    result["approved"] = result["approved_revision"] == result["revision"]
    return result
