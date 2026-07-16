from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from xml.etree import ElementTree

import pytest

from modules.spatial_action.report_visuals import render_report_visual, validate_safe_svg
from store.analysis_run_storage import AnalysisRunStorage


def _candidate(visual_type: str, data: dict) -> dict:
    return {
        "visual_id": f"visual:{visual_type}",
        "visual_type": visual_type,
        "title": f"{visual_type} <验证>",
        "purpose": "确定性 & 可追溯渲染",
        "evidence_ids": ["evidence:one"],
        "metric_attempt_ids": ["plan:one"],
        "source_artifact": "source.json",
        "object_ids": [],
        "transform": {"type": "identity"},
        "coordinate_system": "EPSG:4326",
        "extent": [112.0, 28.0, 112.1, 28.1],
        "geometry_sources": ["artifact:geometry"],
        "spec_hash": "sha256:spec",
        "data": data,
    }


@pytest.mark.parametrize(
    ("visual_type", "data", "expected_token"),
    [
        (
            "bar",
            {"x_label": "阶段", "y_label": "数量", "series": [{"name": "基准", "points": [{"label": "一", "value": 2}, {"label": "二", "value": 5}]}]},
            "<rect",
        ),
        (
            "line",
            {"x_label": "年份", "y_label": "指数", "series": [{"name": "趋势", "points": [{"label": "2025", "value": 2}, {"label": "2026", "value": 3}]}]},
            "<polyline",
        ),
        (
            "scatter",
            {"x_label": "接触", "y_label": "停留", "series": [{"name": "样本", "points": [{"x": 1, "y": 3, "label": "A"}, {"x": 4, "y": 6, "label": "B"}]}]},
            "<circle",
        ),
        (
            "simple_map",
            {"features": [{"id": "zone:one", "label": "试点区", "geometry": {"type": "Polygon", "coordinates": [[[112.0, 28.0], [112.1, 28.0], [112.1, 28.1], [112.0, 28.1], [112.0, 28.0]]]}, "value": 7}]},
            "<path",
        ),
        (
            "diagram",
            {"nodes": [{"id": "a", "label": "输入"}, {"id": "b", "label": "判断"}], "links": [{"source": "a", "target": "b", "label": "形成"}]},
            "marker-end",
        ),
        (
            "timeline",
            {"items": [{"label": "试点", "detail": "封顶预算", "order": 2}, {"label": "核验", "detail": "先行检查", "order": 1}]},
            "封顶预算",
        ),
    ],
)
def test_report_visual_renderer_is_deterministic(visual_type, data, expected_token):
    candidate = _candidate(visual_type, data)

    first = render_report_visual(candidate)
    second = render_report_visual(candidate)

    assert first == second
    assert first.startswith('<svg xmlns="http://www.w3.org/2000/svg"')
    assert first.endswith("</svg>\n")
    assert "&lt;验证&gt;" in first
    assert "确定性 &amp; 可追溯渲染" in first
    assert expected_token in first
    validate_safe_svg(first)

    root = ElementTree.fromstring(first)
    metadata = next(item for item in root if item.tag.rsplit("}", 1)[-1] == "metadata")
    assert json.loads(metadata.text or "") == {
        "coordinate_system": candidate["coordinate_system"],
        "evidence_ids": candidate["evidence_ids"],
        "extent": candidate["extent"],
        "geometry_sources": candidate["geometry_sources"],
        "metric_attempt_ids": candidate["metric_attempt_ids"],
        "source_artifact": candidate["source_artifact"],
        "spec_hash": candidate["spec_hash"],
        "transform": candidate["transform"],
        "visual_id": candidate["visual_id"],
    }


def test_report_visual_renderer_rejects_missing_or_invalid_data():
    with pytest.raises(ValueError, match=r"bar\.data\.series"):
        render_report_visual(_candidate("bar", {}))

    with pytest.raises(ValueError, match="unknown node"):
        render_report_visual(
            _candidate(
                "diagram",
                {"nodes": [{"id": "a", "label": "输入"}], "links": [{"source": "a", "target": "missing"}]},
            )
        )


@pytest.mark.parametrize(
    "unsafe_svg",
    [
        '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg"><foreignObject><div>unsafe</div></foreignObject></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg"><image href="https://example.com/x.svg"/></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>',
        '<svg xmlns="http://www.w3.org/2000/svg"><path fill="url(https://example.com/pattern)"/></svg>',
    ],
)
def test_validate_safe_svg_rejects_active_content_and_external_links(unsafe_svg):
    with pytest.raises(ValueError):
        validate_safe_svg(unsafe_svg)


def test_report_visual_svg_round_trips_through_run_storage(tmp_path):
    storage = AnalysisRunStorage(tmp_path)
    svg = render_report_visual(
        _candidate(
            "bar",
            {"series": [{"name": "试点", "points": [{"label": "使用", "value": 12}]}]},
        )
    )
    manifest = {
        "run_id": "visual-run",
        "capability_id": "visual-capability",
        "input_artifact_refs": [],
        "output_artifact_refs": [
            {
                "artifact_id": "visual:bar",
                "artifact_type": "report_visual",
                "title": "bar",
                "filename": "pilot-usage",
                "content_digest": "sha256:visual",
            }
        ],
    }
    request = {"history_id": "history"}

    created = storage.create(history_id="history", manifest=manifest, artifact_payloads={"visual:bar": svg}, execution_request=request)
    reused = storage.create(history_id="history", manifest=manifest, artifact_payloads={"visual:bar": svg}, execution_request=request)
    storage.validate("visual-capability", "visual-run")

    target = tmp_path / "visual-capability" / "visual-run" / "report" / "assets" / "pilot-usage.svg"
    index = json.loads((target.parents[2] / "artifact-index.json").read_text(encoding="utf-8"))
    assert target.read_text(encoding="utf-8") == svg
    assert target.read_bytes() == svg.encode("utf-8")
    assert created == reused
    assert created["artifacts"][0]["payload"] == svg
    assert index["artifacts"][0]["format"] == "svg"
    assert index["artifacts"][0]["path"] == "report/assets/pilot-usage.svg"


def test_report_markdown_storage_preserves_lf_bytes(tmp_path):
    storage = AnalysisRunStorage(tmp_path)
    report = "# 报告\n\n正文\n"
    manifest = {
        "run_id": "report-run",
        "capability_id": "report-capability",
        "input_artifact_refs": [],
        "output_artifact_refs": [
            {
                "artifact_id": "artifact:report",
                "artifact_type": "report",
                "title": "report",
                "filename": "project-report.md",
                "content_digest": "sha256:report",
            }
        ],
    }
    storage.create(
        history_id="history",
        manifest=manifest,
        artifact_payloads={"artifact:report": report},
        execution_request={"history_id": "history"},
    )
    target = tmp_path / "report-capability" / "report-run" / "report" / "project-report.md"
    assert target.read_bytes() == report.encode("utf-8")
    assert b"\r\n" not in target.read_bytes()


def test_report_chapter_round_trips_as_json_in_chapters_directory(tmp_path):
    storage = AnalysisRunStorage(tmp_path)
    chapter = {"chapter_id": "chapter:one", "title": "项目判断", "blocks": [{"type": "paragraph", "text": "内容"}]}
    manifest = {
        "run_id": "chapter-run",
        "capability_id": "chapter-capability",
        "input_artifact_refs": [],
        "output_artifact_refs": [
            {
                "artifact_id": "chapter:one",
                "artifact_type": "report_chapter",
                "title": "chapter",
                "filename": "project-judgment",
                "content_digest": "sha256:chapter",
            }
        ],
    }

    created = storage.create(history_id="history", manifest=manifest, artifact_payloads={"chapter:one": chapter}, execution_request={"history_id": "history"})
    reused = storage.create(history_id="history", manifest=manifest, artifact_payloads={"chapter:one": chapter}, execution_request={"history_id": "history"})
    storage.validate("chapter-capability", "chapter-run")

    target = tmp_path / "chapter-capability" / "chapter-run" / "chapters" / "project-judgment.json"
    index = json.loads((target.parent.parent / "artifact-index.json").read_text(encoding="utf-8"))
    assert json.loads(target.read_text(encoding="utf-8")) == chapter
    assert created == reused
    assert created["artifacts"][0]["payload"] == chapter
    assert index["artifacts"][0]["format"] == "json"
    assert index["artifacts"][0]["path"] == "chapters/project-judgment.json"


def test_evidence_gates_round_trip_in_evidence_directory(tmp_path):
    storage = AnalysisRunStorage(tmp_path)
    gates = {"schema_version": "2.0", "run_id": "gate-run", "gates": []}
    manifest = {
        "run_id": "gate-run",
        "capability_id": "gate-capability",
        "input_artifact_refs": [],
        "output_artifact_refs": [
            {
                "artifact_id": "artifact:evidence-gates",
                "artifact_type": "evidence_gates",
                "title": "evidence gates",
                "filename": "evidence-gates.json",
                "content_digest": "sha256:gates",
            }
        ],
    }
    created = storage.create(
        history_id="history",
        manifest=manifest,
        artifact_payloads={"artifact:evidence-gates": gates},
        execution_request={"history_id": "history"},
    )
    storage.validate("gate-capability", "gate-run")
    target = tmp_path / "gate-capability" / "gate-run" / "evidence" / "evidence-gates.json"
    assert json.loads(target.read_text(encoding="utf-8")) == gates
    assert created["artifacts"][0]["payload"] == gates


def test_run_workspace_finalize_reads_svg_as_text(tmp_path, monkeypatch):
    script_path = Path("skills/spatial-business-analyst/scripts/run_workspace.py").resolve()
    spec = importlib.util.spec_from_file_location("report_visual_run_workspace", script_path)
    assert spec and spec.loader
    run_workspace = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(run_workspace)

    root = tmp_path / "runs"
    capability_id = "visual-capability"
    run_id = "visual-finalize"
    workspace = root / capability_id / f".{run_id}.workspace"
    (workspace / "report" / "assets").mkdir(parents=True)
    (workspace / "chapters").mkdir()
    svg = render_report_visual(_candidate("timeline", {"items": [{"label": "启动", "order": 1}]}))
    chapter = {"chapter_id": "chapter:one", "title": "阶段判断"}
    (workspace / "report" / "assets" / "timeline.svg").write_text(svg, encoding="utf-8")
    (workspace / "chapters" / "stage.json").write_text(json.dumps(chapter), encoding="utf-8")
    manifest = {
        "run_id": run_id,
        "capability_id": capability_id,
        "status": "completed",
        "metric_plan": {"catalog_version": "test", "decision_questions": [], "entries": []},
        "output_artifact_refs": [
            {"artifact_id": "visual:timeline", "artifact_type": "report_visual", "filename": "timeline.svg"},
            {"artifact_id": "chapter:one", "artifact_type": "report_chapter", "filename": "stage.json"},
        ],
    }
    request = {"history_id": "history"}
    manifest_path = tmp_path / "manifest.json"
    request_path = tmp_path / "request.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    request_path.write_text(json.dumps(request), encoding="utf-8")
    captured = {}

    def fake_save(_repo, **kwargs):
        captured.update(kwargs)
        return {}

    monkeypatch.setattr(run_workspace.AnalysisRunRepo, "save", fake_save)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(script_path),
            "finalize",
            "--root",
            str(root),
            "--capability-id",
            capability_id,
            "--run-id",
            run_id,
            "--manifest",
            str(manifest_path),
            "--request",
            str(request_path),
        ],
    )

    assert run_workspace.main() == 0
    assert captured["artifact_payloads"]["visual:timeline"] == svg
    assert captured["artifact_payloads"]["chapter:one"] == chapter
    assert not workspace.exists()


def test_run_workspace_init_creates_chapters_directory(tmp_path, monkeypatch):
    script_path = Path("skills/spatial-business-analyst/scripts/run_workspace.py").resolve()
    spec = importlib.util.spec_from_file_location("report_chapter_run_workspace", script_path)
    assert spec and spec.loader
    run_workspace = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(run_workspace)

    root = tmp_path / "runs"
    manifest = {
        "run_id": "chapter-init",
        "capability_id": "chapter-capability",
        "metric_plan": {"catalog_version": "test", "decision_questions": [], "entries": []},
    }
    request = {"history_id": "history"}
    manifest_path = tmp_path / "manifest-init.json"
    request_path = tmp_path / "request-init.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    request_path.write_text(json.dumps(request), encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(script_path),
            "init",
            "--root",
            str(root),
            "--capability-id",
            "chapter-capability",
            "--run-id",
            "chapter-init",
            "--manifest",
            str(manifest_path),
            "--request",
            str(request_path),
        ],
    )

    assert run_workspace.main() == 0
    assert (root / "chapter-capability" / ".chapter-init.workspace" / "chapters").is_dir()
