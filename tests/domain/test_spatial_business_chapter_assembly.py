from __future__ import annotations

import importlib.util
import hashlib
import json
import sys
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "spatial-business-analyst"
    / "scripts"
    / "validate_chapter_assembly.py"
)
SPEC = importlib.util.spec_from_file_location("validate_chapter_assembly", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _review(review_type: str, verdict: str) -> str:
    label = "反方审查" if review_type == "adversarial" else "分析深度审校"
    return (
        "---\n"
        f"review_type: {review_type}\n"
        f"verdict: {verdict}\n"
        "---\n"
        f"# {label}\n\n"
        "已核验关键判断、候选解释、证据机制、方案代价与改判路径，结论能够影响当前决策。"
    )


def _write_reviews(reviews_dir: Path, chapter_id: str, version: int, verdict: str) -> dict[str, str | int]:
    adversarial = f"{chapter_id}.v{version}.adversarial.md"
    depth = f"{chapter_id}.v{version}.depth.md"
    (reviews_dir / adversarial).write_text(_review("adversarial", verdict), encoding="utf-8")
    (reviews_dir / depth).write_text(_review("depth", verdict), encoding="utf-8")
    return {
        "version": version,
        "path": f"chapters/{chapter_id}.v{version}.md",
        "adversarial_review_path": f"chapter-reviews/{adversarial}",
        "depth_review_path": f"chapter-reviews/{depth}",
        "review_status": verdict,
    }


def _write_state_bundle(report_dir: Path) -> None:
    state_dir = report_dir / "state"
    state_dir.mkdir()
    snapshot_version = 4
    payloads = {
        "project_semantic_model": {"objects": []},
        "problem_map": {"status": "confirmed", "questions": []},
        "decision_logic_map": {
            "status": "ready",
            "value_path": {
                "baseline": "居民对场地的日常使用缺少稳定承接。",
                "beneficiaries": [
                    {
                        "stakeholder": "周边居民",
                        "current_need": "获得低冲突的日常服务与参与界面。",
                        "timeframe": "每周日常使用时段",
                    }
                ],
                "desired_outcome": "形成可持续使用并可被运营团队响应的服务闭环。",
                "deployable_workflow": {
                    "user": "周边居民",
                    "trigger": "产生服务或参与需求时",
                    "service": "完成一次可记录的居民服务与内容参与",
                    "space": "首期开放的公共界面",
                    "operator": "项目协调人",
                    "record": "服务闭合与重复使用记录",
                },
                "outputs": ["完成的服务记录和内容单元"],
                "outcomes": ["稳定使用与协同响应"],
                "impacts": ["形成可复制的基层治理服务机制"],
                "assumptions": ["居民愿意在明确规则下持续使用"],
                "intervention_window": "首期六个月",
                "outcome_horizon": "首期结束后三个月复核",
                "expansion_or_stop": "以重复使用、服务闭合和冲突记录决定调整。",
                "replication_unit": "下一处居民服务空间",
            },
            "rules": [
                {
                    "id": "R1",
                    "decision_question": "项目首期应验证什么？",
                    "when": ["当前直接市场证据尚未闭合。"],
                    "judgment": "先采用低容量可逆试验。",
                    "action": "首期不投入重资产。",
                    "alternatives": ["直接建设重资产内容"],
                    "counterexample": "若直接市场证据闭合，则可比较重资产方案。",
                    "evidence_refs": ["evidence:market:1"],
                    "limitations": ["空间指标不能证明支付意愿。"],
                    "validation": "以试验到访和支付记录决定后续投资。",
                    "status": "conditional",
                    "metric_refs": [],
                }
            ],
        },
        "decision_inventory": {"decisions": []},
        "evidence_summary": {"items": []},
    }
    artifacts = {}
    for state_id, contract in MODULE.STATE_ARTIFACTS.items():
        artifact = {
            "state_id": state_id,
            "schema": contract["schema"],
            "snapshot_version": snapshot_version,
            "updated_at": "2026-07-22T10:00:00+08:00",
            "payload": payloads[state_id],
        }
        path = report_dir / contract["path"]
        path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
        artifacts[state_id] = {
            "path": contract["path"],
            "schema": contract["schema"],
            "snapshot_version": snapshot_version,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    manifest = {
        "schema": MODULE.STATE_MANIFEST_SCHEMA,
        "snapshot_version": snapshot_version,
        "artifacts": artifacts,
    }
    (state_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_report(tmp_path: Path, *, second_version: bool = True, mutate_assembly: bool = False) -> Path:
    report_dir = tmp_path / "report"
    chapters_dir = report_dir / "chapters"
    reviews_dir = report_dir / "chapter-reviews"
    chapters_dir.mkdir(parents=True)
    reviews_dir.mkdir()
    _write_state_bundle(report_dir)

    first_v1 = "# 目标客群与行为\n\n" + "市场证据改变使用场景。" * 170
    first_v2 = "# 目标客群与行为\n\n" + "市场证据通过日常使用机制改变产品时段。" * 130
    positioning = "# 定位与产品\n\n" + "推荐方向的相对优势来自项目特有资产与使用关系。" * 100
    (chapters_dir / "regional-people.v1.md").write_text(first_v1, encoding="utf-8")
    versions = [_write_reviews(reviews_dir, "regional-people", 1, "revision_required" if second_version else "accepted")]
    accepted_first = first_v1
    accepted_version = 1
    if second_version:
        (chapters_dir / "regional-people.v2.md").write_text(first_v2, encoding="utf-8")
        versions.append(_write_reviews(reviews_dir, "regional-people", 2, "accepted"))
        accepted_first = first_v2
        accepted_version = 2
    (chapters_dir / "positioning-product.v1.md").write_text(positioning, encoding="utf-8")
    positioning_review = _write_reviews(reviews_dir, "positioning-product", 1, "accepted")

    index = {
        "schema": MODULE.CHAPTER_INDEX_SCHEMA,
        "report_mode": "formal_comprehensive",
        "state_manifest": MODULE.STATE_MANIFEST_PATH,
        "chapters": [
            {
                "chapter_id": "regional-people",
                "role": "目标客群与行为综合师",
                "decision_ids": ["decision:people"],
                "dependencies": [],
                "versions": versions,
                "accepted_version": accepted_version,
                "status": "accepted",
                "character_count": MODULE.content_character_count(accepted_first),
            },
            {
                "chapter_id": "positioning-product",
                "role": "定位与产品策略师",
                "decision_ids": ["decision:positioning"],
                "dependencies": ["regional-people"],
                "versions": [positioning_review],
                "accepted_version": 1,
                "status": "accepted",
                "character_count": MODULE.content_character_count(positioning),
            },
        ],
    }
    (report_dir / "chapter-index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    assembled_first = accepted_first.replace("使用机制", "消费机制", 1) if mutate_assembly else accepted_first
    report = (
        "# 项目报告\n\n执行摘要。\n\n"
        f'<!-- chapter:start id="regional-people" version="v{accepted_version}" -->\n'
        f"{assembled_first}\n"
        '<!-- chapter:end id="regional-people" -->\n\n过渡。\n\n'
        '<!-- chapter:start id="positioning-product" version="v1" -->\n'
        f"{positioning}\n"
        '<!-- chapter:end id="positioning-product" -->\n'
    )
    (report_dir / "project-report.md").write_text(report, encoding="utf-8")
    return report_dir


def _codes(findings) -> set[str]:
    return {item.code for item in findings}


def test_validates_versioned_low_loss_assembly(tmp_path):
    report_dir = _write_report(tmp_path)

    result = MODULE.validate_report_dir(report_dir)

    assert result.valid is True
    assert result.chapter_count == 2
    assert not result.errors


def test_rejects_single_line_review(tmp_path):
    report_dir = _write_report(tmp_path)
    review = report_dir / "chapter-reviews" / "regional-people.v2.adversarial.md"
    review.write_text("accepted", encoding="utf-8")

    result = MODULE.validate_report_dir(report_dir)

    assert result.valid is False
    assert "chapter_review_metadata_missing" in _codes(result.errors)


def test_rejects_missing_independent_review(tmp_path):
    report_dir = _write_report(tmp_path)
    (report_dir / "chapter-reviews" / "regional-people.v2.depth.md").unlink()

    result = MODULE.validate_report_dir(report_dir)

    assert "chapter_depth_review_missing" in _codes(result.errors)


def test_rejects_wrong_review_type(tmp_path):
    report_dir = _write_report(tmp_path)
    review = report_dir / "chapter-reviews" / "regional-people.v2.adversarial.md"
    review.write_text(_review("depth", "accepted"), encoding="utf-8")

    result = MODULE.validate_report_dir(report_dir)

    assert "chapter_review_type" in _codes(result.errors)


def test_rejects_review_without_substantive_rationale(tmp_path):
    report_dir = _write_report(tmp_path)
    review = report_dir / "chapter-reviews" / "regional-people.v2.depth.md"
    review.write_text("---\nreview_type: depth\nverdict: accepted\n---\n# 好", encoding="utf-8")

    result = MODULE.validate_report_dir(report_dir)

    assert "chapter_review_rationale_missing" in _codes(result.errors)


def test_rejects_latest_revision_required_verdict(tmp_path):
    report_dir = _write_report(tmp_path)
    review = report_dir / "chapter-reviews" / "regional-people.v2.depth.md"
    review.write_text(_review("depth", "revision_required"), encoding="utf-8")

    result = MODULE.validate_report_dir(report_dir)

    assert {"chapter_review_status", "chapter_review_status_mismatch"} <= _codes(result.errors)


def test_requires_explicit_state_manifest_reference(tmp_path):
    report_dir = _write_report(tmp_path)
    index_path = report_dir / "chapter-index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    del index["state_manifest"]
    index_path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")

    result = MODULE.validate_report_dir(report_dir)

    assert "state_manifest_reference_missing" in _codes(result.errors)


def test_rejects_missing_state_manifest(tmp_path):
    report_dir = _write_report(tmp_path)
    (report_dir / MODULE.STATE_MANIFEST_PATH).unlink()

    result = MODULE.validate_report_dir(report_dir)

    assert "state_manifest_missing" in _codes(result.errors)


def test_rejects_state_path_escape(tmp_path):
    report_dir = _write_report(tmp_path)
    manifest_path = report_dir / MODULE.STATE_MANIFEST_PATH
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"]["problem_map"]["path"] = "../problem-map.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    result = MODULE.validate_report_dir(report_dir)

    assert {"state_artifact_path", "state_artifact_missing"} <= _codes(result.errors)


def test_rejects_snapshot_version_mismatch(tmp_path):
    report_dir = _write_report(tmp_path)
    manifest_path = report_dir / MODULE.STATE_MANIFEST_PATH
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"]["problem_map"]["snapshot_version"] += 1
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    result = MODULE.validate_report_dir(report_dir)

    assert "state_artifact_snapshot" in _codes(result.errors)


def test_rejects_incomplete_decision_logic_rule(tmp_path):
    report_dir = _write_report(tmp_path)
    state_path = report_dir / MODULE.STATE_ARTIFACTS["decision_logic_map"]["path"]
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["payload"]["rules"][0].pop("counterexample")
    state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    manifest_path = report_dir / MODULE.STATE_MANIFEST_PATH
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"]["decision_logic_map"]["sha256"] = hashlib.sha256(state_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    result = MODULE.validate_report_dir(report_dir)

    assert "decision_logic_rule_invalid" in _codes(result.errors)


def test_rejects_missing_value_path(tmp_path):
    report_dir = _write_report(tmp_path)
    state_path = report_dir / MODULE.STATE_ARTIFACTS["decision_logic_map"]["path"]
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["payload"].pop("value_path")
    state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    manifest_path = report_dir / MODULE.STATE_MANIFEST_PATH
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"]["decision_logic_map"]["sha256"] = hashlib.sha256(state_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    result = MODULE.validate_report_dir(report_dir)

    assert "value_path_missing" in _codes(result.errors)


def test_rejects_legacy_index_schema_version(tmp_path):
    report_dir = _write_report(tmp_path)
    index_path = report_dir / "chapter-index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["schema_version"] = index.pop("schema")
    index_path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")

    result = MODULE.validate_report_dir(report_dir)

    assert {"chapter_index_legacy_schema", "chapter_index_schema"} <= _codes(result.errors)


def test_rejects_legacy_state_version(tmp_path):
    report_dir = _write_report(tmp_path)
    manifest_path = report_dir / MODULE.STATE_MANIFEST_PATH
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["state_version"] = 1
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    result = MODULE.validate_report_dir(report_dir)

    assert "state_manifest_legacy_version" in _codes(result.errors)


def test_rejects_wrong_state_schema(tmp_path):
    report_dir = _write_report(tmp_path)
    manifest_path = report_dir / MODULE.STATE_MANIFEST_PATH
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["schema"] = "wrong-state-manifest"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    result = MODULE.validate_report_dir(report_dir)

    assert "state_manifest_schema" in _codes(result.errors)


def test_rejects_state_checksum_mismatch(tmp_path):
    report_dir = _write_report(tmp_path)
    state_path = report_dir / MODULE.STATE_ARTIFACTS["evidence_summary"]["path"]
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["payload"]["items"].append({"id": "evidence:tampered"})
    state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

    result = MODULE.validate_report_dir(report_dir)

    assert "state_artifact_checksum" in _codes(result.errors)


def test_rejects_duplicate_decision_ownership(tmp_path):
    report_dir = _write_report(tmp_path)
    index_path = report_dir / "chapter-index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["chapters"][1]["decision_ids"] = ["decision:people"]
    index_path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")

    result = MODULE.validate_report_dir(report_dir)

    assert result.valid is False
    assert "decision_owner_duplicate" in _codes(result.errors)


def test_requires_formal_report_artifacts(tmp_path):
    result = MODULE.validate_report_dir(tmp_path / "missing-report")

    assert result.valid is False
    assert "chapter_index_missing" in _codes(result.errors)


def test_rejects_legacy_alternate_reader_report(tmp_path):
    report_dir = _write_report(tmp_path)
    (report_dir / "scenario-simulation.md").write_text("# 旧情景报告", encoding="utf-8")

    result = MODULE.validate_report_dir(report_dir)

    assert result.valid is False
    assert "alternate_reader_report_forbidden" in _codes(result.errors)


def test_rejects_any_unregistered_root_reader_markdown(tmp_path):
    report_dir = _write_report(tmp_path)
    (report_dir / "desktop-research-report.md").write_text("# 另一份读者报告", encoding="utf-8")

    result = MODULE.validate_report_dir(report_dir)

    assert result.valid is False
    assert "alternate_reader_report_forbidden" in _codes(result.errors)


def test_rejects_dependency_that_is_not_an_earlier_accepted_chapter(tmp_path):
    report_dir = _write_report(tmp_path)
    index_path = report_dir / "chapter-index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["chapters"][0]["dependencies"] = ["positioning-product"]
    index_path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")

    result = MODULE.validate_report_dir(report_dir)

    assert "chapter_dependency_not_prior" in _codes(result.errors)


def test_rejects_unresolved_latest_review(tmp_path):
    report_dir = _write_report(tmp_path)
    index_path = report_dir / "chapter-index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["chapters"][0]["versions"][-1]["review_status"] = "revision_required"
    index["chapters"][0]["status"] = "revision_required"
    index_path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")

    result = MODULE.validate_report_dir(report_dir)

    assert {"chapter_not_accepted", "chapter_review_status_mismatch"} <= _codes(result.errors)


def test_rejects_non_latest_accepted_version(tmp_path):
    report_dir = _write_report(tmp_path)
    index_path = report_dir / "chapter-index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["chapters"][0]["accepted_version"] = 1
    index_path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")

    result = MODULE.validate_report_dir(report_dir)

    assert "accepted_version_not_latest" in _codes(result.errors)


def test_rejects_more_than_two_rewrites(tmp_path):
    report_dir = _write_report(tmp_path)
    index_path = report_dir / "chapter-index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    chapter = index["chapters"][0]
    chapter["versions"] = chapter["versions"] * 2
    chapter["accepted_version"] = 4
    index_path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")

    result = MODULE.validate_report_dir(report_dir)

    assert "chapter_revision_limit" in _codes(result.errors)


def test_rejects_main_editor_rewriting_accepted_prose(tmp_path):
    report_dir = _write_report(tmp_path, mutate_assembly=True)

    result = MODULE.validate_report_dir(report_dir)

    assert result.valid is False
    assert "chapter_content_modified" in _codes(result.errors)


def test_allows_visual_inserted_after_chapter_boundary(tmp_path):
    report_dir = _write_report(tmp_path)
    report_path = report_dir / "project-report.md"
    report = report_path.read_text(encoding="utf-8")
    end = '<!-- chapter:end id="regional-people" -->'
    visual = '\n\n<!-- report-anchor:regional-people-visual -->\n\n![区域证据](assets/regional-people.svg)'
    report_path.write_text(report.replace(end, f"{end}{visual}", 1), encoding="utf-8")

    result = MODULE.validate_report_dir(report_dir)

    assert result.valid is True


def test_rejects_visual_inserted_inside_accepted_chapter(tmp_path):
    report_dir = _write_report(tmp_path)
    report_path = report_dir / "project-report.md"
    report = report_path.read_text(encoding="utf-8")
    end = '<!-- chapter:end id="regional-people" -->'
    visual = '<!-- report-anchor:regional-people-visual -->\n\n![区域证据](assets/regional-people.svg)\n\n'
    report_path.write_text(report.replace(end, f"{visual}{end}", 1), encoding="utf-8")

    result = MODULE.validate_report_dir(report_dir)

    assert result.valid is False
    assert "chapter_content_modified" in _codes(result.errors)


def test_rejects_orphan_chapter_end_marker(tmp_path):
    report_dir = _write_report(tmp_path)
    report_path = report_dir / "project-report.md"
    report = report_path.read_text(encoding="utf-8")
    report_path.write_text(f'{report}\n<!-- chapter:end id="orphan" -->\n', encoding="utf-8")

    result = MODULE.validate_report_dir(report_dir)

    assert "chapter_marker_unbalanced" in _codes(result.errors)


def test_length_band_is_warning_not_publication_failure(tmp_path):
    report_dir = _write_report(tmp_path, second_version=False)
    chapter_path = report_dir / "chapters" / "regional-people.v1.md"
    short = "# 区域与人群\n\n当前判断成立，但本章过短。"
    chapter_path.write_text(short, encoding="utf-8")
    index_path = report_dir / "chapter-index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["chapters"][0]["character_count"] = MODULE.content_character_count(short)
    index_path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    report_path = report_dir / "project-report.md"
    report = report_path.read_text(encoding="utf-8")
    start = '<!-- chapter:start id="regional-people" version="v1" -->'
    end = '<!-- chapter:end id="regional-people" -->'
    report = reassemble(report, start, end, short)
    report_path.write_text(report, encoding="utf-8")

    result = MODULE.validate_report_dir(report_dir)

    assert result.valid is True
    assert "chapter_below_length_band" in _codes(result.warnings)


def reassemble(report: str, start: str, end: str, body: str) -> str:
    prefix, remainder = report.split(start, 1)
    _, suffix = remainder.split(end, 1)
    return f"{prefix}{start}\n{body}\n{end}{suffix}"
