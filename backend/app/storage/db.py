"""SQLite 连接、迁移与短事务。

- 每个连接 foreign_keys=ON、busy_timeout=5000，本地磁盘开 WAL。
- 迁移在启动时执行，幂等；迁移版本写进 ``schema_migrations``。
- SSE 读取不持有事务：写事件用独立短事务立即提交。
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]          # backend/
MIGRATIONS = ROOT / "migrations"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def db_path() -> Path:
    configured = os.environ.get("DATA_DIR")
    base = Path(configured) if configured else ROOT.parent / "data"
    base.mkdir(parents=True, exist_ok=True)
    return base / "evidence_chain.sqlite3"


_local = threading.local()


def connect() -> sqlite3.Connection:
    path = db_path()
    conn = sqlite3.connect(path, timeout=30, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def get_conn() -> sqlite3.Connection:
    """线程内复用连接（uvicorn 单 worker + 线程池）。"""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = connect()
        _local.conn = conn
    return conn


@contextmanager
def tx(conn: sqlite3.Connection | None = None):
    c = conn or get_conn()
    c.execute("BEGIN IMMEDIATE")
    try:
        yield c
        c.execute("COMMIT")
    except Exception:
        c.execute("ROLLBACK")
        raise


def init_db() -> dict[str, Any]:
    conn = get_conn()
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    applied: list[str] = []
    for path in sorted(MIGRATIONS.glob("*.sql")):
        version = path.stem
        row = conn.execute("SELECT 1 FROM schema_migrations WHERE version = ?", (version,)).fetchone()
        if row:
            continue
        script = path.read_text(encoding="utf-8")
        conn.executescript(script)
        conn.execute("INSERT INTO schema_migrations(version, applied_at) VALUES (?,?)", (version, utcnow()))
        applied.append(version)
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    return {"applied": applied, "integrity": integrity, "tables": tables, "path": str(db_path())}


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=True, default=str)


def loads(text: str | None, default: Any = None) -> Any:
    if text is None or text == "":
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default


def rows(cur: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(r) for r in cur]


def one(cur) -> dict[str, Any] | None:
    row = cur.fetchone() if hasattr(cur, "fetchone") else None
    return dict(row) if row else None
