import sqlite3

import pytest

from dbagent import db, tools


def price(pid=1):
    c = sqlite3.connect(db.data_path())
    try:
        return c.execute("SELECT list_price FROM prod WHERE prod_id=?", (pid,)).fetchone()[0]
    finally:
        c.close()


def test_propose_does_not_change_data(database):
    before = price()
    out = tools.propose_change("UPDATE prod SET list_price = 1.0 WHERE prod_id = 1", "price fix")
    assert out["status"] == "pending_human_approval" and out["rows_that_would_change"] == 1
    assert price() == before
    assert len(tools.list_pending()) == 1


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM cust WHERE cust_id = 1",                 # table not writable
        "UPDATE emp SET salary = 0 WHERE emp_id = 1",          # not writable + sensitive
        "UPDATE prod SET list_price = 1",                      # no WHERE
        "UPDATE ord_hdr SET status = 'new' WHERE order_id > 0",  # more than 100 rows
        "DROP TABLE prod",
        "SELECT 1",
        "UPDATE prod SET list_price = 1 WHERE prod_id = 1; DELETE FROM prod WHERE 1=1",
    ],
)
def test_unsafe_proposals_are_rejected(database, sql):
    with pytest.raises(ValueError):
        tools.propose_change(sql)
    assert tools.list_pending() == []


def test_approve_applies_change_and_takes_snapshot(database):
    original = price()
    p = tools.propose_change("UPDATE prod SET list_price = 1.0 WHERE prod_id = 1")
    out = tools.approve(p["proposal_id"])
    assert out["rows_changed"] == 1
    assert price() == 1.0
    assert original != 1.0


def test_restore_returns_database_to_snapshot(database):
    original = price()
    p = tools.propose_change("UPDATE prod SET list_price = 1.0 WHERE prod_id = 1")
    tools.approve(p["proposal_id"])
    tools.restore(p["proposal_id"])
    assert price() == original


def test_approve_aborts_if_row_count_drifted(database):
    p = tools.propose_change("UPDATE ord_hdr SET status = 'new' WHERE status = 'shipped' AND order_id < 40")
    c = sqlite3.connect(db.data_path())
    c.execute("UPDATE ord_hdr SET status = 'delivered' WHERE order_id < 40 AND status = 'shipped'")
    c.commit()
    c.close()
    with pytest.raises(ValueError, match="row count changed"):
        tools.approve(p["proposal_id"])


def test_cannot_approve_twice_or_restore_unapproved(database):
    p = tools.propose_change("UPDATE prod SET list_price = 2.0 WHERE prod_id = 2")
    with pytest.raises(ValueError):
        tools.restore(p["proposal_id"])
    tools.approve(p["proposal_id"])
    with pytest.raises(ValueError):
        tools.approve(p["proposal_id"])


def test_reject_leaves_data_unchanged(database):
    before = price(3)
    p = tools.propose_change("UPDATE prod SET list_price = 2.0 WHERE prod_id = 3")
    tools.reject(p["proposal_id"])
    assert price(3) == before


def test_audit_log_records_actors(database):
    tools.run_query("SELECT COUNT(*) FROM cust")
    p = tools.propose_change("UPDATE prod SET list_price = 2.0 WHERE prod_id = 2")
    tools.approve(p["proposal_id"])
    m = db.meta()
    pairs = {(r["actor"], r["tool"]) for r in m.execute("SELECT actor, tool FROM audit_log")}
    m.close()
    assert {("agent", "run_query"), ("agent", "propose_change"), ("human", "approve")} <= pairs
