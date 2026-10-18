"""Connections, the SQLite authorizer (the main safety control) and the metadata store."""

from __future__ import annotations

import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

# Columns the agent may never read or change (personal data and pay).
SENSITIVE: frozenset[tuple[str, str]] = frozenset(
    {
        ("cust", "email"), ("cust", "phone"),
        ("emp", "email"), ("emp", "salary"),
    }
)
# Tables where an approved change may be applied.
WRITABLE_TABLES = frozenset({"prod", "ord_hdr", "ship"})
MAX_AFFECTED_ROWS = 100
MAX_ROWS = 100
QUERY_TIMEOUT_S = 3.0

ALLOWED_FUNCTIONS = frozenset(
    {
        "count", "sum", "avg", "min", "max", "total", "round", "abs", "coalesce", "ifnull", "nullif",
        "iif", "length", "lower", "upper", "substr", "substring", "trim", "ltrim", "rtrim", "instr",
        "replace", "printf", "cast", "typeof", "date", "datetime", "strftime", "julianday", "like",
        "glob", "group_concat", "row_number", "rank", "dense_rank", "lag", "lead", "ntile",
        "first_value", "last_value", "sign", "likelihood", "unlikely",
    }
)


def data_path() -> Path:
    return Path(os.environ.get("DBAGENT_DB", "data/retail.db"))


def meta_path() -> Path:
    return Path(os.environ.get("DBAGENT_META", str(data_path().with_name("meta.db"))))


def snapshot_dir() -> Path:
    return data_path().with_name("snapshots")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_authorizer(action, arg1, arg2, dbname, source):
    if action == sqlite3.SQLITE_SELECT or action == sqlite3.SQLITE_RECURSIVE:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_READ:
        if str(arg1).lower().startswith("sqlite_"):
            return sqlite3.SQLITE_DENY
        if (str(arg1).lower(), str(arg2).lower()) in SENSITIVE:
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_FUNCTION:
        return sqlite3.SQLITE_OK if str(arg2).lower() in ALLOWED_FUNCTIONS else sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_DENY


def _write_authorizer(action, arg1, arg2, dbname, source):
    if action in (sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_INSERT, sqlite3.SQLITE_DELETE):
        table = str(arg1).lower()
        if table not in WRITABLE_TABLES:
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_UPDATE and (table, str(arg2).lower()) in SENSITIVE:
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    return _read_authorizer(action, arg1, arg2, dbname, source)


def allow_all(action, arg1, arg2, dbname, source):
    """Permissive authorizer: set_authorizer(None) misbehaves on Python < 3.11."""
    return sqlite3.SQLITE_OK


def connect_ro() -> sqlite3.Connection:
    """Read-only connection with the read authorizer and a wall-clock query limit."""
    p = data_path().resolve()
    conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    conn.set_authorizer(_read_authorizer)
    deadline = time.monotonic() + QUERY_TIMEOUT_S
    conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10_000)
    return conn


def connect_unrestricted_ro() -> sqlite3.Connection:
    """Read-only, no authorizer: used only for schema metadata (names, types, counts)."""
    return sqlite3.connect(f"file:{data_path().resolve()}?mode=ro", uri=True)


def connect_write() -> sqlite3.Connection:
    """Autocommit connection (manual BEGIN/COMMIT) used only by human-approved changes."""
    conn = sqlite3.connect(data_path(), isolation_level=None)
    return conn


def meta() -> sqlite3.Connection:
    p = meta_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS proposals (
            id INTEGER PRIMARY KEY AUTOINCREMENT, sql TEXT NOT NULL, reason TEXT,
            preview_rows INTEGER, status TEXT NOT NULL DEFAULT 'pending',
            snapshot TEXT, created_at TEXT NOT NULL, decided_at TEXT);
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, actor TEXT NOT NULL,
            tool TEXT NOT NULL, args TEXT, outcome TEXT);
        """
    )
    return conn


def audit(actor: str, tool: str, args: dict, outcome: str) -> None:
    import json

    conn = meta()
    try:
        conn.execute(
            "INSERT INTO audit_log (ts, actor, tool, args, outcome) VALUES (?,?,?,?,?)",
            (now_iso(), actor, tool, json.dumps(args, default=str)[:2000], outcome[:300]),
        )
        conn.commit()
    finally:
        conn.close()


def is_sensitive(table: str, column: str) -> bool:
    return (table.lower(), column.lower()) in SENSITIVE
