"""
Database: document storage + change log for versioned sync.
"""

import os
import sqlite3
import json
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "sync_server.db"


def _get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS documents (
            source TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS change_log (
            version INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            action TEXT NOT NULL CHECK(action IN ('upsert', 'delete')),
            content TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)
    conn.commit()
    conn.close()


def current_version() -> int:
    conn = _get_conn()
    row = conn.execute("SELECT COALESCE(MAX(version), 0) AS v FROM change_log").fetchone()
    conn.close()
    return row["v"]


def get_documents() -> list[dict]:
    conn = _get_conn()
    rows = conn.execute("SELECT source, content FROM documents ORDER BY source").fetchall()
    conn.close()
    return [{"source": r["source"], "content": r["content"]} for r in rows]


def get_changes(since: int) -> dict:
    """Return {upsert: [...], deleted_sources: [...], version: int} for changes after `since`."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT source, action, content FROM change_log WHERE version > ? ORDER BY version",
        (since,),
    ).fetchall()
    conn.close()

    upsert = []
    deleted = []
    seen = set()
    for r in rows:
        if r["action"] == "upsert":
            upsert.append({"source": r["source"], "content": r["content"]})
            seen.add(r["source"])
        elif r["action"] == "delete":
            # Remove any prior upsert of same source in this batch
            upsert = [u for u in upsert if u["source"] != r["source"]]
            if r["source"] not in seen:
                deleted.append(r["source"])
            seen.add(r["source"])

    return {
        "version": current_version(),
        "upsert": upsert,
        "deleted_sources": deleted,
    }


def upsert_document(source: str, content: str) -> int:
    """Add or update a document. Returns new version number."""
    conn = _get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO documents (source, content, updated_at) VALUES (?, ?, datetime('now'))",
        (source, content),
    )
    conn.execute(
        "INSERT INTO change_log (source, action, content) VALUES (?, 'upsert', ?)",
        (source, content),
    )
    conn.commit()
    v = conn.execute("SELECT last_insert_rowid() AS v").fetchone()["v"]
    conn.close()
    return v


def delete_document(source: str) -> int:
    """Delete a document. Returns new version number, or 0 if not found."""
    conn = _get_conn()
    existing = conn.execute("SELECT 1 FROM documents WHERE source = ?", (source,)).fetchone()
    if not existing:
        conn.close()
        return 0
    conn.execute("DELETE FROM documents WHERE source = ?", (source,))
    conn.execute(
        "INSERT INTO change_log (source, action, content) VALUES (?, 'delete', NULL)",
        (source,),
    )
    conn.commit()
    v = conn.execute("SELECT last_insert_rowid() AS v").fetchone()["v"]
    conn.close()
    return v


def get_document_content(source: str) -> str | None:
    conn = _get_conn()
    row = conn.execute("SELECT content FROM documents WHERE source = ?", (source,)).fetchone()
    conn.close()
    return row["content"] if row else None


def seed_from_dir(data_dir: str | None = None):
    """If the database is empty, load all .txt files from data_dir as seed documents."""
    if data_dir is None:
        data_dir = str(ROOT / "data")
    if not os.path.isdir(data_dir):
        return

    conn = _get_conn()
    existing = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    conn.close()
    if existing > 0:
        return

    for fname in sorted(os.listdir(data_dir)):
        if fname.endswith(".txt"):
            fpath = os.path.join(data_dir, fname)
            with open(fpath, encoding="utf-8") as f:
                content = f.read().strip()
            if content:
                upsert_document(fname, content)


# Initialize on import
init_db()
seed_from_dir()
