from types import SimpleNamespace

from core.config import DEFAULT_DOCUMENT_UPLOAD_DIR, Settings
import store.ai_database as ai_database
from store.ai_models import AiBase
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


def test_init_db_does_not_create_ai_document_schema(monkeypatch):
    called = []

    monkeypatch.setattr(database.Base.metadata, "create_all", lambda bind: called.append("create_all"))
    monkeypatch.setattr(database, "_ensure_agent_sessions_schema", lambda: called.append("agent_sessions"))
    monkeypatch.setattr(database, "_ensure_poi_results_schema", lambda: called.append("poi_results"))
    monkeypatch.setattr(database, "_ensure_analysis_artifacts_schema", lambda: called.append("analysis_artifacts"))

    database.init_db()

    assert called == [
        "create_all",
        "agent_sessions",
        "poi_results",
        "analysis_artifacts",
    ]


def test_poi_results_schema_creates_history_sort_index(monkeypatch):
    statements = []

    class FakeInspector:
        def has_table(self, table_name):
            assert table_name == "poi_results"
            return True

        def get_columns(self, table_name):
            assert table_name == "poi_results"
            return [
                {"name": "id"},
                {"name": "history_id"},
                {"name": "source"},
                {"name": "year"},
                {"name": "poi_data"},
                {"name": "summary"},
                {"name": "created_at"},
            ]

    class FakeConnection:
        def execute(self, statement):
            statements.append(str(statement))

    class FakeBegin:
        def __enter__(self):
            return FakeConnection()

        def __exit__(self, exc_type, exc, tb):
            return False

    fake_engine = SimpleNamespace(begin=lambda: FakeBegin())

    monkeypatch.setattr(database, "_refresh_runtime_config_if_needed", lambda: None)
    monkeypatch.setattr(database, "engine", fake_engine)
    monkeypatch.setattr(database, "inspect", lambda engine: FakeInspector())

    database._ensure_poi_results_schema()

    assert any("ix_poi_results_history_created_id" in statement for statement in statements)


def test_ai_db_initializes_document_pipeline_schema(monkeypatch):
    called = []

    monkeypatch.setattr(ai_database, "_engine", None)
    monkeypatch.setattr(ai_database.settings, "postgres_database_url", "sqlite:///:memory:")
    monkeypatch.setattr(AiBase.metadata, "create_all", lambda bind: called.append(sorted(AiBase.metadata.tables)))

    ai_database.init_ai_db()

    assert called == [[
        "document_blocks",
        "document_index_nodes",
        "documents",
        "jobs",
    ]]


def test_ai_engine_accepts_sqlite_for_tests(monkeypatch):
    captured = {}

    def fake_create_engine(uri, **kwargs):
        captured["uri"] = uri
        captured["kwargs"] = kwargs
        return SimpleNamespace()

    monkeypatch.setattr(ai_database, "create_engine", fake_create_engine)

    ai_database._build_ai_engine("sqlite:///:memory:")

    assert captured["uri"] == "sqlite:///:memory:"
    assert captured["kwargs"]["connect_args"] == {"check_same_thread": False}
    assert "pool_size" not in captured["kwargs"]


def test_empty_document_upload_dir_uses_default(monkeypatch):
    monkeypatch.setenv("DOCUMENT_UPLOAD_DIR", "")
    settings = Settings()

    assert settings.document_upload_dir == str(DEFAULT_DOCUMENT_UPLOAD_DIR.resolve())
