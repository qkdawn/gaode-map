#!/usr/bin/env python3
"""Validate low-loss assembly for a formal spatial business report."""
from __future__ import annotations

import argparse
import json
import re
import string
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "spatial-business-chapter-index.v1"
CHAPTER_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
START_RE = re.compile(
    r'<!--\s*chapter:start\s+id="(?P<chapter_id>[a-z0-9-]+)"\s+version="v(?P<version>[1-3])"\s*-->'
)
END_RE = re.compile(r'<!--\s*chapter:end\s+id="(?P<chapter_id>[a-z0-9-]+)"\s*-->')
ASSEMBLED_RE = re.compile(
    r'<!--\s*chapter:start\s+id="(?P<chapter_id>[a-z0-9-]+)"\s+version="v(?P<version>[1-3])"\s*-->\s*'
    r'(?P<body>.*?)\s*'
    r'<!--\s*chapter:end\s+id="(?P=chapter_id)"\s*-->',
    re.DOTALL,
)
MARKDOWN_PUNCTUATION = set(string.punctuation) | set("，。；：！？、（）【】《》“”‘’—…·")


@dataclass(frozen=True)
class Finding:
    code: str
    message: str
    chapter_id: str = ""


@dataclass
class ValidationResult:
    report_dir: str
    chapter_count: int = 0
    errors: list[Finding] = field(default_factory=list)
    warnings: list[Finding] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.errors

    def payload(self) -> dict[str, Any]:
        return {
            "status": "passed" if self.valid else "failed",
            "report_dir": self.report_dir,
            "chapter_count": self.chapter_count,
            "errors": [asdict(item) for item in self.errors],
            "warnings": [asdict(item) for item in self.warnings],
        }


def _normalized_markdown(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n").strip()


def content_character_count(markdown: str) -> int:
    """Count visible content characters without Markdown control syntax."""
    value = re.sub(r"<!--[\s\S]*?-->", "", markdown)
    value = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", value)
    value = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", value)
    value = re.sub(r"```[\s\S]*?```", "", value)
    return sum(1 for char in value if not char.isspace() and char not in MARKDOWN_PUNCTUATION)


def _safe_file(root: Path, relative_path: Any, *, code: str, result: ValidationResult, chapter_id: str) -> Path | None:
    if not isinstance(relative_path, str) or not relative_path.strip():
        result.errors.append(Finding(code, "Path must be a non-empty string.", chapter_id))
        return None
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        result.errors.append(Finding(code, "Path escapes the report directory.", chapter_id))
        return None
    if not candidate.is_file():
        result.errors.append(Finding(code, f"File does not exist: {relative_path}", chapter_id))
        return None
    return candidate


def _load_index(report_dir: Path, result: ValidationResult) -> dict[str, Any] | None:
    index_path = report_dir / "chapter-index.json"
    if not index_path.is_file():
        result.errors.append(Finding("chapter_index_missing", "Formal report is missing chapter-index.json."))
        return None
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        result.errors.append(Finding("chapter_index_invalid", f"Cannot read chapter-index.json: {exc}"))
        return None
    if not isinstance(payload, dict):
        result.errors.append(Finding("chapter_index_invalid", "chapter-index.json must contain an object."))
        return None
    if payload.get("schema_version") != SCHEMA_VERSION:
        result.errors.append(Finding("chapter_index_schema", f"schema_version must be {SCHEMA_VERSION}."))
    if payload.get("report_mode") != "formal_comprehensive":
        result.errors.append(Finding("report_mode_invalid", "report_mode must be formal_comprehensive."))
    return payload


def _validate_versions(
    report_dir: Path,
    chapter: dict[str, Any],
    chapter_id: str,
    result: ValidationResult,
) -> tuple[int | None, str | None]:
    versions = chapter.get("versions")
    if not isinstance(versions, list) or not versions:
        result.errors.append(Finding("chapter_versions_missing", "Chapter must contain at least one version.", chapter_id))
        return None, None
    if len(versions) > 3:
        result.errors.append(Finding("chapter_revision_limit", "Initial draft plus at most two rewrites are allowed.", chapter_id))
    actual_numbers = [item.get("version") for item in versions if isinstance(item, dict)]
    expected_numbers = list(range(1, len(versions) + 1))
    if actual_numbers != expected_numbers:
        result.errors.append(Finding("chapter_version_sequence", "Versions must be consecutive integers starting at 1.", chapter_id))

    accepted_version = chapter.get("accepted_version")
    if accepted_version != len(versions):
        result.errors.append(Finding("accepted_version_not_latest", "The accepted version must be the latest version.", chapter_id))
    accepted_path: str | None = None
    for position, version in enumerate(versions, 1):
        if not isinstance(version, dict):
            result.errors.append(Finding("chapter_version_invalid", "Every version entry must be an object.", chapter_id))
            continue
        expected_path = f"chapters/{chapter_id}.v{position}.md"
        expected_review = f"chapter-reviews/{chapter_id}.v{position}.md"
        if version.get("path") != expected_path:
            result.errors.append(Finding("chapter_version_path", f"Version path must be {expected_path}.", chapter_id))
        if version.get("review_path") != expected_review:
            result.errors.append(Finding("chapter_review_path", f"Review path must be {expected_review}.", chapter_id))
        _safe_file(report_dir, version.get("path"), code="chapter_file_missing", result=result, chapter_id=chapter_id)
        _safe_file(report_dir, version.get("review_path"), code="chapter_review_missing", result=result, chapter_id=chapter_id)
        expected_status = "accepted" if position == len(versions) else "revision_required"
        if version.get("review_status") != expected_status:
            result.errors.append(
                Finding("chapter_review_status", f"Version v{position} review_status must be {expected_status}.", chapter_id)
            )
        if position == accepted_version:
            accepted_path = expected_path
    return accepted_version if isinstance(accepted_version, int) else None, accepted_path


def validate_report_dir(report_dir: str | Path) -> ValidationResult:
    root = Path(report_dir).resolve()
    result = ValidationResult(report_dir=str(root))
    payload = _load_index(root, result)
    if payload is None:
        return result
    chapters = payload.get("chapters")
    if not isinstance(chapters, list) or not chapters:
        result.errors.append(Finding("chapters_missing", "Formal report must contain at least one owned chapter."))
        return result
    result.chapter_count = len(chapters)

    seen_chapters: set[str] = set()
    decision_owners: dict[str, str] = {}
    accepted: list[tuple[str, int, Path]] = []
    for index, chapter in enumerate(chapters):
        if not isinstance(chapter, dict):
            result.errors.append(Finding("chapter_invalid", "Every chapter entry must be an object."))
            continue
        chapter_id = chapter.get("chapter_id")
        if not isinstance(chapter_id, str) or not CHAPTER_ID_RE.fullmatch(chapter_id):
            result.errors.append(Finding("chapter_id_invalid", "chapter_id must be a lowercase kebab-case identifier."))
            continue
        if chapter_id in seen_chapters:
            result.errors.append(Finding("chapter_id_duplicate", "chapter_id must be unique.", chapter_id))
            continue
        seen_chapters.add(chapter_id)
        if not isinstance(chapter.get("role"), str) or not chapter["role"].strip():
            result.errors.append(Finding("chapter_role_missing", "Chapter role is required.", chapter_id))

        decision_ids = chapter.get("decision_ids")
        if not isinstance(decision_ids, list) or not decision_ids or not all(isinstance(item, str) and item for item in decision_ids):
            result.errors.append(Finding("chapter_decisions_missing", "Chapter must own at least one decision ID.", chapter_id))
        else:
            for decision_id in decision_ids:
                owner = decision_owners.get(decision_id)
                if owner is not None:
                    result.errors.append(
                        Finding("decision_owner_duplicate", f"Decision {decision_id} is already owned by {owner}.", chapter_id)
                    )
                else:
                    decision_owners[decision_id] = chapter_id

        dependencies = chapter.get("dependencies", [])
        if not isinstance(dependencies, list) or not all(isinstance(item, str) for item in dependencies):
            result.errors.append(Finding("chapter_dependencies_invalid", "dependencies must be a list of chapter IDs.", chapter_id))
        else:
            for dependency in dependencies:
                if dependency not in seen_chapters:
                    result.errors.append(
                        Finding("chapter_dependency_not_prior", f"Dependency {dependency} must be an earlier accepted chapter.", chapter_id)
                    )

        if chapter.get("status") != "accepted":
            result.errors.append(Finding("chapter_not_accepted", "Every assembled chapter must have status accepted.", chapter_id))
        accepted_version, accepted_relative = _validate_versions(root, chapter, chapter_id, result)
        if accepted_version is None or accepted_relative is None:
            continue
        accepted_path = root / accepted_relative
        if not accepted_path.is_file():
            continue
        computed_count = content_character_count(accepted_path.read_text(encoding="utf-8"))
        if chapter.get("character_count") != computed_count:
            result.errors.append(
                Finding("character_count_mismatch", f"character_count must be {computed_count} for the accepted version.", chapter_id)
            )
        if computed_count < 1500:
            result.warnings.append(
                Finding("chapter_below_length_band", f"Accepted chapter has {computed_count} content characters; expected 1500-3000.", chapter_id)
            )
        elif computed_count > 3000:
            result.warnings.append(
                Finding("chapter_above_length_band", f"Accepted chapter has {computed_count} content characters; expected 1500-3000.", chapter_id)
            )
        accepted.append((chapter_id, accepted_version, accepted_path))

    report_path = _safe_file(root, "project-report.md", code="project_report_missing", result=result, chapter_id="")
    if report_path is None:
        return result
    report_markdown = report_path.read_text(encoding="utf-8")
    start_count = len(START_RE.findall(report_markdown))
    end_count = len(END_RE.findall(report_markdown))
    assembled_matches = list(ASSEMBLED_RE.finditer(report_markdown))
    if start_count != len(assembled_matches) or end_count != len(assembled_matches):
        result.errors.append(Finding("chapter_marker_unbalanced", "Every chapter marker pair must have matching start and end IDs."))
    assembled_order: list[str] = []
    assembled_ids: set[str] = set()
    accepted_map = {chapter_id: (version, path) for chapter_id, version, path in accepted}
    for match in assembled_matches:
        chapter_id = match.group("chapter_id")
        version = int(match.group("version"))
        assembled_order.append(chapter_id)
        if chapter_id in assembled_ids:
            result.errors.append(Finding("chapter_marker_duplicate", "Chapter appears more than once in project-report.md.", chapter_id))
            continue
        assembled_ids.add(chapter_id)
        expected = accepted_map.get(chapter_id)
        if expected is None:
            result.errors.append(Finding("chapter_marker_unassigned", "Assembled chapter is not accepted by chapter-index.json.", chapter_id))
            continue
        expected_version, expected_path = expected
        if version != expected_version:
            result.errors.append(Finding("chapter_marker_version", f"Assembly must use accepted version v{expected_version}.", chapter_id))
        source = _normalized_markdown(expected_path.read_text(encoding="utf-8"))
        assembled_body = _normalized_markdown(match.group("body"))
        if assembled_body != source:
            result.errors.append(Finding("chapter_content_modified", "Accepted chapter prose was changed during assembly.", chapter_id))

    expected_order = [chapter_id for chapter_id, _, _ in accepted]
    if assembled_order != expected_order:
        result.errors.append(Finding("chapter_order_mismatch", "Assembled chapter order must match chapter-index.json."))
    for chapter_id in set(expected_order) - assembled_ids:
        result.errors.append(Finding("chapter_marker_missing", "Accepted chapter is missing from project-report.md.", chapter_id))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", required=True, help="Directory containing chapter-index.json and project-report.md")
    args = parser.parse_args()
    result = validate_report_dir(args.report_dir)
    json.dump(result.payload(), sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0 if result.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
