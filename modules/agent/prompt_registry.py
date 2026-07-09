from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List

from pydantic import BaseModel, ConfigDict, Field


class PromptConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    prompt_key: str
    title: str = ""
    system_prompt: str = ""
    payload_note: str = ""
    output_schema: Dict[str, Any] = Field(default_factory=dict)
    evidence_version: str = ""
    updated_at: str = ""


class PromptUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    system_prompt: str = ""
    payload_note: str = ""
    output_schema: Dict[str, Any] = Field(default_factory=dict)


_REGISTRY_PATH = Path("runtime") / "agent_prompt_registry.json"
_DEFAULT_BUILDERS: Dict[str, Callable[[], PromptConfig]] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _schema(properties: Dict[str, Any], required: List[str]) -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _register_default(prompt_key: str, builder: Callable[[], PromptConfig]) -> None:
    _DEFAULT_BUILDERS[prompt_key] = builder


def register_prompt_default(prompt_key: str, builder: Callable[[], PromptConfig]) -> None:
    _register_default(prompt_key, builder)


def _default_payload_note(task: str, evidence_version: str) -> str:
    return (
        f'User payload: {{"task":"{task}","evidence": {evidence_version} 证据包}}。'
        "evidence 只包含后端构造的结构化字段；不包含图片/base64、全量点位、完整网格或前端 UI 状态。"
    )


def _make_default_configs() -> Dict[str, PromptConfig]:
    updated_at = "2026-05-10T00:00:00Z"
    defaults: Dict[str, PromptConfig] = {
        "headline": PromptConfig(
            prompt_key="headline",
            title="核心判断",
            system_prompt=(
                "你是一名商业地理与城市空间分析师。"
                "请基于给定结构化证据，输出 JSON：{\"summary\":\"...\",\"supporting_clause\":\"...\"}。"
                "要求：summary 必须是一句话商业判断；supporting_clause 必须补一句解释，不要复述 summary；"
                "不能编造新事实，不能罗列原始数值。"
            ),
            payload_note=_default_payload_note("summary_headline_generation", "summary_pack_v1"),
            output_schema=_schema(
                {
                    "summary": {"type": "string"},
                    "supporting_clause": {"type": "string"},
                },
                ["summary"],
            ),
            evidence_version="summary_pack_v1",
            updated_at=updated_at,
        ),
        "spatial_structure": PromptConfig(
            prompt_key="spatial_structure",
            title="空间结构",
            system_prompt=(
                "你是一名商业地理与城市空间分析师。现在只生成空间结构判断卡片，必须输出 JSON，不要输出 markdown。"
                "JSON 结构固定为：{\"section_key\":\"spatial_structure\",\"title\":\"空间结构\",\"reasoning\":\"...\","
                "\"dimensions\":[{\"key\":\"aggregation\",\"label\":\"聚集性\",\"conclusion\":\"...\"},"
                "{\"key\":\"mixing\",\"label\":\"混合性\",\"conclusion\":\"...\"},"
                "{\"key\":\"morphology\",\"label\":\"形态性\",\"conclusion\":\"...\"}]}。"
                "只回答空间组织，不写人口、夜光或用户画像；reasoning 必须是商业判断句，不要写成指标描述。"
            ),
            payload_note=_default_payload_note("summary_section_spatial_structure", "summary_pack_v1"),
            output_schema=_schema(
                {
                    "section_key": {"type": "string"},
                    "title": {"type": "string"},
                    "reasoning": {"type": "string"},
                    "dimensions": {"type": "array", "items": {"type": "object"}},
                },
                ["section_key", "title", "reasoning", "dimensions"],
            ),
            evidence_version="summary_pack_v1",
            updated_at=updated_at,
        ),
        "poi_structure": PromptConfig(
            prompt_key="poi_structure",
            title="POI结构",
            system_prompt=(
                "你是一名商业地理与城市空间分析师。现在只生成 POI 结构判断卡片，必须输出 JSON，不要输出 markdown。"
                "JSON 结构固定为：{\"section_key\":\"poi_structure\",\"title\":\"POI结构\",\"reasoning\":\"...\"}。"
                "只写主导业态、占比结构和功能特征，要写成判断句，不要写成“反映了/体现了”的指标播报。"
            ),
            payload_note=_default_payload_note("summary_section_poi_structure", "summary_pack_v1"),
            output_schema=_schema(
                {
                    "section_key": {"type": "string"},
                    "title": {"type": "string"},
                    "reasoning": {"type": "string"},
                },
                ["section_key", "title", "reasoning"],
            ),
            evidence_version="summary_pack_v1",
            updated_at=updated_at,
        ),
        "consumption_vitality": PromptConfig(
            prompt_key="consumption_vitality",
            title="经济活动强度",
            system_prompt=(
                "你是一名商业地理与城市空间分析师。现在只生成经济活动强度判断卡片，必须输出 JSON，不要输出 markdown。"
                "JSON 结构固定为：{\"section_key\":\"consumption_vitality\",\"title\":\"经济活动强度\",\"reasoning\":\"...\"}。"
                "只基于夜光、方位和路网 raw signal 生成解释；不写消费能力、客流、营业额或白天活跃；不套用固定判断路径。"
            ),
            payload_note=_default_payload_note("summary_section_consumption_vitality", "summary_pack_v1"),
            output_schema=_schema(
                {
                    "section_key": {"type": "string"},
                    "title": {"type": "string"},
                    "reasoning": {"type": "string"},
                },
                ["section_key", "title", "reasoning"],
            ),
            evidence_version="summary_pack_v1",
            updated_at=updated_at,
        ),
        "business_support": PromptConfig(
            prompt_key="business_support",
            title="业态承接",
            system_prompt=(
                "你是一名商业地理与城市空间分析师。现在只生成业态承接判断卡片，必须输出 JSON，不要输出 markdown。"
                "JSON 结构固定为：{\"section_key\":\"business_support\",\"title\":\"业态承接\",\"reasoning\":\"...\"}。"
                "只基于路网与空间条件 raw signal 生成解释；不规定连通性、通达效率、认知可读性的固定顺序，不预设承接结论。"
            ),
            payload_note=_default_payload_note("summary_section_business_support", "summary_pack_v1"),
            output_schema=_schema(
                {
                    "section_key": {"type": "string"},
                    "title": {"type": "string"},
                    "reasoning": {"type": "string"},
                },
                ["section_key", "title", "reasoning"],
            ),
            evidence_version="summary_pack_v1",
            updated_at=updated_at,
        ),
        "user_profile": PromptConfig(
            prompt_key="user_profile",
            title="用户画像",
            system_prompt=(
                "你是一名商业地理与城市空间分析师。请基于给定结构化证据，输出 JSON："
                "{\"headline\":\"...\",\"traits\":[\"...\",\"...\"]}。"
                "headline 必须写消费者是谁，traits 写 2 到 4 条稳定画像特征。不能编造新事实，不能输出 markdown。"
            ),
            payload_note=_default_payload_note("summary_user_profile_generation", "summary_pack_v1"),
            output_schema=_schema(
                {
                    "headline": {"type": "string"},
                    "traits": {"type": "array", "items": {"type": "string"}},
                },
                ["headline", "traits"],
            ),
            evidence_version="summary_pack_v1",
            updated_at=updated_at,
        ),
        "behavior_inference": PromptConfig(
            prompt_key="behavior_inference",
            title="商业行为推断",
            system_prompt=(
                "你是一名商业地理与城市空间分析师。请基于给定结构化证据，输出 JSON："
                "{\"headline\":\"...\",\"traits\":[\"...\",\"...\"]}。"
                "headline 必须写消费行为或使用方式，traits 写 2 到 4 条行为特征。不能编造新事实，不能输出 markdown。"
            ),
            payload_note=_default_payload_note("summary_behavior_inference_generation", "summary_pack_v1"),
            output_schema=_schema(
                {
                    "headline": {"type": "string"},
                    "traits": {"type": "array", "items": {"type": "string"}},
                },
                ["headline", "traits"],
            ),
            evidence_version="summary_pack_v1",
            updated_at=updated_at,
        ),
        "followups": PromptConfig(
            prompt_key="followups",
            title="快捷追问",
            system_prompt=(
                "你是一名商业地理与城市空间分析师。请基于当前总结证据，输出 JSON：{\"questions\":[\"...\",\"...\",\"...\"]}。"
                "questions 输出 1 到 3 条；每条都要基于当前证据缺口或用户问题自然生成；不要输出解释和 markdown。"
            ),
            payload_note=_default_payload_note("summary_followup_generation", "summary_pack_v1"),
            output_schema=_schema(
                {"questions": {"type": "array", "items": {"type": "string"}}},
                ["questions"],
            ),
            evidence_version="summary_pack_v1",
            updated_at=updated_at,
        ),
        "tourism_cross_analysis": PromptConfig(
            prompt_key="tourism_cross_analysis",
            title="文旅交叉策划分析",
            system_prompt=(
                "你是一名资深城市策划、商业地理、人口画像、夜经济与文旅项目策划分析师。"
                "请基于输入的同一目标地块的人口数据、POI多年变化数据和夜间灯光变化数据，生成一段用于城市文旅策划报告的综合分析文本。"
                "本次分析目标不是分别罗列人口、POI和夜光数据，而是让 AI 基于三类证据自行生成可追溯的空间现象、人的体验、策划影响和行动建议。"
                "人口、POI和夜光只作为证据输入；不要预设固定分析链路、固定结论或固定项目定位。"
                "生成判断前必须在内部按 Observation、Mechanism、Alternative、Evidence Quality、Implication 检查关键证据：先看数据现象，再解释可能机制，同时给出替代解释和证据质量边界，最后只输出证据能支撑的策划含义。"
                "只能使用输入 evidence 中已有信息，不得使用外部信息。可使用的数据包括：人口总量、年龄结构、男女人数、性别比例、人口空间分布、网格人口数量、每个网格内男女差异、人口密度分布、高密度网格、低密度网格、人口集聚区、人口稀疏区等人口字段；POI 的 year_summaries、trend_metrics、category_changes、subcategory_changes、material_change_highlights、area_distribution、spatial_factors、subcategory_spatial_trends、growth_area_signal、rule_insights、constraints；夜间灯光的 series、hotspot_shift、insights、snapshot_refs、years、period。"
                "不得凭空编造政策、道路、商圈、地铁、景区、地标、人流、消费金额、游客来源、消费等级、营业收入、活动事件或文化资源。"
                "人口数据只能说明人口结构、空间分布和潜在需求，不能直接等同于真实消费能力；POI数据只能说明业态数量、结构、变化和空间分布，不能直接等同于经营质量或真实客流；夜间灯光数据只能作为夜间活动强度、空间活跃度和夜经济潜力的间接指标，不能直接等同于消费额、营业收入或真实人流量。"
                "如果证据不足，必须明确说明：当前证据只能支持趋势判断，不能直接证明真实消费规模。仍需叠加客流、消费、交通、商户营业时间、活动运营和实地调研数据验证。"
                "空间交叉证据使用规则：人口、POI、夜光三类数据的空间耦合只能引用 evidence.spatial_evidence.shared_grid 中的 shared_grid_evidence_v1；H3 证据只能引用 poi_evidence.h3_evidence 或 spatial_evidence.poi_h3_evidence，用于 POI 密度、集聚、热点、复合度等专项空间结构判断，不得用 H3 直接证明人口、POI、夜光三者重合。"
                "可分析人口数量、年龄结构和空间分布，但不得把年龄或人口结构套入固定客群模板。"
                "必须分析男女人数和性别比例，判断整体人群结构是否均衡。不得基于性别进行刻板化消费判断，性别数据主要用于判断空间服务均衡性、公共安全感、夜间活动包容性、家庭/社交场景适配性和运营服务配置。"
                "必须分析人口在网格中的分布，识别人口高密度区、低密度区、集中区和分散区，判断人口空间结构是集中型、多点型、均衡型还是分化型。"
                "必须分析每个网格内男女差异，识别性别结构差异较大的网格。性别较均衡的网格适合复合型公共活动、家庭休闲、社交消费；性别差异较大的网格需关注服务设施包容性、安全感、夜间照明、活动内容多元化；不得将性别差异直接解释为某类消费偏好，除非数据中有明确证据。"
                "可分析人口密度、POI 总量、类别结构和年度变化，但不要把高低密度或具体业态变化直接套入固定策划结论。"
                "必须结合方向、圈层、热点、增长片区信号判断 POI 空间分布是内部加密、核心强化、多点扩散还是外扩不足。不得根据坐标自行编造具体道路、商圈或地标。"
                "必须分析夜间灯光所反映的夜间空间活力和夜间消费基础。分析 total_radiance 的多年变化，判断夜间整体活动强度是增强、稳定、波动还是衰退；分析 mean_radiance，判断夜间亮度提升是否具有整体性；分析 p90_radiance 和 max_radiance，p90用于判断高亮区域稳定性和强度，max用于辅助判断局部极值波动；分析 lit_pixel_ratio，点亮比例高说明夜间基础覆盖完整，但不能直接说明消费活力强。"
                "必须分析 increase_count、decrease_count、stable_count、hotspot_stable、hotspot_emerging、hotspot_faded，判断夜间空间活力属于高稳定活跃型、稳定增强型、增长潜力型、局部热点型、分化调整型或活力衰退型。"
                "交叉分析由 AI 根据证据自然组织，不要求固定按照人口、POI、夜光或项目定位顺序展开。"
                "人口密度 × POI供给、年龄结构 × POI业态等关系只能作为证据关系描述，不得直接生成服务补位、消费潜力或外来客流结论。"
                "必须完成性别结构 × 空间服务判断：整体性别比例和网格男女差异对公共空间安全感、夜间照明和导视、活动内容多元化、公共卫生间、休憩设施、亲子友好设施、夜间运营包容性和舒适性的启示。不得把性别差异直接等同于消费偏好。"
                "人口、POI、夜光的空间关系只描述证据关系，由 AI 自行决定是否转化为策划语言；不要预置优先策划区、服务补位、业态组合或项目定位模板。"
                "风险与验证必须指出：人口数据不能直接代表消费；POI不能直接代表经营质量；夜光不能直接代表消费额；性别和年龄结构不能被刻板化解释；文旅类POI或文化内容可能不足；局部夜光减弱或热点衰退可能存在空间分化；后续需补充客流、消费、交通、营业时间、活动运营和实地调研验证。"
                "如果证据不足，必须明确写出：当前证据只能支持趋势判断，不能直接证明真实消费规模；仍需叠加客流、消费、交通、商户营业时间、活动运营和实地调研数据验证。"
                "输出中文，专业、理性、适合城市文旅策划报告，不要写成纯技术报告，不要堆砌数据。"
                "必须只输出 JSON，不要输出 markdown。JSON 固定为 {\"title\":\"文旅交叉策划分析\",\"content\":\"...\"}。"
                "content 可自然分段，不要求固定九节标题，不输出固定填空式策划结论。"
            ),
            payload_note=(
                'User payload: {"task":"tourism_cross_analysis","evidence": tourism_cross_analysis_v1 证据包}。'
                "evidence 只包含当前分析会话已有的人口、POI多年变化、夜间灯光和系统派生摘要；不包含外部资料、全量底图或前端 UI 状态。"
            ),
            output_schema=_schema(
                {
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                },
                ["title", "content"],
            ),
            evidence_version="tourism_cross_analysis_v1",
            updated_at=updated_at,
        ),
        "poi_iteration": PromptConfig(
            prompt_key="poi_iteration",
            title="POI 多年迭代",
            system_prompt=(
                "你是一名资深商业地理、城市空间与城市策划分析师。请基于 poi_iteration_v1 证据包，生成一篇用于城市策划文本的“业态基础分析总结报告”。"
                "报告目标是把 POI 多年变化解释成完整策划判断，而不是列表摘要。请从 POI 总量、一级业态、细分业态、空间分布、H3 网格结构、年度 H3 变化和增长信号中，判断区域商业基础、业态演化、空间活力和策划含义。"
                "只能使用证据包中已有信息，重点依据 year_summaries、trend_metrics、category_changes、subcategory_changes、area_distribution、spatial_factors、subcategory_spatial_trends、growth_area_signal、material_change_highlights、h3_evidence、yearly_grid_evidence。"
                "生成判断前必须在内部按 Observation、Mechanism、Alternative、Evidence Quality、Implication 检查关键证据：不要把 POI 数量、占比或增速直接翻译成商业结论；必须说明替代解释、证据强弱和仍需验证的判断。"
                "H3 证据可用于判断网格密度、混合度、邻域均值、热点/冷点、LISA、LQ、缺口、类别结构、空间集聚和年度变化；不得用网格坐标编造道路、商圈、地标、客流、收入或外部游客来源。"
                "不得使用证据包之外的信息。不得凭空编造城市发展背景、政策、地铁、道路、商圈、学校、景区、人口、房价、消费等级或外部事件。位置判断只能来自证据中已有区域、方向、圈层、热点或空间信号字段。"
                "证据不足时必须写明“证据信号有限”“无法直接判断原因”或“只能作趋势性推断”。原因分析必须基于证据链，可提出可能原因，但要说明依据来自总量变化、一级业态变化、细分业态变化、空间分布变化、网格变化或显著增减类目。"
                "判断重要变化时优先考虑绝对增减量、末年数量、末年占比、主导程度、连续趋势和空间集中程度，不要只依据百分比增速。"
                "报告应按证据自然组织章节，不固定章节名称和顺序；内容上需要覆盖主导业态、业态结构、空间特征、变化原因、策划启示和最终判断这些分析维度。"
                "可选专题章节只在证据显著时出现，例如旅游、文教、体育、商务办公、购物、住宿等；不得固定输出“住宿与停留”，也不要套固定目录。"
                "每个章节写成正式报告段落，遵循“数据现象 -> 结构判断 -> 策划含义”的表达。章节内容要有具体数据依据，避免只有短句。"
                "只输出一个 JSON 对象，不要输出 markdown、解释说明或代码块。唯一允许的 JSON 结构如下："
                "{\"report_title\":\"业态基础分析总结报告\",\"report_sections\":[{\"heading\":\"证据自然生成的章节标题\",\"paragraphs\":[\"数据现象、结构判断与策划含义写成一个完整段落。\"]}],\"report_content\":\"业态基础分析总结报告\\n\\n证据自然生成的章节标题\\n\\n完整报告正文\"}"
                "report_sections 每项必须包含 heading 和 paragraphs；paragraphs 必须是中文段落数组。report_content 必须是完整纯文本报告，由标题、章节标题和段落正文组成。"
            ),
            payload_note=(
                'User payload: {"task":"poi_iteration_change","evidence": poi_iteration_v1 证据包}。'
                "evidence 只包含年度摘要、趋势指标、业态/小类变化、空间因子、小类空间信号、增长片区信号、区域分布摘要、H3 网格证据和年度网格证据；"
                "不包含全量 POI 点、图片 base64、底图、完整热力格或前端 UI 状态。"
            ),
            output_schema=_schema(
                {
                    "report_title": {"type": "string"},
                    "report_sections": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "heading": {"type": "string"},
                                "paragraphs": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["heading", "paragraphs"],
                            "additionalProperties": False,
                        },
                    },
                    "report_content": {"type": "string"},
                },
                [
                    "report_title",
                    "report_sections",
                    "report_content",
                ],
            ),
            evidence_version="poi_iteration_v1",
            updated_at=updated_at,
        ),
        "nightlight_iteration": PromptConfig(
            prompt_key="nightlight_iteration",
            title="夜光多年迭代",
            system_prompt=(
                "你是商业地理与夜光遥感分析助手。请基于 nightlight_iteration_v1 证据包中的 years、series、hotspot_shift、"
                "insights 和 snapshot_refs 判断区域夜间经济活动的热点变化和迁移趋势。"
                "只输出 JSON 对象，字段必须为 headline, trend_summary, hotspot_migration, risk_or_opportunity。"
                "headline 必须是一句话趋势判断；trend_summary 说明总辐亮、均值、P90 或点亮占比的主要变化；"
                "hotspot_migration 只能使用 hotspot_shift 和 insights 中已有信号；risk_or_opportunity 说明机会或风险。不要输出 markdown。"
            ),
            payload_note=(
                'User payload: {"task":"nightlight_iteration_change","evidence": nightlight_iteration_v1 证据包}。'
                "evidence 只包含年度夜光统计、热点迁移摘要、规则洞察和快照引用状态；不包含图片 base64、完整栅格、地图底图或前端 UI 状态。"
            ),
            output_schema=_schema(
                {
                    "headline": {"type": "string"},
                    "trend_summary": {"type": "string"},
                    "hotspot_migration": {"type": "string"},
                    "risk_or_opportunity": {"type": "string"},
                },
                ["headline", "trend_summary", "hotspot_migration", "risk_or_opportunity"],
            ),
            evidence_version="nightlight_iteration_v1",
            updated_at=updated_at,
        ),
    }
    for prompt_key, builder in _DEFAULT_BUILDERS.items():
        defaults[prompt_key] = builder()
    return defaults


def _read_registry_file() -> Dict[str, Any]:
    if not _REGISTRY_PATH.exists():
        return {}
    try:
        data = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_registry_file(configs: Dict[str, PromptConfig]) -> None:
    _REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        key: config.model_dump(mode="json")
        for key, config in sorted(configs.items())
    }
    _REGISTRY_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_configs() -> Dict[str, PromptConfig]:
    configs = _make_default_configs()
    stored = _read_registry_file()
    changed = not _REGISTRY_PATH.exists()
    for key, value in stored.items():
        if not isinstance(value, dict):
            continue
        try:
            config = PromptConfig(**{**value, "prompt_key": str(value.get("prompt_key") or key)})
        except Exception:
            continue
        configs[config.prompt_key] = config
    for key, config in list(configs.items()):
        if not config.updated_at:
            configs[key] = config.model_copy(update={"updated_at": _now_iso()})
            changed = True
    if changed:
        _write_registry_file(configs)
    return configs


def list_prompt_configs() -> List[PromptConfig]:
    return list(_load_configs().values())


def get_prompt_config(prompt_key: str) -> PromptConfig:
    key = str(prompt_key or "").strip()
    configs = _load_configs()
    if key not in configs:
        raise KeyError(key)
    return configs[key]


def update_prompt_config(prompt_key: str, update: PromptUpdateRequest) -> PromptConfig:
    key = str(prompt_key or "").strip()
    configs = _load_configs()
    if key not in configs:
        raise KeyError(key)
    current = configs[key]
    next_config = current.model_copy(update={
        "system_prompt": str(update.system_prompt or ""),
        "payload_note": str(update.payload_note or ""),
        "output_schema": deepcopy(update.output_schema or {}),
        "updated_at": _now_iso(),
    })
    configs[key] = next_config
    _write_registry_file(configs)
    return next_config


def build_prompt_snapshot(config: PromptConfig) -> Dict[str, Any]:
    return {
        "prompt_key": config.prompt_key,
        "title": config.title,
        "system_prompt": config.system_prompt,
        "payload_note": config.payload_note,
        "output_schema": deepcopy(config.output_schema or {}),
        "evidence_version": config.evidence_version,
        "updated_at": config.updated_at,
    }
