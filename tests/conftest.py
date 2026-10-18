import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dbagent import demo_data


@pytest.fixture()
def database(tmp_path, monkeypatch):
    path = tmp_path / "retail.db"
    monkeypatch.setenv("DBAGENT_DB", str(path))
    monkeypatch.setenv("DBAGENT_META", str(tmp_path / "meta.db"))
    demo_data.build(path)
    return path
