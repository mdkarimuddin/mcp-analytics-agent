from dbagent import cli, db, tools


def test_demo_pending_approve_restore_flow(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DBAGENT_DB", str(tmp_path / "r.db"))
    monkeypatch.setenv("DBAGENT_META", str(tmp_path / "m.db"))
    cli.main(["demo"])
    assert db.data_path().exists()
    p = tools.propose_change("UPDATE prod SET list_price = 3.0 WHERE prod_id = 4", "test")
    capsys.readouterr()
    cli.main(["pending"])
    assert "prod_id = 4" in capsys.readouterr().out
    cli.main(["approve", str(p["proposal_id"])])
    assert "approved" in capsys.readouterr().out
    cli.main(["restore", str(p["proposal_id"])])
    assert "restored" in capsys.readouterr().out


def test_reject_via_cli(database, capsys):
    p = tools.propose_change("UPDATE prod SET list_price = 3.0 WHERE prod_id = 4")
    cli.main(["reject", str(p["proposal_id"])])
    assert "rejected" in capsys.readouterr().out
