"""Tool implementations: schema exploration, validated read-only SQL, change proposals.

Safety layers for reads: single statement, SELECT/WITH only, read-only connection,
SQLite authorizer (function allow-list, PII columns blocked), row cap, time limit.
Writes are never executed by the agent: it can only propose; a human approves.
"""

from __future__ import annotations

import re
import sqlite3
import time
from pathlib import Path

from . import db

_TABLE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _check_table(name: str) -> str:
    if not _TABLE_RE.match(name or ""):
        raise ValueError("invalid table name")
    return name


def list_tables() -> dict:
    """All tables with row counts."""
    conn = db.connect_unrestricted_ro()
    try:
        names = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        tables = [{"table": n, "rows": conn.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0]} for n in names]
    finally:
        conn.close()
    db.audit("agent", "list_tables", {}, f"{len(tables)} tables")
    return {"tables": tables}


def describe_table(table: str) -> dict:
    """Columns (with PII flags), foreign keys, row count and 3 sample rows without sensitive columns."""
    _check_table(table)
    conn = db.connect_unrestricted_ro()
    try:
        cols = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
        if not cols:
            raise ValueError(f"unknown table: {table}")
        fks = [{"column": r[3], "references": f"{r[2]}.{r[4]}"}
               for r in conn.execute(f'PRAGMA foreign_key_list("{table}")')]
        columns = [{"name": c[1], "type": c[2], "blocked": db.is_sensitive(table, c[1])} for c in cols]
        safe = [c["name"] for c in columns if not c["blocked"]]
        count = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        sample = [list(r) for r in conn.execute(
            "SELECT " + ", ".join(f'"{c}"' for c in safe) + f' FROM "{table}" LIMIT 3')]
    finally:
        conn.close()
    db.audit("agent", "describe_table", {"table": table}, "ok")
    return {"table": table, "rows": count, "columns": columns, "foreign_keys": fks,
            "sample_columns": safe, "sample_rows": sample}


def find_columns(keyword: str) -> dict:
    """Find columns whose name contains a keyword, across all tables."""
    keyword = (keyword or "").strip().lower()
    if not 1 <= len(keyword) <= 40:
        raise ValueError("keyword must be 1-40 characters")
    conn = db.connect_unrestricted_ro()
    hits = []
    try:
        for (t,) in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall():
            for c in conn.execute(f'PRAGMA table_info("{t}")'):
                if keyword in c[1].lower():
                    hits.append({"table": t, "column": c[1], "type": c[2], "blocked": db.is_sensitive(t, c[1])})
    finally:
        conn.close()
    db.audit("agent", "find_columns", {"keyword": keyword}, f"{len(hits)} hits")
    return {"matches": hits}


def run_query(sql: str, max_rows: int = 50) -> dict:
    """Run one read-only SELECT (or WITH ... SELECT). Result is capped and time-limited."""
    sql = (sql or "").strip().rstrip(";").strip()
    max_rows = max(1, min(int(max_rows), db.MAX_ROWS))
    if not sql or len(sql) > 4000:
        raise ValueError("sql must be 1-4000 characters")
    if not re.match(r"^(select|with)\b", sql, re.IGNORECASE):
        raise ValueError("only SELECT or WITH ... SELECT statements are allowed")
    conn = db.connect_ro()
    start = time.monotonic()
    try:
        cur = conn.execute(sql)
        cols = [d[0] for d in cur.description or []]
        rows = cur.fetchmany(max_rows + 1)
    except (sqlite3.Error, sqlite3.Warning) as exc:
        db.audit("agent", "run_query", {"sql": sql}, f"rejected: {exc}")
        msg = str(exc)
        if "not authorized" in msg or "prohibited" in msg:
            msg += " (blocked: personal data columns, unapproved functions or non-SELECT operations)"
        if "interrupted" in msg:
            msg = f"query exceeded {db.QUERY_TIMEOUT_S:.0f}s limit"
        raise ValueError(msg) from exc
    finally:
        conn.close()
    truncated = len(rows) > max_rows
    rows = [list(r) for r in rows[:max_rows]]
    db.audit("agent", "run_query", {"sql": sql}, f"{len(rows)} rows")
    return {"columns": cols, "rows": rows, "row_count": len(rows), "truncated": truncated,
            "elapsed_ms": round((time.monotonic() - start) * 1000)}


def _dry_run(sql: str) -> int:
    """Execute inside a transaction under the write authorizer, count affected rows, roll back."""
    conn = db.connect_write()
    try:
        conn.execute("BEGIN")
        conn.set_authorizer(db._write_authorizer)
        try:
            cur = conn.execute(sql)
            n = cur.rowcount
        finally:
            conn.set_authorizer(db.allow_all)
            conn.execute("ROLLBACK")
    finally:
        conn.close()
    return n


def _validate_change(sql: str) -> str:
    sql = (sql or "").strip().rstrip(";").strip()
    if not 1 <= len(sql) <= 2000:
        raise ValueError("sql must be 1-2000 characters")
    if not re.match(r"^(update|insert|delete)\b", sql, re.IGNORECASE):
        raise ValueError("only UPDATE, INSERT or DELETE statements can be proposed")
    if re.match(r"^(update|delete)\b", sql, re.IGNORECASE) and not re.search(r"\bwhere\b", sql, re.IGNORECASE):
        raise ValueError("UPDATE and DELETE need a WHERE clause")
    return sql


def propose_change(sql: str, reason: str = "") -> dict:
    """Validate and dry-run a data change. Nothing is applied; a human must approve it."""
    sql = _validate_change(sql)
    try:
        n = _dry_run(sql)
    except (sqlite3.Error, sqlite3.Warning) as exc:
        db.audit("agent", "propose_change", {"sql": sql}, f"rejected: {exc}")
        raise ValueError(f"change rejected: {exc} (writable tables: {sorted(db.WRITABLE_TABLES)})") from exc
    if n < 0 or n > db.MAX_AFFECTED_ROWS:
        db.audit("agent", "propose_change", {"sql": sql}, f"rejected: {n} rows")
        raise ValueError(f"change affects {n} rows; limit is {db.MAX_AFFECTED_ROWS}")
    conn = db.meta()
    try:
        cur = conn.execute(
            "INSERT INTO proposals (sql, reason, preview_rows, status, created_at) VALUES (?,?,?,'pending',?)",
            (sql, reason[:300], n, db.now_iso()))
        conn.commit()
        pid = cur.lastrowid
    finally:
        conn.close()
    db.audit("agent", "propose_change", {"sql": sql, "reason": reason}, f"proposal {pid}, {n} rows")
    return {"proposal_id": pid, "status": "pending_human_approval", "rows_that_would_change": n,
            "message": "Nothing was changed. A human must run `dbagent approve <id>`."}


# ---- Human-only operations (CLI; never exposed through MCP) ----

def list_pending() -> list[dict]:
    conn = db.meta()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT id, sql, reason, preview_rows FROM proposals WHERE status='pending' ORDER BY id")]
    finally:
        conn.close()


def approve(proposal_id: int) -> dict:
    """Snapshot the database, apply the change in a transaction, verify the row count, commit."""
    m = db.meta()
    try:
        p = m.execute("SELECT * FROM proposals WHERE id=?", (proposal_id,)).fetchone()
        if p is None or p["status"] != "pending":
            raise ValueError("proposal not found or not pending")
        sql = _validate_change(p["sql"])
        snap_dir = db.snapshot_dir()
        snap_dir.mkdir(parents=True, exist_ok=True)
        snap = snap_dir / f"before_proposal_{proposal_id}.db"
        src = sqlite3.connect(db.data_path())
        dst = sqlite3.connect(snap)
        src.backup(dst)
        dst.close()
        src.close()
        conn = db.connect_write()
        try:
            conn.execute("BEGIN")
            conn.set_authorizer(db._write_authorizer)
            try:
                n = conn.execute(sql).rowcount
                if n != p["preview_rows"]:
                    raise ValueError(f"row count changed since preview ({p['preview_rows']} -> {n}); aborted")
                conn.set_authorizer(db.allow_all)
                conn.execute("COMMIT")
            except Exception:
                conn.set_authorizer(db.allow_all)
                conn.execute("ROLLBACK")
                raise
        finally:
            conn.close()
        m.execute("UPDATE proposals SET status='approved', snapshot=?, decided_at=? WHERE id=?",
                  (str(snap), db.now_iso(), proposal_id))
        m.commit()
    finally:
        m.close()
    db.audit("human", "approve", {"proposal_id": proposal_id}, f"applied {n} rows")
    return {"proposal_id": proposal_id, "status": "approved", "rows_changed": n, "snapshot": str(snap)}


def reject(proposal_id: int) -> dict:
    m = db.meta()
    try:
        cur = m.execute("UPDATE proposals SET status='rejected', decided_at=? WHERE id=? AND status='pending'",
                        (db.now_iso(), proposal_id))
        m.commit()
        if cur.rowcount == 0:
            raise ValueError("proposal not found or not pending")
    finally:
        m.close()
    db.audit("human", "reject", {"proposal_id": proposal_id}, "rejected")
    return {"proposal_id": proposal_id, "status": "rejected"}


def restore(proposal_id: int) -> dict:
    """Undo an approved change by restoring the pre-change snapshot (discards later changes too)."""
    m = db.meta()
    try:
        p = m.execute("SELECT * FROM proposals WHERE id=?", (proposal_id,)).fetchone()
        if p is None or p["status"] != "approved" or not p["snapshot"] or not Path(p["snapshot"]).exists():
            raise ValueError("only approved changes with an existing snapshot can be restored")
        src = sqlite3.connect(p["snapshot"])
        dst = sqlite3.connect(db.data_path())
        src.backup(dst)
        dst.close()
        src.close()
        m.execute("UPDATE proposals SET status='restored', decided_at=? WHERE id=?", (db.now_iso(), proposal_id))
        m.commit()
    finally:
        m.close()
    db.audit("human", "restore", {"proposal_id": proposal_id}, "snapshot restored")
    return {"proposal_id": proposal_id, "status": "restored"}
