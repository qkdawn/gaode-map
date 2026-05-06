from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.append(str(Path(__file__).resolve().parents[2]))

import store.agent_session_repo as agent_session_repo_module
from store.agent_session_repo import AgentSessionRepo
from store.models import Base


def _install_repo(monkeypatch):
    engine = create_engine("sqlite:///:memory:", future=True)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(agent_session_repo_module, "SessionLocal", testing_session_local)
    return AgentSessionRepo(), testing_session_local


def test_upsert_and_get_agent_session_record(monkeypatch):
    repo, _ = _install_repo(monkeypatch)

    repo.upsert_record(
        "agent-1",
        title="商业分析",
        preview="开始一段新的分析对话",
        status="answered",
        history_id="history-current",
        panel_kind="commercial_summary",
        snapshot={
            "input": "",
            "messages": [{"role": "user", "content": "总结这个区域"}],
            "cards": [{"type": "summary", "title": "概览", "content": "已完成分析", "items": []}],
        },
        title_source="fallback",
    )

    record = repo.get_record("agent-1")

    assert record is not None
    assert record["id"] == "agent-1"
    assert record["title"] == "商业分析"
    assert record["preview"] == "开始一段新的分析对话"
    assert record["status"] == "answered"
    assert record["history_id"] == "history-current"
    assert record["panel_kind"] == "commercial_summary"
    assert record["title_source"] == "fallback"
    assert record["snapshot"]["_meta"]["history_id"] == "history-current"
    assert record["snapshot"]["_meta"]["panel_kind"] == "commercial_summary"
    assert record["snapshot"]["messages"][0]["content"] == "总结这个区域"


def test_list_records_orders_pinned_before_recent(monkeypatch):
    repo, _ = _install_repo(monkeypatch)

    repo.upsert_record(
        "agent-1",
        title="旧会话",
        preview="old",
        status="answered",
        history_id="history-1",
        panel_kind="followup",
        snapshot={"messages": []},
    )
    repo.upsert_record(
        "agent-2",
        title="新会话",
        preview="new",
        status="answered",
        history_id="history-2",
        panel_kind="followup",
        snapshot={"messages": []},
    )
    repo.update_metadata("agent-1", is_pinned=True)

    records = repo.list_records()

    assert [item["id"] for item in records] == ["agent-1", "agent-2"]
    assert records[0]["is_pinned"] is True


def test_delete_missing_agent_session_returns_false(monkeypatch):
    repo, _ = _install_repo(monkeypatch)

    assert repo.delete_record("missing") is False


def test_update_metadata_unpins_session(monkeypatch):
    repo, _ = _install_repo(monkeypatch)

    repo.upsert_record(
        "agent-1",
        title="原始标题",
        preview="preview",
        status="idle",
        history_id="history-1",
        panel_kind="followup",
        snapshot={"messages": []},
        is_pinned=True,
    )

    updated = repo.update_metadata("agent-1", title="手动改名", is_pinned=False)

    assert updated is not None
    assert updated["title"] == "手动改名"
    assert updated["is_pinned"] is False
    assert updated["pinned_at"] is None
    assert updated["title_source"] == "user"


def test_missing_agent_panel_identity_is_rejected(monkeypatch):
    repo, _ = _install_repo(monkeypatch)

    try:
        repo.upsert_record(
            "agent-missing",
            title="缺少字段",
            preview="missing",
            status="answered",
            history_id="",
            panel_kind="",
            snapshot={"messages": []},
        )
    except ValueError as exc:
        assert "history_id" in str(exc)
    else:
        raise AssertionError("missing history_id/panel_kind should be rejected")


def test_list_records_exposes_panel_kind(monkeypatch):
    repo, _ = _install_repo(monkeypatch)

    repo.upsert_record(
        "agent-summary",
        title="总结会话",
        preview="summary",
        status="answered",
        history_id="history-current",
        panel_kind="commercial_summary",
        snapshot={
            "messages": [],
            "output": {
                "panel_payloads": {
                    "summary_pack": {
                        "headline_judgment": {"summary": "这是一个生活消费主导的商业区"},
                    }
                }
            },
        },
    )
    repo.upsert_record(
        "agent-followup",
        title="追问会话",
        preview="followup",
        status="answered",
        history_id="history-current",
        panel_kind="followup",
        snapshot={
            "messages": [{"role": "user", "content": "为什么这里路网较弱"}],
            "output": {"panel_payloads": {}},
        },
    )

    by_id = {item["id"]: item for item in repo.list_records()}
    assert by_id["agent-summary"]["panel_kind"] == "commercial_summary"
    assert by_id["agent-followup"]["panel_kind"] == "followup"
    assert by_id["agent-summary"]["history_id"] == "history-current"
    assert by_id["agent-followup"]["history_id"] == "history-current"
