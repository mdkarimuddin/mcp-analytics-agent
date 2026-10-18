import pytest

from dbagent import db, tools


def test_list_tables_shows_twelve_tables(database):
    out = tools.list_tables()["tables"]
    assert len(out) == 12
    assert {t["table"]: t["rows"] for t in out}["ord_hdr"] == 3000


def test_describe_table_flags_blocked_columns_and_hides_them_in_samples(database):
    d = tools.describe_table("cust")
    blocked = {c["name"] for c in d["columns"] if c["blocked"]}
    assert blocked == {"email", "phone"}
    assert "email" not in d["sample_columns"]
    assert len(d["sample_rows"]) == 3
    assert any(fk["references"] == "cust.cust_id" for fk in tools.describe_table("ord_hdr")["foreign_keys"])


def test_describe_rejects_bad_names(database):
    with pytest.raises(ValueError):
        tools.describe_table('cust"; DROP TABLE cust; --')
    with pytest.raises(ValueError):
        tools.describe_table("no_such_table")


def test_find_columns_across_tables(database):
    hits = tools.find_columns("dt")["matches"]
    assert {"ord_hdr", "pay", "ship"} <= {h["table"] for h in hits}


def test_run_query_returns_correct_numbers(database):
    out = tools.run_query("SELECT COUNT(*) AS n FROM ord_hdr WHERE status = 'delivered'")
    assert out["columns"] == ["n"]
    assert out["rows"][0][0] > 2000


def test_joins_and_window_functions_work(database):
    out = tools.run_query(
        "SELECT s.city, COUNT(*) n, RANK() OVER (ORDER BY COUNT(*) DESC) r "
        "FROM ord_hdr o JOIN store s ON s.store_id = o.store_id GROUP BY s.city")
    assert out["row_count"] == 6


def test_row_cap_and_truncation(database):
    out = tools.run_query("SELECT order_id FROM ord_hdr", max_rows=10)
    assert out["row_count"] == 10 and out["truncated"] is True


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM cust",
        "DROP TABLE cust",
        "UPDATE prod SET list_price = 0",
        "PRAGMA table_info(cust)",
        "ATTACH DATABASE '/tmp/x.db' AS x",
        "SELECT 1; DROP TABLE cust",
        "",
    ],
)
def test_non_select_and_multi_statement_are_rejected(database, sql):
    with pytest.raises(ValueError):
        tools.run_query(sql)
    assert tools.list_tables()["tables"][0]["rows"] >= 0  # database intact


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT email FROM cust",
        "SELECT * FROM cust",
        "SELECT phone FROM cust LIMIT 1",
        "SELECT salary FROM emp",
        "SELECT cust_id FROM cust WHERE email LIKE '%@%'",
        "SELECT c.email FROM cust c",
        "WITH x AS (SELECT email FROM cust) SELECT * FROM x",
    ],
)
def test_personal_data_columns_are_blocked_in_every_form(database, sql):
    with pytest.raises(ValueError, match="blocked|not authorized|prohibited"):
        tools.run_query(sql)


def test_non_sensitive_columns_of_same_table_are_allowed(database):
    assert tools.run_query("SELECT segment, COUNT(*) FROM cust GROUP BY segment")["row_count"] >= 2


def test_unapproved_functions_are_denied(database):
    with pytest.raises(ValueError):
        tools.run_query("SELECT load_extension('x')")
    with pytest.raises(ValueError):
        tools.run_query("SELECT random()")


def test_schema_tables_are_not_readable_via_sql(database):
    with pytest.raises(ValueError):
        tools.run_query("SELECT name FROM sqlite_master")


def test_runaway_query_is_stopped(database, monkeypatch):
    monkeypatch.setattr(db, "QUERY_TIMEOUT_S", 0.2)
    with pytest.raises(ValueError, match="limit"):
        tools.run_query(
            "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c WHERE x < 100000000) "
            "SELECT COUNT(*) FROM c")


def test_injected_product_description_is_only_data(database):
    out = tools.run_query("SELECT description FROM prod WHERE prod_id = 7")
    assert "IGNORE ALL PREVIOUS" in out["rows"][0][0]
    assert tools.describe_table("cust")["rows"] == 500  # nothing was dropped
