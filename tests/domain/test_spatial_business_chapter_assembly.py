from __future__ import annotations

import importlib.util
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


def _write_report(tmp_path: Path, *, second_version: bool = True, mutate_assembly: bool = False) -> Path:
    report_dir = tmp_path / "report"
    chapters_dir = report_dir / "chapters"
    reviews_dir = report_dir / "chapter-reviews"
    chapters_dir.mkdir(parents=True)
    reviews_dir.mkdir()

    first_v1 = "# 区域与人群\n\n" + "区域证据改变使用场景。" * 170
    first_v2 = "# 区域与人群\n\n" + "区域证据通过日常使用机制改变产品时段。" * 130
    positioning = "# 定位与产品\n\n" + "文化生活方向的相对优势来自项目特有资产与使用关系。" * 100
    (chapters_dir / "regional-people.v1.md").write_text(first_v1, encoding="utf-8")
    (reviews_dir / "regional-people.v1.md").write_text("需要解释机制并返写。", encoding="utf-8")
    versions = [
        {
            "version": 1,
            "path": "chapters/regional-people.v1.md",
            "review_path": "chapter-reviews/regional-people.v1.md",
            "review_status": "revision_required" if second_version else "accepted",
        }
    ]
    accepted_first = first_v1
    accepted_version = 1
    if second_version:
        (chapters_dir / "regional-people.v2.md").write_text(first_v2, encoding="utf-8")
        (reviews_dir / "regional-people.v2.md").write_text("accepted", encoding="utf-8")
        versions.append(
            {
                "version": 2,
                "path": "chapters/regional-people.v2.md",
                "review_path": "chapter-reviews/regional-people.v2.md",
                "review_status": "accepted",
            }
        )
        accepted_first = first_v2
        accepted_version = 2
    (chapters_dir / "positioning-product.v1.md").write_text(positioning, encoding="utf-8")
    (reviews_dir / "positioning-product.v1.md").write_text("accepted", encoding="utf-8")

    index = {
        "schema_version": MODULE.SCHEMA_VERSION,
        "report_mode": "formal_comprehensive",
        "chapters": [
            {
                "chapter_id": "regional-people",
                "role": "区域与人群分析师",
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
                "versions": [
                    {
                        "version": 1,
                        "path": "chapters/positioning-product.v1.md",
                        "review_path": "chapter-reviews/positioning-product.v1.md",
                        "review_status": "accepted",
                    }
                ],
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

    assert {"chapter_not_accepted", "chapter_review_status"} <= _codes(result.errors)


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
