#!/usr/bin/env python3
"""Validate low-loss assembly for a formal spatial business report."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import string
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


CHAPTER_INDEX_SCHEMA = "spatial-business-chapter-index"
STATE_MANIFEST_SCHEMA = "spatial-business-state-manifest"
STATE_MANIFEST_PATH = "state/manifest.json"
STATE_ARTIFACTS = {
    "project_semantic_model": {
        "path": "state/project-semantic-model.json",
        "schema": "spatial-business-project-semantic-model",
    },
    "problem_map": {
        "path": "state/problem-map.json",
        "schema": "spatial-business-problem-map",
    },
    "decision_logic_map": {
        "path": "state/decision-logic-map.json",
        "schema": "spatial-business-decision-logic-map",
    },
    "decision_inventory": {
        "path": "state/decision-inventory.json",
        "schema": "spatial-business-decision-inventory",
    },
    "evidence_summary": {
        "path": "state/evidence-summary.json",
        "schema": "spatial-business-evidence-summary",
    },
}
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
    if "schema_version" in payload:
        result.errors.append(Finding("chapter_index_legacy_schema", "schema_version is not part of the current contract."))
    if payload.get("schema") != CHAPTER_INDEX_SCHEMA:
        result.errors.append(Finding("chapter_index_schema", f"schema must be {CHAPTER_INDEX_SCHEMA}."))
    if payload.get("report_mode") != "formal_comprehensive":
        result.errors.append(Finding("report_mode_invalid", "report_mode must be formal_comprehensive."))
    return payload


def _is_iso_datetime(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _validate_state(report_dir: Path, payload: dict[str, Any], result: ValidationResult) -> None:
    """Validate the resumable state bundle and its content-addressed manifest."""
    manifest_ref = payload.get("state_manifest")
    if manifest_ref is None:
        result.errors.append(Finding("state_manifest_reference_missing", "chapter-index.json must declare state_manifest."))
        return
    if manifest_ref != STATE_MANIFEST_PATH:
        result.errors.append(Finding("state_manifest_path", f"state_manifest must be {STATE_MANIFEST_PATH}."))
        return
    manifest_path = _safe_file(report_dir, manifest_ref, code="state_manifest_missing", result=result, chapter_id="")
    if manifest_path is None:
        return
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        result.errors.append(Finding("state_manifest_invalid", f"Cannot read state manifest: {exc}"))
        return
    if not isinstance(manifest, dict):
        result.errors.append(Finding("state_manifest_invalid", "State manifest must contain an object."))
        return
    if "schema_version" in manifest or "state_version" in manifest:
        result.errors.append(Finding("state_manifest_legacy_version", "schema_version and state_version are not part of the current contract."))
    if manifest.get("schema") != STATE_MANIFEST_SCHEMA:
        result.errors.append(Finding("state_manifest_schema", f"schema must be {STATE_MANIFEST_SCHEMA}."))
    snapshot_version = manifest.get("snapshot_version")
    if not isinstance(snapshot_version, int) or isinstance(snapshot_version, bool) or snapshot_version < 1:
        result.errors.append(Finding("state_snapshot_version", "snapshot_version must be a positive integer."))
        snapshot_version = None
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != set(STATE_ARTIFACTS):
        result.errors.append(Finding("state_artifacts_missing", "State manifest must list the five required state artifacts."))
        return
    for state_id, contract in STATE_ARTIFACTS.items():
        entry = artifacts.get(state_id)
        if not isinstance(entry, dict):
            result.errors.append(Finding("state_artifact_invalid", f"Manifest entry {state_id} must be an object."))
            continue
        if entry.get("path") != contract["path"]:
            result.errors.append(Finding("state_artifact_path", f"{state_id} path must be {contract['path']}."))
        if "schema_version" in entry or "state_version" in entry:
            result.errors.append(Finding("state_artifact_legacy_version", f"{state_id} manifest entry uses legacy version fields."))
        if entry.get("schema") != contract["schema"]:
            result.errors.append(Finding("state_artifact_schema", f"{state_id} schema is invalid."))
        if entry.get("snapshot_version") != snapshot_version:
            result.errors.append(Finding("state_artifact_snapshot", f"{state_id} snapshot_version must match the manifest."))
        artifact_path = _safe_file(report_dir, entry.get("path"), code="state_artifact_missing", result=result, chapter_id="")
        if artifact_path is None:
            continue
        digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        if entry.get("sha256") != digest:
            result.errors.append(Finding("state_artifact_checksum", f"{state_id} checksum does not match its file."))
        try:
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            result.errors.append(Finding("state_artifact_invalid", f"Cannot read {state_id}: {exc}"))
            continue
        if not isinstance(artifact, dict) or artifact.get("state_id") != state_id:
            result.errors.append(Finding("state_artifact_identity", f"{state_id} must declare its state_id."))
        if isinstance(artifact, dict) and ("schema_version" in artifact or "state_version" in artifact):
            result.errors.append(Finding("state_artifact_legacy_version", f"{state_id} uses legacy version fields."))
        if isinstance(artifact, dict) and artifact.get("schema") != contract["schema"]:
            result.errors.append(Finding("state_artifact_schema", f"{state_id} schema is invalid."))
        if isinstance(artifact, dict) and artifact.get("snapshot_version") != snapshot_version:
            result.errors.append(Finding("state_artifact_snapshot", f"{state_id} snapshot_version must match the manifest."))
        if isinstance(artifact, dict) and not _is_iso_datetime(artifact.get("updated_at")):
            result.errors.append(Finding("state_artifact_updated_at", f"{state_id} updated_at must be an ISO-8601 timestamp."))
        if not isinstance(artifact, dict) or not isinstance(artifact.get("payload"), dict):
            result.errors.append(Finding("state_artifact_payload", f"{state_id} must contain an object payload."))
        if state_id == "problem_map" and isinstance(artifact, dict) and isinstance(artifact.get("payload"), dict):
            if artifact["payload"].get("status") != "confirmed":
                result.errors.append(Finding("problem_map_not_confirmed", "Formal assembly requires a confirmed problem map."))
        if state_id == "decision_logic_map" and isinstance(artifact, dict) and isinstance(artifact.get("payload"), dict):
            _validate_decision_logic_map(artifact["payload"], result)


def _validate_decision_logic_map(payload: dict[str, Any], result: ValidationResult) -> None:
    if payload.get("status") != "ready":
        result.errors.append(Finding("decision_logic_map_not_ready", "Formal assembly requires a ready decision logic map."))
    rules = payload.get("rules")
    if not isinstance(rules, list) or not rules:
        result.errors.append(Finding("decision_logic_rules_missing", "Decision logic map must contain at least one rule."))
        return
    required_fields = {
        "id": str,
        "decision_question": str,
        "judgment": str,
        "action": str,
        "counterexample": str,
        "validation": str,
        "status": str,
    }
    valid_statuses = {"supported", "conditional", "excluded"}
    for rule in rules:
        if not isinstance(rule, dict):
            result.errors.append(Finding("decision_logic_rule_invalid", "Every decision logic rule must be an object."))
            continue
        for field_name, field_type in required_fields.items():
            if not isinstance(rule.get(field_name), field_type) or not rule[field_name].strip():
                result.errors.append(Finding("decision_logic_rule_invalid", f"Rule field {field_name} must be a non-empty string."))
        for field_name in ("when", "alternatives", "evidence_refs", "limitations"):
            if not isinstance(rule.get(field_name), list):
                result.errors.append(Finding("decision_logic_rule_invalid", f"Rule field {field_name} must be a list."))
        if isinstance(rule.get("when"), list) and not rule["when"]:
            result.errors.append(Finding("decision_logic_rule_invalid", "Rule field when must contain at least one condition."))
        if rule.get("status") not in valid_statuses:
            result.errors.append(Finding("decision_logic_rule_invalid", "Rule status is invalid."))
        metric_refs = rule.get("metric_refs", [])
        if not isinstance(metric_refs, list):
            result.errors.append(Finding("decision_logic_rule_invalid", "Rule field metric_refs must be a list when present."))
            continue
        for metric_ref in metric_refs:
            required_metric_fields = ("result_id", "tool_id", "observation", "comparison_basis", "decision_effect", "does_not_prove")
            if not isinstance(metric_ref, dict) or any(
                not isinstance(metric_ref.get(field_name), str) or not metric_ref[field_name].strip()
                for field_name in required_metric_fields
            ):
                result.errors.append(Finding("decision_logic_metric_invalid", "Metric references must declare provenance, effect and inference boundary."))


REVIEW_FRONTMATTER_RE = re.compile(r"\A---\s*\n(?P<meta>.*?)\n---\s*\n(?P<body>.*)\Z", re.DOTALL)
REVIEW_META_RE = re.compile(r"^(?P<key>[a-z_]+):\s*(?P<value>[^\s].*)$")
REVIEW_TYPES = {"adversarial", "depth"}
REVIEW_VERDICTS = {"accepted", "revision_required"}


def _validate_review(review_path: Path, chapter_id: str, expected_type: str, result: ValidationResult) -> str | None:
    """Validate a typed review artifact and return its content-derived verdict."""
    try:
        content = review_path.read_text(encoding="utf-8")
    except OSError as exc:
        result.errors.append(Finding("chapter_review_invalid", f"Cannot read review: {exc}", chapter_id))
        return None
    match = REVIEW_FRONTMATTER_RE.fullmatch(_normalized_markdown(content))
    if match is None:
        result.errors.append(Finding("chapter_review_metadata_missing", "Review must contain strict Markdown frontmatter.", chapter_id))
        return None
    metadata: dict[str, str] = {}
    for line in match.group("meta").splitlines():
        meta_match = REVIEW_META_RE.fullmatch(line.strip())
        if meta_match is None or meta_match.group("key") in metadata:
            result.errors.append(Finding("chapter_review_metadata_invalid", "Review frontmatter must contain unique key-value lines.", chapter_id))
            return None
        metadata[meta_match.group("key")] = meta_match.group("value").strip()
    if set(metadata) != {"review_type", "verdict"}:
        result.errors.append(Finding("chapter_review_metadata_invalid", "Review frontmatter must contain only review_type and verdict.", chapter_id))
        return None
    review_type = metadata["review_type"]
    verdict = metadata["verdict"]
    if review_type not in REVIEW_TYPES or review_type != expected_type:
        result.errors.append(Finding("chapter_review_type", f"Review type must be {expected_type}.", chapter_id))
    if verdict not in REVIEW_VERDICTS:
        result.errors.append(Finding("chapter_review_verdict", "Review verdict must be accepted or revision_required.", chapter_id))
        verdict = None
    if content_character_count(match.group("body")) < 20:
        result.errors.append(Finding("chapter_review_rationale_missing", "Review needs at least 20 substantive content characters.", chapter_id))
    return verdict


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
        expected_adversarial_review = f"chapter-reviews/{chapter_id}.v{position}.adversarial.md"
        expected_depth_review = f"chapter-reviews/{chapter_id}.v{position}.depth.md"
        if version.get("path") != expected_path:
            result.errors.append(Finding("chapter_version_path", f"Version path must be {expected_path}.", chapter_id))
        if "review_path" in version:
            result.errors.append(Finding("chapter_review_contract_legacy", "review_path is not valid in the v2 contract.", chapter_id))
        if version.get("adversarial_review_path") != expected_adversarial_review:
            result.errors.append(
                Finding("chapter_adversarial_review_path", f"Adversarial review path must be {expected_adversarial_review}.", chapter_id)
            )
        if version.get("depth_review_path") != expected_depth_review:
            result.errors.append(Finding("chapter_depth_review_path", f"Depth review path must be {expected_depth_review}.", chapter_id))
        _safe_file(report_dir, version.get("path"), code="chapter_file_missing", result=result, chapter_id=chapter_id)
        adversarial_file = _safe_file(
            report_dir,
            version.get("adversarial_review_path"),
            code="chapter_adversarial_review_missing",
            result=result,
            chapter_id=chapter_id,
        )
        depth_file = _safe_file(
            report_dir,
            version.get("depth_review_path"),
            code="chapter_depth_review_missing",
            result=result,
            chapter_id=chapter_id,
        )
        adversarial_verdict = (
            _validate_review(adversarial_file, chapter_id, "adversarial", result) if adversarial_file is not None else None
        )
        depth_verdict = _validate_review(depth_file, chapter_id, "depth", result) if depth_file is not None else None
        computed_status = "accepted" if adversarial_verdict == depth_verdict == "accepted" else "revision_required"
        expected_status = "accepted" if position == len(versions) else "revision_required"
        if version.get("review_status") != computed_status:
            result.errors.append(
                Finding("chapter_review_status_mismatch", f"Version v{position} review_status must match the two review verdicts.", chapter_id)
            )
        if computed_status != expected_status:
            result.errors.append(Finding("chapter_review_status", f"Version v{position} review status must be {expected_status}.", chapter_id))
        if position == accepted_version:
            accepted_path = expected_path
    return accepted_version if isinstance(accepted_version, int) else None, accepted_path


def validate_report_dir(report_dir: str | Path) -> ValidationResult:
    root = Path(report_dir).resolve()
    result = ValidationResult(report_dir=str(root))
    payload = _load_index(root, result)
    if payload is None:
        return result
    _validate_state(root, payload, result)
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
