from pathlib import Path
import sys
from datetime import datetime
from types import SimpleNamespace

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

sys.path.append(str(Path(__file__).resolve().parents[2]))

import store.history_repo as history_repo_module
from store.history_repo import HistoryRepo
from store.history_keys import build_history_record_id
from store.models import AgentSession, AnalysisHistory, Base, PoiResult


def _complete_poi(poi_id, name, location, year):
    return {
        "poi_id": poi_id,
        "name": name,
        "category": "餐饮",
        "subcategory": "中餐厅",
        "typecode": "050100",
        "address": "",
        "location": location,
        "year": year,
        "source": "local",
    }


def _install_repo(monkeypatch):
    engine = create_engine("sqlite:///:memory:", future=True)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(history_repo_module, "SessionLocal", testing_session_local)
    return HistoryRepo(), testing_session_local


def _build_history(params, polygon, *, description, history_id=None):
    return AnalysisHistory(
        id=history_id or build_history_record_id(params, polygon),
        description=description,
        params=params,
        result_polygon=polygon,
    )


def test_history_year_selection_uses_business_year_not_row_order():
    history = SimpleNamespace(params={"years": [2020, 2022, 2024], "year": 2020})
    rows = [
        SimpleNamespace(year=2024),
        SimpleNamespace(year=2022),
        SimpleNamespace(year=2020),
    ]

    assert HistoryRepo._resolve_selected_year(history, rows, None) == 2024
    assert HistoryRepo._resolve_selected_year(history, rows, 2022) == 2022
    assert HistoryRepo._resolve_selected_year(history, rows, 2030) == 2030


def test_history_year_selection_has_no_hardcoded_2026_preference():
    history = SimpleNamespace(params={"years": [2026, 2028]})
    rows = [SimpleNamespace(year=2026), SimpleNamespace(year=2028)]

    assert HistoryRepo._resolve_selected_year(history, rows, None) == 2028


def test_get_list_extracts_only_sidebar_params_from_sqlite(monkeypatch):
    repo, testing_session_local = _install_repo(monkeypatch)

    session = testing_session_local()
    try:
        params = {
            "center": [112.9388, 28.2282],
            "time_min": 15,
            "keywords": "咖啡店",
            "mode": "walking",
            "source": "local",
            "h3_result": {"grid": {"features": [{"id": i} for i in range(64)]}},
            "road_result": {"roads": {"features": [{"id": i} for i in range(64)]}},
        }
        polygon = [[112.9, 28.2], [113.0, 28.3], [112.9, 28.2]]
        session.add(
            _build_history(params, polygon, description="长沙步行 15 分钟")
        )
        session.commit()
    finally:
        session.close()

    records = repo.get_list()

    assert len(records) == 1
    assert records[0]["description"] == "长沙步行 15 分钟"
    assert records[0]["params"] == {
        "center": [112.9388, 28.2282],
        "time_min": 15,
        "keywords": "咖啡店",
        "mode": "walking",
        "source": "local",
        "year": None,
        "years": [],
    }


def test_get_list_dedupes_using_lightweight_sidebar_fields(monkeypatch):
    repo, testing_session_local = _install_repo(monkeypatch)

    session = testing_session_local()
    try:
        shared_params = {
            "center": [112.9, 28.2],
            "time_min": 15,
            "keywords": "咖啡店",
            "mode": "walking",
            "source": "local",
        }
        session.add_all(
            [
                _build_history(
                    {**shared_params, "h3_result": {"grid": {"features": [{"id": 1}]}}},
                    [],
                    description="同一分析",
                    history_id="history-dedupe-1",
                ),
                _build_history(
                    {**shared_params, "road_result": {"roads": {"features": [{"id": 2}, {"id": 3}]}}},
                    [],
                    description="同一分析",
                    history_id="history-dedupe-2",
                ),
            ]
        )
        session.commit()
    finally:
        session.close()

    records = repo.get_list()

    assert len(records) == 1


def test_get_list_includes_ai_session_count(monkeypatch):
    repo, testing_session_local = _install_repo(monkeypatch)

    session = testing_session_local()
    try:
        params = {
            "center": [112.9, 28.2],
            "time_min": 15,
            "keywords": "咖啡店",
            "mode": "walking",
            "source": "local",
        }
        polygon = [[112.9, 28.2], [113.0, 28.3], [112.9, 28.2]]
        history = _build_history(params, polygon, description="测试历史")
        session.add(history)
        session.flush()
        session.add(
            AgentSession(
                id="agent-1",
                title="总结",
                preview="summary",
                status="answered",
                history_id=history.id,
                panel_kind="commercial_summary",
                snapshot={"_meta": {"history_id": history.id}},
                is_pinned=False,
            )
        )
        session.commit()
    finally:
        session.close()

    records = repo.get_list()

    assert len(records) == 1
    assert records[0]["ai_session_count"] == 1


def test_delete_record_removes_linked_agent_sessions(monkeypatch):
    repo, testing_session_local = _install_repo(monkeypatch)

    session = testing_session_local()
    try:
        params = {
            "center": [112.9, 28.2],
            "time_min": 15,
            "keywords": "咖啡店",
            "mode": "walking",
            "source": "local",
        }
        polygon = [[112.9, 28.2], [113.0, 28.3], [112.9, 28.2]]
        history = _build_history(params, polygon, description="测试历史")
        session.add(history)
        session.flush()
        session.add(
            PoiResult(
                history_id=history.id,
                poi_data=[{"name": "test"}],
                summary={"total": 1},
            )
        )
        session.add_all(
            [
                AgentSession(
                    id="agent-linked",
                    title="linked",
                    preview="linked",
                    status="answered",
                    history_id=history.id,
                    panel_kind="commercial_summary",
                    snapshot={"_meta": {"history_id": history.id}},
                    is_pinned=False,
                ),
                AgentSession(
                    id="agent-other",
                    title="other",
                    preview="other",
                    status="answered",
                    history_id="other-history",
                    panel_kind="followup",
                    snapshot={"_meta": {"history_id": "other-history"}},
                    is_pinned=False,
                ),
            ]
        )
        session.commit()
        target_id = history.id
    finally:
        session.close()

    assert repo.delete_record(target_id) is True

    verify = testing_session_local()
    try:
        assert verify.query(AnalysisHistory).filter_by(id=target_id).count() == 0
        assert verify.query(PoiResult).filter_by(history_id=target_id).count() == 0
        assert verify.query(AgentSession).filter_by(id="agent-linked").count() == 0
        assert verify.query(AgentSession).filter_by(id="agent-other").count() == 1
    finally:
        verify.close()


def test_create_record_does_not_touch_created_at_when_material_is_unchanged(monkeypatch):
    repo, testing_session_local = _install_repo(monkeypatch)
    created_at = datetime(2024, 1, 1, 12, 0, 0)
    params = {
        "center": [112.9, 28.2],
        "time_min": 15,
        "keywords": "椁愰ギ",
        "mode": "walking",
        "source": "local",
        "year": None,
        "years": [],
    }
    polygon = [[112.9, 28.2], [113.0, 28.3], [112.9, 28.2]]
    pois = [{"id": "poi-1", "name": "test", "location": [112.9, 28.2]}]

    session = testing_session_local()
    try:
        history = _build_history(params, polygon, description="same", history_id="history-fixed")
        history.created_at = created_at
        session.add(history)
        session.flush()
        session.add(
            PoiResult(
                history_id="history-fixed",
                source="local",
                year=None,
                poi_data=pois,
                summary={"total": len(pois), "source": "local", "year": None},
                created_at=created_at,
            )
        )
        session.commit()
    finally:
        session.close()

    returned_id = repo.create_record(
        dict(params),
        [list(point) for point in polygon],
        [dict(item) for item in pois],
        "same",
        preferred_history_id="history-fixed",
    )

    assert returned_id == "history-fixed"

    verify = testing_session_local()
    try:
        history = verify.query(AnalysisHistory).filter_by(id="history-fixed").first()
        poi_record = verify.query(PoiResult).filter_by(history_id="history-fixed").first()
        assert history.created_at == created_at
        assert poi_record.created_at == created_at
        assert history.description == "same"
        assert history.params == params
        assert history.result_polygon == polygon
        assert poi_record.poi_data == pois
    finally:
        verify.close()


def test_create_record_updates_created_at_when_params_polygon_description_or_pois_change(monkeypatch):
    cases = [
        ("params", {"params": {"time_min": 30}}),
        ("polygon", {"polygon": [[112.9, 28.2], [113.1, 28.4], [112.9, 28.2]]}),
        ("description", {"description": "changed"}),
        ("pois", {"pois": [_complete_poi("poi-2", "changed", [113.0, 28.3], 2024)]}),
    ]
    for case_name, override in cases:
        repo, testing_session_local = _install_repo(monkeypatch)
        created_at = datetime(2024, 1, 1, 12, 0, 0)
        params = {
            "center": [112.9, 28.2],
            "time_min": 15,
            "keywords": "椁愰ギ",
            "mode": "walking",
            "source": "local",
            "year": 2024,
            "years": [2024],
        }
        polygon = [[112.9, 28.2], [113.0, 28.3], [112.9, 28.2]]
        pois = [_complete_poi("poi-1", "test", [112.9, 28.2], 2024)]

        session = testing_session_local()
        try:
            history = _build_history(params, polygon, description="same", history_id=f"history-{case_name}")
            history.created_at = created_at
            session.add(history)
            session.flush()
            session.add(
                PoiResult(
                    history_id=f"history-{case_name}",
                    source="local",
                    year=2024,
                    poi_data=pois,
                    summary={"total": len(pois)},
                    created_at=created_at,
                )
            )
            session.commit()
        finally:
            session.close()

        next_params = {**params, **override.get("params", {})}
        next_polygon = override.get("polygon", polygon)
        next_pois = override.get("pois", pois)
        next_description = override.get("description", "same")

        repo.create_record(
            next_params,
            next_polygon,
            next_pois,
            next_description,
            preferred_history_id=f"history-{case_name}",
        )

        verify = testing_session_local()
        try:
            history = verify.query(AnalysisHistory).filter_by(id=f"history-{case_name}").first()
            poi_record = verify.query(PoiResult).filter_by(history_id=f"history-{case_name}").first()
            assert history.created_at > created_at
            if case_name == "pois":
                assert poi_record.created_at > created_at
                assert poi_record.poi_data == next_pois
            assert history.description == next_description
            assert history.params == next_params
            assert history.result_polygon == next_polygon
        finally:
            verify.close()


def test_create_record_reuses_existing_preferred_history_id(monkeypatch):
    repo, testing_session_local = _install_repo(monkeypatch)

    session = testing_session_local()
    try:
        session.add(
            _build_history(
                {
                    "center": [112.9, 28.2],
                    "time_min": 15,
                    "keywords": "咖啡店",
                    "mode": "walking",
                    "source": "local",
                },
                [[112.9, 28.2], [113.0, 28.3], [112.9, 28.2]],
                description="old",
                history_id="history-fixed",
            )
        )
        session.commit()
    finally:
        session.close()

    returned_id = repo.create_record(
        {
            "center": [112.91, 28.21],
            "time_min": 30,
            "keywords": "餐饮",
            "mode": "walking",
            "source": "local",
        },
        [[120.1, 30.1], [120.2, 30.2], [120.1, 30.1]],
        [],
        "updated",
        preferred_history_id="history-fixed",
    )

    assert returned_id == "history-fixed"

    verify = testing_session_local()
    try:
        history = verify.query(AnalysisHistory).filter_by(id="history-fixed").first()
        assert history is not None
        assert history.description == "updated"
        assert history.result_polygon == [[120.1, 30.1], [120.2, 30.2], [120.1, 30.1]]
    finally:
        verify.close()


def test_create_record_appends_multi_year_snapshots_without_overwriting_existing_years(monkeypatch):
    repo, testing_session_local = _install_repo(monkeypatch)

    history_id = repo.create_record(
        {
            "center": [112.9, 28.2],
            "time_min": 15,
            "keywords": "poi",
            "mode": "walking",
            "source": "local",
            "year": 2022,
            "years": [2022],
        },
        [[112.9, 28.2], [113.0, 28.3], [112.9, 28.2]],
        [_complete_poi("poi-2022", "2022", [112.9, 28.2], 2022)],
        "multi",
        preferred_history_id="history-multi",
        poi_results_by_year=[{"source": "local", "year": 2022, "pois": [_complete_poi("poi-2022", "2022", [112.9, 28.2], 2022)]}],
    )

    repo.create_record(
        {
            "center": [112.9, 28.2],
            "time_min": 15,
            "keywords": "poi",
            "mode": "walking",
            "source": "local",
            "year": 2024,
            "years": [2022, 2024],
        },
        [[112.9, 28.2], [113.0, 28.3], [112.9, 28.2]],
        [_complete_poi("poi-2024", "2024", [112.9, 28.2], 2024)],
        "multi",
        preferred_history_id=history_id,
        poi_results_by_year=[{"source": "local", "year": 2024, "pois": [_complete_poi("poi-2024", "2024", [112.9, 28.2], 2024)]}],
    )

    verify = testing_session_local()
    try:
        history = verify.query(AnalysisHistory).filter_by(id=history_id).first()
        poi_rows = verify.query(PoiResult).filter_by(history_id=history_id).order_by(PoiResult.year.asc()).all()
        assert history.params["years"] == [2022, 2024]
        assert [row.year for row in poi_rows] == [2022, 2024]
        assert poi_rows[0].poi_data[0]["poi_id"] == "poi-2022"
        assert poi_rows[1].poi_data[0]["poi_id"] == "poi-2024"
    finally:
        verify.close()


def test_create_record_does_not_sort_large_poi_json_when_updating(monkeypatch):
    repo, testing_session_local = _install_repo(monkeypatch)

    history_id = repo.create_record(
        {
            "center": [112.9, 28.2],
            "time_min": 15,
            "keywords": "poi",
            "mode": "walking",
            "source": "local",
            "year": 2022,
            "years": [2022],
        },
        [[112.9, 28.2], [113.0, 28.3], [112.9, 28.2]],
        [_complete_poi("poi-2022", "2022", [112.9, 28.2], 2022)],
        "multi",
        preferred_history_id="history-no-large-sort",
        poi_results_by_year=[{"source": "local", "year": 2022, "pois": [_complete_poi("poi-2022", "2022", [112.9, 28.2], 2022)]}],
    )

    engine = testing_session_local.kw["bind"]
    statements = []

    def _record_statement(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.lower())

    event.listen(engine, "before_cursor_execute", _record_statement)
    try:
        repo.create_record(
            {
                "center": [112.9, 28.2],
                "time_min": 15,
                "keywords": "poi",
                "mode": "walking",
                "source": "local",
                "year": 2024,
                "years": [2022, 2024],
            },
            [[112.9, 28.2], [113.0, 28.3], [112.9, 28.2]],
            [_complete_poi("poi-2024", "2024", [112.9, 28.2], 2024)],
            "multi",
            preferred_history_id=history_id,
            poi_results_by_year=[{"source": "local", "year": 2024, "pois": [_complete_poi("poi-2024", "2024", [112.9, 28.2], 2024)]}],
        )
    finally:
        event.remove(engine, "before_cursor_execute", _record_statement)

    sorted_large_selects = [
        statement
        for statement in statements
        if "select" in statement
        and "poi_results.poi_data" in statement
        and "order by" in statement
    ]
    assert sorted_large_selects == []


def test_get_pois_reads_large_poi_json_only_after_selecting_target_row(monkeypatch):
    repo, testing_session_local = _install_repo(monkeypatch)

    session = testing_session_local()
    try:
        session.add(
            _build_history(
                {
                    "center": [112.9, 28.2],
                    "time_min": 15,
                    "keywords": "poi",
                    "mode": "walking",
                    "source": "local",
                    "year": 2024,
                    "years": [2022, 2024],
                },
                [[112.9, 28.2], [113.0, 28.3], [112.9, 28.2]],
                description="multi",
                history_id="history-poi-select",
            )
        )
        session.flush()
        session.add_all(
            [
                PoiResult(
                    history_id="history-poi-select",
                    source="local",
                    year=2022,
                    poi_data=[{"id": "poi-2022"}],
                    summary={"total": 1, "source": "local", "year": 2022},
                ),
                PoiResult(
                    history_id="history-poi-select",
                    source="local",
                    year=2024,
                    poi_data=[{"id": "poi-2024"}, {"id": "poi-2024-b"}],
                    summary={"total": 2, "source": "local", "year": 2024},
                ),
            ]
        )
        session.commit()
    finally:
        session.close()

    engine = testing_session_local.kw["bind"]
    statements = []

    def _record_statement(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.lower())

    event.listen(engine, "before_cursor_execute", _record_statement)
    try:
        result = repo.get_pois("history-poi-select", year=2024)
    finally:
        event.remove(engine, "before_cursor_execute", _record_statement)

    assert result["count"] == 2
    assert result["polygon"] == [[112.9, 28.2], [113.0, 28.3], [112.9, 28.2]]
    assert [poi["id"] for poi in result["pois"]] == ["poi-2024", "poi-2024-b"]
    poi_data_selects = [
        statement
        for statement in statements
        if "select" in statement and "poi_results.poi_data" in statement
    ]
    assert len(poi_data_selects) == 1
    assert "where poi_results.id" in poi_data_selects[0]
