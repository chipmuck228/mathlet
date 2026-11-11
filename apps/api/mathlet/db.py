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
        # Additive, idempotent migration: preserve all existing 0.1 records.
        c.executescript("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
          version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS plans (
          id TEXT PRIMARY KEY, title TEXT NOT NULL, payload TEXT NOT NULL,
          revision INTEGER NOT NULL DEFAULT 1, confirmed_revision INTEGER,
          reviewer TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS plan_draft_links (
          plan_id TEXT NOT NULL REFERENCES plans(id), unit_id TEXT NOT NULL,
          draft_id TEXT NOT NULL REFERENCES drafts(id), plan_revision INTEGER NOT NULL,
          PRIMARY KEY(plan_id,unit_id)
        );
        """)
        c.execute("INSERT OR IGNORE INTO schema_migrations VALUES(1,?)", (now(),))
        columns = {r[1] for r in c.execute("PRAGMA table_info(blocks)")}
        if "original_content" not in columns:
            c.execute("ALTER TABLE blocks ADD COLUMN original_content TEXT NOT NULL DEFAULT '[]'")
        c.execute("""CREATE TABLE IF NOT EXISTS formula_candidates (
          block_id TEXT PRIMARY KEY REFERENCES blocks(id), base_revision INTEGER NOT NULL,
          text TEXT NOT NULL, original_content TEXT NOT NULL, created_at TEXT NOT NULL
        )""")
        if "original_text" not in columns:
            c.execute("ALTER TABLE blocks ADD COLUMN original_text TEXT")
        from .knowledge_models import init_knowledge
        init_knowledge(c)
        c.execute("INSERT OR IGNORE INTO schema_migrations VALUES(5,?)", (now(),))
        c.execute("INSERT OR IGNORE INTO schema_migrations VALUES(4,?)", (now(),))
        c.execute("INSERT OR IGNORE INTO schema_migrations VALUES(3,?)", (now(),))
        c.execute("INSERT OR IGNORE INTO schema_migrations VALUES(2,?)", (now(),))


def block_json(row):
    from .formulas import parts_from_text
    result = dict(row)
    for key in ("assets", "warnings"):
        result[key] = json.loads(result[key])
    result["verified"] = bool(result["verified"])
    result["original_content"] = json.loads(result.get("original_content", "[]"))
    result["content"] = parts_from_text(result["text"])
    return result


def draft_json(row):
    result = dict(row)
    result["source_ids"] = json.loads(result["source_ids"])
    result["approved"] = result["approved_revision"] == result["revision"]
    return result
