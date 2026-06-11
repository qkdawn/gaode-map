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


def test_ai_db_initializes_document_pipeline_schema(monkeypatch):
    called = []

    monkeypatch.setattr(ai_database, "_engine", None)
    monkeypatch.setattr(ai_database.settings, "postgres_database_url", "sqlite:///:memory:")
    monkeypatch.setattr(ai_database, "_ensure_pgvector_extension", lambda bind: called.append("vector"))
    monkeypatch.setattr(AiBase.metadata, "create_all", lambda bind: called.append(sorted(AiBase.metadata.tables)))

    ai_database.init_ai_db()

    assert called == ["vector", [
        "document_blocks",
        "documents",
        "evidence_chunks",
        "evidence_embeddings",
        "jobs",
    ]]


def test_ai_db_enables_pgvector_for_postgres(monkeypatch):
    executed = []

    class FakeUrl:
        drivername = "postgresql+psycopg"

    class FakeConnection:
        def execute(self, statement):
            executed.append(str(statement))

    class FakeBegin:
        def __enter__(self):
            return FakeConnection()

        def __exit__(self, *_args):
            return False

    class FakeEngine:
        url = "postgresql+psycopg://example/db"

        def begin(self):
            return FakeBegin()

    monkeypatch.setattr(ai_database, "make_url", lambda _url: FakeUrl())

    ai_database._ensure_pgvector_extension(FakeEngine())

    assert executed == ["CREATE EXTENSION IF NOT EXISTS vector"]


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
