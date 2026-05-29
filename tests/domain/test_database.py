from types import SimpleNamespace

import store.database as database


def test_mysql_engine_uses_short_lived_connections(monkeypatch):
    captured = {}

    def fake_create_engine(uri, **kwargs):
        captured["uri"] = uri
        captured["kwargs"] = kwargs
        return SimpleNamespace()

    monkeypatch.setattr(database, "create_engine", fake_create_engine)

    database._build_engine("mysql+pymysql://user:password@example.test:13306/gaode_deploy?charset=utf8mb4")

    assert captured["uri"].startswith("mysql+pymysql://")
    assert captured["kwargs"]["pool_pre_ping"] is True
    assert captured["kwargs"]["pool_recycle"] == 300
    assert captured["kwargs"]["pool_size"] == 5
    assert captured["kwargs"]["max_overflow"] == 5
    assert captured["kwargs"]["connect_args"] == {
        "connect_timeout": 5,
        "read_timeout": 30,
        "write_timeout": 30,
    }
