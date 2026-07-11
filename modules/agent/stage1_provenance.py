from __future__ import annotations

from collections import Counter
from copy import deepcopy
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from modules.documents.project_evidence import ProjectEvidenceDossier

from .schemas import AnalysisSnapshot


class ArtifactProvenance(BaseModel):
    """Authoritative identity and metadata for one selected source artifact."""

    model_config = ConfigDict(extra="forbid")

    artifact_id: str
    source_id: str
    source_kind: str
    title: str = ""
    locator: str
    metadata_origin: str
    aliases: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProvenanceDiscrepancy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    declared: Any = None
    authoritative: Any = None
    resolution: Literal["corrected", "conflicting"]


class EvidenceProvenanceBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    status: Literal["verified", "corrected", "unverifiable", "conflicting"]
    artifact_id: str = ""
    source_id: str = ""
    source_kind: str = ""
    locator: str = ""
    metadata_origin: str = ""
    matched_by: str = ""
    corrected_fields: list[str] = Field(default_factory=list)
    unverified_fields: list[str] = Field(default_factory=list)
    discrepancies: list[ProvenanceDiscrepancy] = Field(default_factory=list)
    message: str = ""


class ProvenanceBindingIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    severity: Literal["error", "warning"]
    evidence_id: str
    message: str
    repair_hint: str = ""


class Stage1ProvenanceSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["passed", "passed_with_gaps", "failed"]
    assessed_count: int = 0
    critical_evidence_ids: list[str] = Field(default_factory=list)
    status_counts: dict[str, int] = Field(default_factory=dict)
    bindings: list[EvidenceProvenanceBinding] = Field(default_factory=list)
    issues: list[ProvenanceBindingIssue] = Field(default_factory=list)

    @property
    def blocking_issues(self) -> list[ProvenanceBindingIssue]:
        return [item for item in self.issues if item.severity == "error"]


_METADATA_FIELDS = (
    "source_date",
    "analysis_date",
    "sample_size",
    "missing_count",
    "duplicate_count",
    "anomaly_count",
    "coordinate_system",
    "coordinate_transform",
    "scope_id",
)
_ANALYTIC_FIELDS = {
    "analysis_date",
    "sample_size",
    "missing_count",
    "duplicate_count",
    "anomaly_count",
    "coordinate_system",
    "coordinate_transform",
}
_SNAPSHOT_FIELDS = (
    "frontend_analysis",
    "poi_summary",
    "h3",
    "road",
    "population",
    "nightlight",
    "shared_grid",
)
_SNAPSHOT_PARAM_BUNDLES = {
    "poi_summary": ("poi_fetch", "poi_raster_grid"),
    "h3": ("poi_h3_grid",),
    "road": ("road_syntax",),
    "population": ("population",),
    "nightlight": ("nightlight",),
}
_SNAPSHOT_ALIASES = {
    "poi_summary": ("poi", "poi_summary", "POI"),
    "h3": ("h3", "H3"),
    "road": ("road", "路网", "空间句法"),
    "population": ("population", "人口"),
    "nightlight": ("nightlight", "夜光"),
    "shared_grid": ("shared_grid", "共享网格"),
    "frontend_analysis": ("frontend_analysis", "前端分析"),
}
_KEY_ALIASES = {
    "source_date": (
        "source_date",
        "publication_date",
        "published_at",
        "data_date",
        "data_year",
    ),
    "analysis_date": ("analysis_date", "computed_at", "generated_at"),
    "sample_size": ("sample_size", "record_count"),
    "missing_count": ("missing_count",),
    "duplicate_count": ("duplicate_count",),
    "anomaly_count": ("anomaly_count",),
    "coordinate_system": (
        "coordinate_system",
        "coord_type",
        "poi_coord_type",
        "crs",
        "epsg",
    ),
    "coordinate_transform": ("coordinate_transform", "transform_chain"),
    "scope_id": ("scope_id",),
}
_UNKNOWN = {
    "",
    "unknown",
    "未知",
    "未提供",
    "not_available",
    "not_applicable",
    "n/a",
    "na",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _known(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() not in _UNKNOWN
    return True


def _normalized(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip().lower()
    if isinstance(value, float):
        return round(value, 8)
    return value


def _find_value(payload: Any, keys: tuple[str, ...]) -> Any:
    if not isinstance(payload, dict):
        return None
    for key in keys:
        value = payload.get(key)
        if _known(value):
            return value
    for value in payload.values():
        if isinstance(value, dict):
            found = _find_value(value, keys)
            if _known(found):
                return found
    return None


def _metadata(payload: dict[str, Any], *, snapshot_field: str = "") -> dict[str, Any]:
    values = {
        field: _find_value(payload, aliases) for field, aliases in _KEY_ALIASES.items()
    }
    if snapshot_field == "road" and not _known(values.get("sample_size")):
        values["sample_size"] = _find_value(payload, ("node_count", "edge_count", "n"))
    elif snapshot_field == "h3" and not _known(values.get("sample_size")):
        values["sample_size"] = _find_value(payload, ("grid_count", "cell_count"))
    elif snapshot_field == "poi_summary" and not _known(values.get("sample_size")):
        values["sample_size"] = _find_value(payload, ("total", "poi_count", "count"))
    elif snapshot_field == "population" and not _known(values.get("sample_size")):
        values["sample_size"] = _find_value(payload, ("grid_count", "cell_count"))
    elif snapshot_field == "nightlight" and not _known(values.get("sample_size")):
        values["sample_size"] = _find_value(payload, ("cell_count", "grid_count"))
    return {key: value for key, value in values.items() if _known(value)}


def _snapshot_metadata(
    snapshot: AnalysisSnapshot,
    *,
    field: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Merge real execution parameters into one snapshot artifact before extraction."""

    bundle_payloads: dict[str, dict[str, Any]] = {}
    for key in _SNAPSHOT_PARAM_BUNDLES.get(field, ()):
        bundle = snapshot.param_bundles.get(key)
        if isinstance(bundle, dict):
            bundle_payloads[key] = bundle
    combined = {"snapshot": payload, "param_bundles": bundle_payloads}
    metadata = _metadata(combined, snapshot_field=field)
    if not _known(metadata.get("source_date")):
        year_keys = (
            ("poi_year", "year") if field in {"poi_summary", "h3"} else ("year",)
        )
        years = {
            _text(value)
            for bundle in bundle_payloads.values()
            if _known(value := _find_value(bundle, year_keys))
        }
        if len(years) == 1:
            metadata["source_date"] = years.pop()
    return metadata


def _document_page_aliases(page_start: int | None, page_end: int | None) -> list[str]:
    if not page_start:
        return []
    end = page_end or page_start
    if end == page_start:
        return [f"p.{page_start}", f"page {page_start}", f"第{page_start}页"]
    return [
        f"p.{page_start}-{end}",
        f"page {page_start}-{end}",
        f"第{page_start}-{end}页",
    ]


def _aliases(*values: Any) -> list[str]:
    results: list[str] = []
    for value in values:
        normalized = _text(value)
        if normalized and normalized not in results:
            results.append(normalized)
    return results


def build_provenance_registry(
    *,
    selected_sources: list[dict[str, Any]],
    snapshot: AnalysisSnapshot,
    dossier: ProjectEvidenceDossier | None = None,
) -> list[ArtifactProvenance]:
    """Build one backend-owned registry from selected source transport and real artifacts."""

    records: list[ArtifactProvenance] = []
    if dossier is not None:
        for item in dossier.evidence:
            records.append(
                ArtifactProvenance(
                    artifact_id=item.id,
                    source_id=item.source_id,
                    source_kind="document",
                    title=item.document_title,
                    locator=item.locator,
                    metadata_origin="project_evidence_dossier",
                    aliases=_aliases(
                        item.id,
                        item.node_id,
                        item.source_id,
                        item.locator,
                        item.citation,
                        item.document_title,
                        *_document_page_aliases(item.page_start, item.page_end),
                    ),
                    metadata={},
                )
            )

    for source in selected_sources:
        if not isinstance(source, dict):
            continue
        source_id = _text(source.get("source_id"))
        if not source_id or source_id.startswith("document:"):
            continue
        source_kind = _text(source.get("source_kind")) or "analysis_source"
        title = _text(source.get("title"))
        locator = f"selected_sources_context.sources[{source_id}]"
        records.append(
            ArtifactProvenance(
                artifact_id=source_id,
                source_id=source_id,
                source_kind=source_kind,
                title=title,
                locator=locator,
                metadata_origin="selected_sources_context",
                aliases=_aliases(source_id, title),
                metadata=_metadata(source),
            )
        )
        evidence_nodes = source.get("evidence_nodes")
        if not isinstance(evidence_nodes, list):
            continue
        for index, node in enumerate(evidence_nodes):
            if not isinstance(node, dict):
                continue
            artifact_id = _text(node.get("id"))
            if not artifact_id:
                continue
            records.append(
                ArtifactProvenance(
                    artifact_id=artifact_id,
                    source_id=source_id,
                    source_kind=source_kind,
                    title=_text(node.get("title")) or title,
                    locator=f"{locator}.evidence_nodes[{index}]",
                    metadata_origin="selected_sources_context.evidence_nodes",
                    aliases=_aliases(
                        artifact_id,
                        source_id,
                        node.get("source_id"),
                        node.get("title"),
                    ),
                    metadata={**_metadata(source), **_metadata(node)},
                )
            )

    for field in _SNAPSHOT_FIELDS:
        payload = getattr(snapshot, field, None)
        if not payload:
            continue
        artifact_id = f"analysis_snapshot.{field}"
        records.append(
            ArtifactProvenance(
                artifact_id=artifact_id,
                source_id=artifact_id,
                source_kind="analysis_snapshot",
                title=field,
                locator=artifact_id,
                metadata_origin=artifact_id,
                aliases=_aliases(
                    artifact_id,
                    field,
                    *_SNAPSHOT_ALIASES.get(field, ()),
                ),
                metadata=_snapshot_metadata(snapshot, field=field, payload=payload),
            )
        )
    return records


def provenance_registry_payload(
    registry: list[ArtifactProvenance], *, limit: int = 80
) -> list[dict[str, Any]]:
    """Compact registry contract shown to the evidence-building model."""

    return [
        {
            "artifact_id": item.artifact_id,
            "source_id": item.source_id,
            "source_kind": item.source_kind,
            "title": item.title,
            "locator": item.locator,
            "metadata_origin": item.metadata_origin,
            "metadata": deepcopy(item.metadata),
        }
        for item in registry[:limit]
    ]


def project_evidence_payload(
    dossier: ProjectEvidenceDossier | None, *, limit: int = 28
) -> list[dict[str, Any]]:
    if dossier is None:
        return []
    return [
        {
            "artifact_id": item.id,
            "source_id": item.source_id,
            "document_role": item.document_role.value,
            "status": item.status.value,
            "category": item.category,
            "title": item.title,
            "content": item.content[:800],
            "node_id": item.node_id,
            "locator": item.locator,
            "citation": item.citation,
        }
        for item in dossier.evidence[:limit]
    ]


def _match_score(source_ref: str, record: ArtifactProvenance) -> tuple[int, int, int]:
    normalized_ref = source_ref.lower().replace(" ", "")
    aliases = {
        alias.lower().replace(" ", "")
        for alias in record.aliases
        if len(alias.strip()) >= 3
    }
    matched = {alias for alias in aliases if alias in normalized_ref}
    if not matched:
        return (0, 0, 0)
    return (
        max(len(alias) for alias in matched),
        sum(len(alias) for alias in matched),
        len(matched),
    )


def _match_records(
    node: dict[str, Any], registry: list[ArtifactProvenance]
) -> tuple[list[ArtifactProvenance], str]:
    artifact_id = _text(node.get("source_artifact_id"))
    source_ref = _text(node.get("source_ref"))
    if artifact_id:
        exact_identity = [item for item in registry if artifact_id == item.artifact_id]
        if exact_identity:
            return exact_identity, "source_artifact_id"
        alias_matches = [item for item in registry if artifact_id in item.aliases]
        if alias_matches:
            return alias_matches, "source_artifact_id"
    if source_ref:
        scored = [(item, _match_score(source_ref, item)) for item in registry]
        best_score = max((score for _, score in scored), default=(0, 0, 0))
        if best_score != (0, 0, 0):
            return [item for item, score in scored if score == best_score], "source_ref"
    return [], ""


def _records_conflict(records: list[ArtifactProvenance]) -> bool:
    if len(records) <= 1:
        return False
    for field in _METADATA_FIELDS:
        values = {
            _normalized(item.metadata.get(field))
            for item in records
            if _known(item.metadata.get(field))
        }
        if len(values) > 1:
            return True
    return len({item.locator for item in records}) > 1


def _preferred_record(
    records: list[ArtifactProvenance], artifact_id: str
) -> ArtifactProvenance:
    return next(
        (item for item in records if artifact_id == item.artifact_id),
        records[0],
    )


def bind_evidence_to_artifacts(
    ledger: list[dict[str, Any]],
    *,
    registry: list[ArtifactProvenance],
) -> tuple[list[dict[str, Any]], list[EvidenceProvenanceBinding]]:
    """Bind model claims to authoritative artifacts and correct disagreeing metadata."""

    normalized: list[dict[str, Any]] = []
    bindings: list[EvidenceProvenanceBinding] = []
    for index, raw in enumerate(ledger):
        node = deepcopy(raw) if isinstance(raw, dict) else {}
        evidence_id = _text(node.get("id")) or f"evidence-{index + 1}"
        node["id"] = evidence_id
        matches, matched_by = _match_records(node, registry)
        if not matches:
            unverified_fields = [
                field
                for field in (*_METADATA_FIELDS, "source_locator")
                if _known(node.get(field))
            ]
            binding = EvidenceProvenanceBinding(
                evidence_id=evidence_id,
                status="unverifiable",
                matched_by="",
                unverified_fields=unverified_fields,
                message="未能在本轮真实文档节点或分析快照中定位该来源。",
            )
        elif _records_conflict(matches):
            discrepancies: list[ProvenanceDiscrepancy] = []
            for field in _METADATA_FIELDS:
                values = [
                    item.metadata.get(field)
                    for item in matches
                    if _known(item.metadata.get(field))
                ]
                if len({_normalized(value) for value in values}) > 1:
                    discrepancies.append(
                        ProvenanceDiscrepancy(
                            field=field,
                            declared=node.get(field),
                            authoritative=values,
                            resolution="conflicting",
                        )
                    )
            metadata_conflict = bool(discrepancies)
            unverified_fields = [
                field
                for field in (*_METADATA_FIELDS, "source_locator")
                if _known(node.get(field))
            ]
            binding = EvidenceProvenanceBinding(
                evidence_id=evidence_id,
                status="conflicting",
                matched_by=matched_by,
                unverified_fields=unverified_fields,
                discrepancies=discrepancies,
                message=(
                    "多个真实数据资产对同一证据提供了不一致的元数据。"
                    if metadata_conflict
                    else "来源引用同时匹配到多个真实数据资产，无法确定唯一定位。"
                ),
            )
        else:
            artifact_id = _text(node.get("source_artifact_id"))
            record = _preferred_record(matches, artifact_id)
            corrected_fields: list[str] = []
            discrepancies = []
            declared_artifact_id = artifact_id
            if declared_artifact_id != record.artifact_id:
                node["source_artifact_id"] = record.artifact_id
                corrected_fields.append("source_artifact_id")
                discrepancies.append(
                    ProvenanceDiscrepancy(
                        field="source_artifact_id",
                        declared=declared_artifact_id,
                        authoritative=record.artifact_id,
                        resolution="corrected",
                    )
                )
            declared_locator = node.get("source_locator")
            if _normalized(declared_locator) != _normalized(record.locator):
                node["source_locator"] = record.locator
                corrected_fields.append("source_locator")
                discrepancies.append(
                    ProvenanceDiscrepancy(
                        field="source_locator",
                        declared=declared_locator,
                        authoritative=record.locator,
                        resolution="corrected",
                    )
                )
            unverified_fields: list[str] = []
            for field in _METADATA_FIELDS:
                authoritative = record.metadata.get(field)
                declared = node.get(field)
                if _known(authoritative):
                    if _normalized(declared) != _normalized(authoritative):
                        node[field] = authoritative
                        corrected_fields.append(field)
                        discrepancies.append(
                            ProvenanceDiscrepancy(
                                field=field,
                                declared=declared,
                                authoritative=authoritative,
                                resolution="corrected",
                            )
                        )
                elif _known(declared):
                    unverified_fields.append(field)
            binding = EvidenceProvenanceBinding(
                evidence_id=evidence_id,
                status="corrected" if corrected_fields else "verified",
                artifact_id=record.artifact_id,
                source_id=record.source_id,
                source_kind=record.source_kind,
                locator=record.locator,
                metadata_origin=record.metadata_origin,
                matched_by=matched_by,
                corrected_fields=sorted(set(corrected_fields)),
                unverified_fields=sorted(set(unverified_fields)),
                discrepancies=discrepancies,
                message=(
                    "已按真实数据资产修正来源声明。"
                    if corrected_fields
                    else "来源声明已绑定到真实数据资产。"
                ),
            )
        node["provenance_binding_status"] = binding.status
        node["provenance_unverified_fields"] = list(binding.unverified_fields)
        normalized.append(node)
        bindings.append(binding)
    return normalized, bindings


def assess_provenance_bindings(
    bindings: list[EvidenceProvenanceBinding],
    *,
    critical_evidence_ids: set[str] | None = None,
) -> Stage1ProvenanceSummary:
    critical_ids = {item for item in (critical_evidence_ids or set()) if item}
    issues: list[ProvenanceBindingIssue] = []
    for binding in bindings:
        critical = binding.evidence_id in critical_ids
        if binding.status == "unverifiable":
            issues.append(
                ProvenanceBindingIssue(
                    code="artifact_unverifiable",
                    severity="error" if critical else "warning",
                    evidence_id=binding.evidence_id,
                    message=f"证据 {binding.evidence_id} 无法绑定到真实数据资产。",
                    repair_hint="选择可读取的文档节点或先运行对应分析，并重新生成证据台账。",
                )
            )
        elif binding.status == "conflicting":
            metadata_conflict = bool(binding.discrepancies)
            issues.append(
                ProvenanceBindingIssue(
                    code=(
                        "artifact_metadata_conflicting"
                        if metadata_conflict
                        else "artifact_binding_ambiguous"
                    ),
                    severity="error" if critical else "warning",
                    evidence_id=binding.evidence_id,
                    message=(
                        f"证据 {binding.evidence_id} 匹配到相互冲突的数据资产元数据。"
                        if metadata_conflict
                        else f"证据 {binding.evidence_id} 的来源引用无法确定唯一数据资产。"
                    ),
                    repair_hint=(
                        "指定唯一 artifact ID，或先统一来源日期、样本和坐标口径。"
                        if metadata_conflict
                        else "使用 PageIndex node ID、精确页码或唯一 artifact ID 重建证据引用。"
                    ),
                )
            )
        elif binding.status == "corrected":
            issues.append(
                ProvenanceBindingIssue(
                    code="artifact_declaration_corrected",
                    severity="warning",
                    evidence_id=binding.evidence_id,
                    message=(
                        f"证据 {binding.evidence_id} 的来源声明已按真实资产修正："
                        f"{'、'.join(binding.corrected_fields)}。"
                    ),
                    repair_hint="检查模型提示和数据资产元数据，减少后续自动修正。",
                )
            )
        if binding.unverified_fields:
            issues.append(
                ProvenanceBindingIssue(
                    code="artifact_metadata_unverified",
                    severity="error" if critical else "warning",
                    evidence_id=binding.evidence_id,
                    message=(
                        f"证据 {binding.evidence_id} 的以下声明无法由真实资产确认："
                        f"{'、'.join(binding.unverified_fields)}。"
                    ),
                    repair_hint="把来源日期、分析日期、样本和坐标元数据写入实际 artifact，而不是仅由模型声明。",
                )
            )
    blocking = any(item.severity == "error" for item in issues)
    status_counts = dict(sorted(Counter(item.status for item in bindings).items()))
    return Stage1ProvenanceSummary(
        status="failed" if blocking else ("passed_with_gaps" if issues else "passed"),
        assessed_count=len(bindings),
        critical_evidence_ids=sorted(critical_ids),
        status_counts=status_counts,
        bindings=bindings,
        issues=issues,
    )
