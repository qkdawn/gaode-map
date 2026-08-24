from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import modules.spatial_strategy.strategy_chapters as strategy_chapters


RUN_ID = "7b8ab959-c0e2-4d29-8168-9688cb4989bf"


def _chapter(unit_id: str, title: str, content: str) -> str:
    return json.dumps(
        {"unit_id": unit_id, "title": title, "content": content, "citations": []},
        ensure_ascii=False,
    )


def _session_factory():
    engine = create_engine("sqlite:///:memory:", future=True)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE analysis_runs (id TEXT PRIMARY KEY, history_id TEXT, request JSON)"))
        connection.execute(text("CREATE TABLE analysis_step_outputs (run_id TEXT, step TEXT, step_order INTEGER, status TEXT, output JSON)"))
        connection.execute(
            text("INSERT INTO analysis_runs (id, history_id, request) VALUES (:run_id, 'history-1', json(:request))"),
            {"run_id": RUN_ID, "request": '{"project_question":"形成未来空间策略"}'},
        )
        connection.execute(
            text(
                "INSERT INTO analysis_step_outputs (run_id, step, step_order, status, output) "
                "VALUES (:run_id, 'project_basis', 1, 'completed', json(:basis)), "
                "(:run_id, 'supply_gap', 3, 'completed', json(:supply)), "
                "(:run_id, 'audience_use', 4, 'running', json(:audience))"
            ),
            {
                "run_id": RUN_ID,
                "basis": _chapter("project_basis", "项目材料与项目基础", "材料形成明确边界。"),
                "supply": _chapter("supply_gap", "具名供给与服务空位", "项目补充公共服务。"),
                "audience": _chapter("audience_use", "客群与使用", "运行中内容不可读取。"),
            },
        )
    return sessionmaker(bind=engine, future=True)


def test_read_strategy_chapters_returns_only_requested_completed_products(monkeypatch):
    monkeypatch.setattr(strategy_chapters, "SessionLocal", _session_factory())

    result = strategy_chapters.read_strategy_chapters(
        RUN_ID,
        ["supply_gap", "project_basis"],
    )

    assert result["run_id"] == RUN_ID
    assert result["history_id"] == "history-1"
    assert result["project_question"] == "形成未来空间策略"
    assert [chapter["unit_id"] for chapter in result["chapters"]] == [
        "supply_gap",
        "project_basis",
    ]
    assert set(result["chapters"][0]) == {"unit_id", "title", "content", "citations"}
    assert "audience_use" not in str(result)


def test_read_strategy_chapters_fails_when_a_dependency_is_incomplete(monkeypatch):
    monkeypatch.setattr(strategy_chapters, "SessionLocal", _session_factory())

    with pytest.raises(LookupError, match="spatial_strategy_chapters_not_found:audience_use"):
        strategy_chapters.read_strategy_chapters(RUN_ID, ["audience_use"])


def test_read_strategy_chapters_rejects_empty_selection(monkeypatch):
    monkeypatch.setattr(strategy_chapters, "SessionLocal", _session_factory())

    with pytest.raises(ValueError, match="strategy_chapter_unit_ids_required"):
        strategy_chapters.read_strategy_chapters(RUN_ID, [])


def test_read_strategy_chapters_rejects_unknown_run(monkeypatch):
    factory = _session_factory()
    session = factory()
    session.execute(text("DELETE FROM analysis_runs"))
    session.commit()
    session.close()
    monkeypatch.setattr(strategy_chapters, "SessionLocal", factory)

    with pytest.raises(LookupError, match="spatial_strategy_run_not_found"):
        strategy_chapters.read_strategy_chapters(RUN_ID, ["project_basis"])
