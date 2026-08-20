from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import modules.spatial_strategy.strategy_decisions as strategy_decisions


RUN_ID = "7b8ab959-c0e2-4d29-8168-9688cb4989bf"


def _session_factory():
    engine = create_engine("sqlite:///:memory:", future=True)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE analysis_runs (id TEXT PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE analysis_step_outputs (run_id TEXT, step TEXT, step_order INTEGER, status TEXT, output JSON)"))
        connection.execute(text("INSERT INTO analysis_runs (id) VALUES (:run_id)"), {"run_id": RUN_ID})
        connection.execute(
            text(
                "INSERT INTO analysis_step_outputs (run_id, step, step_order, status, output) "
                "VALUES (:run_id, 'future_role', 2, 'completed', json(:output)), "
                "(:run_id, 'current_structure', 1, 'completed', json(:other)), "
                "(:run_id, 'pending_unit', 3, 'running', json(:pending))"
            ),
            {
                "run_id": RUN_ID,
                "output": '{"unit_id":"future_role","title":"未来角色","decision_memo":{"decision":"公共文化客厅","reasoning":"内部推理","key_facts":["原址大院"],"named_entities":[{"name":"潘家坪路","entity_type":"road","relationship":"西侧连接道路","fact":"距项目约135.4米","record_ref":"current:dataset:road_edges/road-1"}],"actions":[{"action":"开放主轴"}],"alternatives_considered":[{"alternative":"商业中心","reason":"供给重复"}]}}',
                "other": '{"unit_id":"current_structure","title":"现状结构","decision_memo":{"decision":"保留门轴院园骨架","key_facts":[],"actions":[],"alternatives_considered":[]}}',
                "pending": '{"unit_id":"pending_unit","decision_memo":{"decision":"不应返回"}}',
            },
        )
    return sessionmaker(bind=engine, future=True)


def test_read_strategy_decisions_returns_only_completed_domain_fields(monkeypatch):
    monkeypatch.setattr(strategy_decisions, "SessionLocal", _session_factory())

    result = strategy_decisions.read_strategy_decisions(RUN_ID)

    assert result["run_id"] == RUN_ID
    assert [item["unit_id"] for item in result["decisions"]] == ["current_structure", "future_role"]
    assert result["decisions"][1] == {
        "unit_id": "future_role",
        "title": "未来角色",
        "decision": "公共文化客厅",
        "key_facts": ["原址大院"],
        "named_entities": [
            {
                "name": "潘家坪路",
                "entity_type": "road",
                "relationship": "西侧连接道路",
                "fact": "距项目约135.4米",
                "record_ref": "current:dataset:road_edges/road-1",
            }
        ],
        "actions": [{"action": "开放主轴"}],
        "alternatives_considered": [{"alternative": "商业中心", "reason": "供给重复"}],
    }
    serialized = str(result)
    assert "内部推理" not in serialized
    assert "pending_unit" not in serialized
    assert "status" not in serialized


def test_read_strategy_decisions_rejects_unknown_run(monkeypatch):
    factory = _session_factory()
    session = factory()
    session.execute(text("DELETE FROM analysis_runs"))
    session.commit()
    session.close()
    monkeypatch.setattr(strategy_decisions, "SessionLocal", factory)

    try:
        strategy_decisions.read_strategy_decisions(RUN_ID)
    except LookupError as exc:
        assert str(exc) == "spatial_strategy_run_not_found"
    else:
        raise AssertionError("unknown run must fail")
