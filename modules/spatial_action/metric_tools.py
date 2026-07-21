from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from modules.spatial_action.arcgis_spatial_tools import ArcGISSpatialToolModule
from modules.spatial_action.project_context import ProjectSpatialAnalysisService
from modules.spatial_action.source_index import SourceIndex, SourceIndexItem
from store.artifact_identity import content_digest

ROOT = Path(__file__).resolve().parents[2]
CATALOG_INDEX = ROOT / "skills" / "spatial-business-analyst" / "references" / "metric-catalog-index.yaml"
CATALOG_DETAIL = ROOT / "skills" / "spatial-business-analyst" / "references" / "metric-catalog.yaml"


def _mapping(value: Any) -> dict[str, Any]:
    return deepcopy(value) if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


class MetricCatalogItem(BaseModel):
    """The only lightweight tool-discovery contract seen at chapter start."""

    model_config = ConfigDict(extra="forbid")
    tool_id: str
    name: str
    purpose: str
    question_tags: list[str] = Field(default_factory=list)
    primary_spatial_unit: str
    action_targets: list[str] = Field(default_factory=list)
    implementation_status: Literal["implemented", "not_implemented"]


class MetricMeasures(BaseModel):
    """What this metric actually observes; keeps names from becoming conclusions."""

    model_config = ConfigDict(extra="forbid")
    definition: str
    unit: str
    outputs: list[str] = Field(default_factory=list)
    calculation: str = ""
    spatial_units: list[str] = Field(default_factory=list)
    time_semantics: str = ""
    method_version: str = ""


class MetricUseFor(BaseModel):
    """Decision contexts in which a metric is useful before a project is operating."""

    model_config = ConfigDict(extra="forbid")
    decision_questions: list[str] = Field(default_factory=list)
    action_targets: list[str] = Field(default_factory=list)
    b2c: list[str] = Field(default_factory=list)
    b2b: list[str] = Field(default_factory=list)
    mixed: list[str] = Field(default_factory=list)


class MetricCompareBy(BaseModel):
    """The default project-internal comparison design for an indicator."""

    model_config = ConfigDict(extra="forbid")
    candidate_targets: str
    area_units: str
    normalization: str
    consistency_rules: list[str] = Field(default_factory=list)


class MetricInterpretWith(BaseModel):
    """Complementary evidence combinations, not a single proxy-score recipe."""

    model_config = ConfigDict(extra="forbid")
    combinations: list[str] = Field(default_factory=list)
    conflict_prompts: list[str] = Field(default_factory=list)


class MetricWatchOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    risks: list[str] = Field(default_factory=list)
    field_checks: list[str] = Field(default_factory=list)


class MetricDetail(BaseModel):
    """Analysis card returned only after a tool is relevant to the decision."""

    model_config = ConfigDict(extra="forbid")
    tool_id: str
    name: str
    measures: MetricMeasures
    use_for: MetricUseFor
    compare_by: MetricCompareBy
    interpret_with: MetricInterpretWith
    watch_out: MetricWatchOut
    unavailable_semantics: str
    asset_types: list[str] = Field(default_factory=list)


class MetricResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    result_id: str
    tool_id: str
    tool_version: str
    status: Literal["available", "unavailable", "failed"]
    summary: str
    structured_result: dict[str, Any] = Field(default_factory=dict)
    input_sources: list[str] = Field(default_factory=list)
    spatial_scope: dict[str, Any] = Field(default_factory=dict)
    time_scope: dict[str, Any] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
    asset_ids: list[str] = Field(default_factory=list)

class MetricToolService:
    """Deep module for catalog discovery, detail lookup, result reuse and execution."""

    def __init__(
        self,
        *,
        spatial_service: ProjectSpatialAnalysisService | None = None,
        visual_tools: ArcGISSpatialToolModule | None = None,
    ) -> None:
        self._spatial_service = spatial_service or ProjectSpatialAnalysisService()
        self._visual_tools = visual_tools or ArcGISSpatialToolModule()
        self._catalog = self._load_catalog()
        self._details = self._load_details()
        self._validate_analysis_cards()

    @staticmethod
    def _load_catalog() -> dict[str, MetricCatalogItem]:
        raw = yaml.safe_load(CATALOG_INDEX.read_text(encoding="utf-8")) or {}
        metrics = raw.get("metrics")
        if not isinstance(metrics, list):
            raise ValueError("metric_catalog_index_requires_metrics")
        catalog: dict[str, MetricCatalogItem] = {}
        for value in metrics:
            item = MetricCatalogItem.model_validate(value)
            if item.tool_id in catalog:
                raise ValueError(f"duplicate_metric_tool:{item.tool_id}")
            catalog[item.tool_id] = item
        if not catalog:
            raise ValueError("metric_catalog_index_is_empty")
        return catalog

    @staticmethod
    def _load_details() -> dict[str, dict[str, Any]]:
        raw = yaml.safe_load(CATALOG_DETAIL.read_text(encoding="utf-8")) or {}
        metrics = raw.get("metrics")
        if not isinstance(metrics, list):
            raise ValueError("metric_catalog_detail_requires_metrics")
        details: dict[str, dict[str, Any]] = {}
        for value in metrics:
            if not isinstance(value, dict):
                continue
            tool_id = str(value.get("id") or "").strip()
            if tool_id:
                details[tool_id] = deepcopy(value)
        return details

    def catalog(self) -> list[MetricCatalogItem]:
        catalog = [item.model_copy(deep=True) for _, item in sorted(self._catalog.items())]
        for item in catalog:
            if item.tool_id in {"spatial.thematic_visual", "report.decision_visual"}:
                item.implementation_status = "implemented" if self._visual_tools.is_tool_available(item.tool_id) else "not_implemented"
        return catalog

    def _validate_analysis_cards(self) -> None:
        """Fail fast when discovery and detailed analyst knowledge drift apart."""

        missing = sorted(set(self._catalog) - set(self._details))
        extra = sorted(set(self._details) - set(self._catalog))
        if missing or extra:
            raise ValueError(f"metric_catalog_detail_alignment_error: missing={missing}, extra={extra}")
        for tool_id in self._catalog:
            card = self.detail(tool_id)
            if not (
                card.measures.definition
                and card.measures.unit
                and card.use_for.decision_questions
                and card.use_for.action_targets
                and card.compare_by.candidate_targets
                and card.compare_by.area_units
                and card.compare_by.normalization
                and card.interpret_with.combinations
                and card.watch_out.risks
            ):
                raise ValueError(f"metric_analysis_card_incomplete:{tool_id}")

    @staticmethod
    def _family_analysis_profile(family: str) -> dict[str, Any]:
        """Shared analyst knowledge avoids 54 copied governance checklists."""
        profiles: dict[str, dict[str, Any]] = {
            "poi": {
                "b2c": ["比较候选点周边的设施组合，识别更接近社区生活、办公通勤、文旅停留或目的地服务的场景，并调整店型、服务与选品假设。"],
                "b2b": ["把企业服务、园区配套和上下游设施当作拜访与服务场景线索，结合账户清单核查目标节点。"],
                "mixed": ["分别解释消费者配套和企业服务设施，避免将设施数量合成为单一需求分数。"],
                "candidate_targets": "对每个候选点使用相同的步行/驾车等时圈或相同半径范围，比较类别构成与面积归一化后的设施密度。",
                "area_units": "在同一分辨率网格或分区内比较设施构成、密度与共位关系。",
                "normalization": "数量比较应同时给出面积、服务圈面积或类别占比，避免把范围大小误读为优势。",
                "combinations": ["POI + 人口 + 路网 + 等时圈：形成 B2C 服务场景、店型与选品的待验证假设。", "企业/园区 POI + 驾车等时圈 + 路网：形成 B2B 客户节点与履约路径假设。"],
                "conflicts": ["设施较多但可达性较弱时，先核查步行连续性、停车和实际可进入性。"],
                "field_checks": ["核查关键设施是否仍在营业、是否面向目标用户以及高峰时段的进入条件。"],
            },
            "poi_grid": {
                "b2c": ["用分析网格识别设施结构相对完整或薄弱的方向，安排踏勘和服务场景验证。"],
                "b2b": ["用网格观察企业服务、物流和产业配套的空间分布，辅助服务节点与拜访走廊假设。"],
                "mixed": ["对比消费者配套与企业服务网格，识别两侧都需要核查的交界区域。"],
                "candidate_targets": "候选点使用一致的覆盖范围，并将落入范围的同源网格按同一规则聚合。",
                "area_units": "使用现有 H3 或规则网格的同一分辨率、相同覆盖规则比较网格值与构成。",
                "normalization": "优先比较密度、占比或同网格等级；不把不同面积单元的总数直接排序。",
                "combinations": ["POI 网格 + 路网网格：识别需要优先核查的空间组织和进入条件。", "POI 网格 + 人口栅格：形成服务覆盖与品类场景假设。"],
                "conflicts": ["POI 高值网格与路网弱连接重叠时，优先验证是否存在物理隔离或内部不可进入。"],
                "field_checks": ["踏勘网格内街面连续性与关键设施是否可服务目标对象。"],
            },
            "road_syntax": {
                "b2c": ["比较候选点的连接结构，调整到店路径、店面朝向与服务时段核查重点。"],
                "b2b": ["比较企业节点和服务节点的驾车连接及路径连续性，调整拜访、交付和售后履约路线假设。"],
                "mixed": ["区分消费者步行进入与企业履约路径，避免以同一条道路指标替代两类可达性。"],
                "candidate_targets": "使用相同出行方式、相同时间阈值或相同网络半径比较候选对象连接结构。",
                "area_units": "使用同一版路网和同一计算参数，在路段或网格内比较结构位置。",
                "normalization": "比较应固定路网版本、半径、出行模式与路段长度处理方式。",
                "combinations": ["路网 + 等时圈 + POI：解释设施可见但不易进入的候选点差异。", "路网 + 企业/园区 + 物流设施：形成 B2B 服务半径和履约路线假设。"],
                "conflicts": ["路网结构较强但设施或覆盖较弱时，核查该走廊是穿行路径还是可停留、可服务的场景。"],
                "field_checks": ["核查人行连续性、过街、停车、装卸和时间限制。"],
            },
            "population": {
                "b2c": ["比较服务范围内的人口分布和结构，细化服务能力、店型和品类场景的待验证假设。"],
                "b2b": ["作为劳动、居住和环境背景，与企业账户和产业节点共同解释服务可达条件。"],
                "mixed": ["不要将人口直接合并为企业需求；分别服务于消费者侧与环境背景判断。"],
                "candidate_targets": "对候选点使用同口径服务范围裁剪同一版人口栅格，比较有效像元的汇总和结构。",
                "area_units": "在同一栅格分辨率或汇总网格内比较分布和结构。",
                "normalization": "固定数据年份、栅格分辨率和裁剪规则；必要时报告面积覆盖率。",
                "combinations": ["人口 + POI + 路网：解释不同候选点的服务场景与覆盖条件。", "人口 + 夜间亮度 + 夜间设施：形成时段和夜间服务的待验证假设。"],
                "conflicts": ["人口覆盖较高但设施或进入条件较弱时，不能直接判定为机会，应先核查服务缺口、边界或不可进入性。"],
                "field_checks": ["通过现场观察、访谈、订单或试点核实真实使用者、时段和服务需求。"],
            },
            "nightlight": {
                "b2c": ["比较夜间亮度空间分布，结合夜间设施和接入条件提出服务时段、夜间品类或运营安排假设。"],
                "b2b": ["作为夜间生产、物流或园区环境的背景线索，需与账户和履约数据共同解释。"],
                "mixed": ["分别识别消费者夜间场景和企业/物流夜间环境，避免解释成统一商业活跃度。"],
                "candidate_targets": "对候选点使用相同范围和同一年度栅格裁剪，比较有效像元的亮度分布。",
                "area_units": "在同一栅格/聚合网格内比较亮度、热点和梯度形态。",
                "normalization": "固定年份、传感器版本、NoData 处理和面积覆盖规则。",
                "combinations": ["夜间亮度 + 夜间设施 + 接入条件：形成夜间服务时段与品类假设。", "夜间亮度 + 路网 + 项目材料：核查照明、可见性或夜间安全条件。"],
                "conflicts": ["亮度较高但夜间设施或安全进入条件不足时，应区分照明来源、穿行道路和实际停留场景。"],
                "field_checks": ["在目标时段实地观察亮度来源、停留、进入和服务设施状态。"],
            },
            "isochrone": {
                "b2c": ["比较候选点的步行或驾车覆盖，调整服务范围、店型和到店便利性假设。"],
                "b2b": ["比较企业或服务节点的驾车覆盖，调整拜访、交付和售后服务半径。"],
                "mixed": ["分别设置消费者与企业端的出行方式和时间阈值。"],
                "candidate_targets": "所有候选点必须使用相同出行方式、相同时间阈值和同一版路网生成范围。",
                "area_units": "将同口径等时圈与同一网格/设施数据相交后比较覆盖结果。",
                "normalization": "固定起点、出行模式、时长、交通假设和数据快照。",
                "combinations": ["等时圈 + POI + 人口：形成服务覆盖和店型假设。", "驾车等时圈 + 企业/园区 + 路网：形成 B2B 节点和履约假设。"],
                "conflicts": ["范围覆盖较大但道路断点明显时，优先踏勘最后一段到达条件。"],
                "field_checks": ["使用实地走访、导航复核或试配送验证真实时间和到达限制。"],
            },
        }
        generic = {
            "b2c": ["在项目内部比较空间差异，辅助选址、布局、服务场景或验证优先级判断。"],
            "b2b": ["在项目内部比较节点、路径或空间条件，辅助账户覆盖和履约验证判断。"],
            "mixed": ["分别说明企业端和消费者端的分析对象与行动含义。"],
            "candidate_targets": "候选对象使用同一数据快照、相同空间范围和一致参数进行比较。",
            "area_units": "项目区域使用同分辨率网格、H3 或既有分区进行内部比较。",
            "normalization": "固定数据版本、空间单元和算法参数；仅报告项目内部相对差异。",
            "combinations": ["与项目材料及至少一个互补的空间指标共同解释，形成可验证的空间场景。"],
            "conflicts": ["不同信号相互冲突时，不强行合成为总分；安排踏勘、访谈或试点解释差异。"],
            "field_checks": ["将主要空间差异转化为对象明确的现场观察、访谈或直接数据核查。"],
        }
        return {**generic, **profiles.get(family, {})}

    def detail(self, tool_id: str) -> MetricDetail:
        item = self._catalog.get(str(tool_id or "").strip())
        if item is None:
            raise ValueError(f"unknown_metric_tool:{tool_id}")
        raw = self._details.get(item.tool_id, {})
        profile = self._family_analysis_profile(str(raw.get("family") or ""))
        actionability = _mapping(raw.get("actionability"))
        spatial_units = [str(value.get("unit")) for value in _list(raw.get("spatial_granularities")) if isinstance(value, dict) and value.get("unit")]
        followups = [
            f"{value.get('metric_id')}：{value.get('purpose') or '解释'}（{value.get('trigger') or '出现需要解释的差异时'}）"
            for value in _list(raw.get("followup_metrics")) if isinstance(value, dict)
        ]
        risks = [str(value) for value in _list(raw.get("does_not_support"))]
        risks.extend(str(value) for value in _list(raw.get("limitations") or raw.get("caveats")))
        return MetricDetail(
            tool_id=item.tool_id,
            name=item.name,
            measures=MetricMeasures(
                definition=str(raw.get("definition") or item.purpose),
                unit=str(raw.get("unit") or "未声明"),
                outputs=[str(value) for value in _list(raw.get("outputs"))],
                calculation=str(raw.get("formula") or raw.get("calculation") or raw.get("definition") or item.purpose),
                spatial_units=spatial_units or [item.primary_spatial_unit],
                time_semantics="使用当前选定的数据快照或年份；跨期比较必须保持同源和同口径。",
                method_version=str(raw.get("catalog_version") or "metric-catalog-2"),
            ),
            use_for=MetricUseFor(
                decision_questions=[str(value) for value in _list(raw.get("answers_questions"))] + [str(value) for value in _list(raw.get("supports"))],
                action_targets=[str(value) for value in _list(actionability.get("action_targets"))] + [str(value) for value in _list(actionability.get("possible_actions"))],
                b2c=profile["b2c"], b2b=profile["b2b"], mixed=profile["mixed"],
            ),
            compare_by=MetricCompareBy(
                candidate_targets=profile["candidate_targets"], area_units=profile["area_units"], normalization=profile["normalization"],
                consistency_rules=[str(value) for value in _list(raw.get("valid_comparisons"))] + ["比较对象必须使用同一数据快照、空间单元和计算参数。"],
            ),
            interpret_with=MetricInterpretWith(combinations=profile["combinations"] + followups, conflict_prompts=profile["conflicts"]),
            watch_out=MetricWatchOut(risks=list(dict.fromkeys(risks)), field_checks=profile["field_checks"]),
            unavailable_semantics="输入范围、必需数据或健康条件不可用时返回 unavailable 并说明原因；绝不生成替代数值。",
            asset_types=["svg"] if (item.implementation_status == "implemented" or (item.tool_id in {"spatial.thematic_visual", "report.decision_visual"} and self._visual_tools.is_tool_available(item.tool_id))) else [],
        )

    def execute(self, *, tool_id: str, history_id: str, history_detail: dict[str, Any], project_documents: dict[str, Any], source_index: SourceIndex, parameters: dict[str, Any] | None = None, project_anchors: dict[str, Any] | None = None) -> MetricResult:
        item = self._catalog.get(str(tool_id or "").strip())
        if item is None:
            raise ValueError(f"unknown_metric_tool:{tool_id}")
        normalized_parameters = _mapping(parameters)
        normalized_anchors = _mapping(project_anchors)
        input_sources = sorted({source for resource in source_index.items for source in resource.source_ids})
        # A metric result includes its project-internal comparison. Candidate
        # objects and the declared comparison design therefore belong to its
        # identity; otherwise a later chapter could reuse an earlier result for
        # a different candidate set and silently show the wrong comparison.
        signature = content_digest({
            "tool_id": item.tool_id,
            "history_id": history_id,
            "parameters": normalized_parameters,
            "input_sources": input_sources,
            "comparison_anchors": normalized_anchors,
        })[7:23]
        result_id = f"result:{item.tool_id}:{signature}"
        existing = source_index.result(result_id)
        if existing:
            return MetricResult.model_validate({"result_id": result_id, "tool_id": item.tool_id, "tool_version": "catalog-4.1", **existing.payload})
        if item.implementation_status != "implemented":
            result = MetricResult(result_id=result_id, tool_id=item.tool_id, tool_version="catalog-4.1", status="unavailable", summary="该工具尚未实现，未生成任何替代数值。", input_sources=input_sources, limitations=["工具实现状态为 not_implemented。"])
            self._record_result(source_index, result)
            return result
        try:
            execution = self._spatial_service.execute_metric_tool(
                tool_id=item.tool_id,
                primary_spatial_unit=item.primary_spatial_unit,
                history_id=history_id,
                history_detail=_mapping(history_detail),
                project_documents=_mapping(project_documents),
                project_anchors=_mapping(project_anchors),
                comparison_design=str(_mapping(project_anchors).get("comparison_design") or ""),
                parameters=normalized_parameters,
            )
            result = MetricResult(
                result_id=result_id,
                tool_id=item.tool_id,
                tool_version="catalog-4.1",
                status=execution.status,
                summary=execution.summary,
                structured_result=execution.structured_result,
                input_sources=execution.input_sources or input_sources,
                spatial_scope={"history_id": history_id, "unit": item.primary_spatial_unit},
                limitations=execution.limitations,
            )
        except Exception as exc:
            result = MetricResult(result_id=result_id, tool_id=item.tool_id, tool_version="catalog-4.1", status="failed", summary="工具执行失败，当前章节应将该问题作为数据边界而非补造数值。", input_sources=input_sources, limitations=[f"内部执行未完成：{type(exc).__name__}"])
        self._record_result(source_index, result)
        self._record_health_summaries(source_index, result)
        return result

    @staticmethod
    def _record_health_summaries(source_index: SourceIndex, result: MetricResult) -> None:
        health_items = _list(_mapping(result.structured_result).get("data_health"))
        for value in health_items:
            health = _mapping(value)
            source_id = str(health.get("source_id") or "").strip()
            if not source_id:
                continue
            resource_id = f"dataset:{source_id}"
            current = next((item for item in source_index.items if item.resource_id == resource_id), None)
            status = str(health.get("status") or "")
            summary = "数据健康：" + ({"ready": "可用于当前比较", "limited": "可用但需按限制解释", "unavailable": "当前不可用于该指标"}.get(status, "待检查"))
            if current is None:
                source_index.upsert(SourceIndexItem(resource_id=resource_id, resource_type="dataset", title=source_id, status="unavailable" if status == "unavailable" else "available", summary=summary, source_ids=[source_id], payload={"data_health": health}))
            else:
                current.status = "unavailable" if status == "unavailable" else current.status
                current.summary = summary
                current.payload = {**current.payload, "data_health": health}
                current.limitations = list(dict.fromkeys([*current.limitations, *[str(item) for item in _list(health.get("limitations"))]]))

    @staticmethod
    def _record_result(source_index: SourceIndex, result: MetricResult) -> None:
        source_index.upsert(SourceIndexItem(resource_id=result.result_id, resource_type="analysis_result", title=result.tool_id, status=result.status, summary=result.summary, source_ids=result.input_sources, spatial_scope=result.spatial_scope, time_scope=result.time_scope, limitations=result.limitations, payload=result.model_dump(mode="json", exclude={"result_id"})))
