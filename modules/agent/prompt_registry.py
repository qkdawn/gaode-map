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
                "只写夜间经济活动强度，不写消费能力、客流、营业额或白天活跃；优先使用夜光方位与路网走向的一致性形成判断。"
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
                "只写路网与空间条件对现有业态的承接；先写连通性，再写通达效率，再写认知可读性，最后落到承接判断。"
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
                "questions 固定输出 3 条；每条都要是下一步值得继续追问的问题；不要输出解释和 markdown。"
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
                "本次分析目标不是分别罗列人口、POI和夜光数据，而是通过三类数据交叉分析，判断目标地块的客群基础、消费需求、业态供给、夜间活力、文旅转化条件、空间运营方向和项目策划定位。"
                "基础分析逻辑：人口数据回答“谁在这里、人口结构如何、潜在需求在哪里？”；POI数据回答“这里有什么业态，商业与服务供给是否支撑消费？”；夜间灯光数据回答“这里夜间是否活跃，是否具备夜间消费和夜游承载条件？”；三类数据叠加回答“这个场地适合做什么类型的文旅项目，面向什么客群，用什么业态组合和空间策略落地”。"
                "只能使用输入 evidence 中已有信息，不得使用外部信息。可使用的数据包括：人口总量、年龄结构、男女人数、性别比例、人口空间分布、网格人口数量、每个网格内男女差异、人口密度分布、高密度网格、低密度网格、人口集聚区、人口稀疏区等人口字段；POI 的 year_summaries、trend_metrics、category_changes、subcategory_changes、material_change_highlights、area_distribution、spatial_factors、subcategory_spatial_trends、growth_area_signal、rule_insights、constraints；夜间灯光的 series、hotspot_shift、insights、snapshot_refs、years、period。"
                "不得凭空编造政策、道路、商圈、地铁、景区、地标、人流、消费金额、游客来源、消费等级、营业收入、活动事件或文化资源。"
                "人口数据只能说明人口结构、空间分布和潜在需求，不能直接等同于真实消费能力；POI数据只能说明业态数量、结构、变化和空间分布，不能直接等同于经营质量或真实客流；夜间灯光数据只能作为夜间活动强度、空间活跃度和夜经济潜力的间接指标，不能直接等同于消费额、营业收入或真实人流量。"
                "如果证据不足，必须明确说明：当前证据只能支持趋势判断，不能直接证明真实消费规模。仍需叠加客流、消费、交通、商户营业时间、活动运营和实地调研数据验证。"
                "空间交叉证据使用规则：人口、POI、夜光三类数据的空间耦合只能引用 evidence.spatial_evidence.shared_grid 中的 shared_grid_evidence_v1；H3 证据只能引用 poi_evidence.h3_evidence 或 spatial_evidence.poi_h3_evidence，用于 POI 密度、集聚、热点、复合度等专项空间结构判断，不得用 H3 直接证明人口、POI、夜光三者重合。"
                "必须先分析人口数据所反映的客群基础和需求方向，但不要只罗列人口数量。必须判断人口总量所反映的基础客群规模，以及该地块是否具备本地生活消费、日常休闲、社区型文旅或夜间消费的基本人群支撑。"
                "必须分析年龄结构，识别主力年龄段和潜在需求方向。年轻人群占比较高时，可判断其对社交餐饮、夜间休闲、轻娱乐、打卡消费、运动社交、文创市集的支撑；中青年人群占比较高时，可判断其对餐饮、亲子、家庭休闲、品质消费、周末活动的支撑；儿童或亲子相关人群明显时，可判断亲子活动、研学体验、公共休闲、轻文旅潜力；老年人群占比较高时，可判断慢行休闲、康养服务、社区活动、日间文旅潜力；年龄结构均衡时，可判断复合型生活文旅场景适配性。所有判断必须基于输入数据，不得强行套用。"
                "必须分析男女人数和性别比例，判断整体人群结构是否均衡。不得基于性别进行刻板化消费判断，性别数据主要用于判断空间服务均衡性、公共安全感、夜间活动包容性、家庭/社交场景适配性和运营服务配置。"
                "必须分析人口在网格中的分布，识别人口高密度区、低密度区、集中区和分散区，判断人口空间结构是集中型、多点型、均衡型还是分化型。"
                "必须分析每个网格内男女差异，识别性别结构差异较大的网格。性别较均衡的网格适合复合型公共活动、家庭休闲、社交消费；性别差异较大的网格需关注服务设施包容性、安全感、夜间照明、活动内容多元化；不得将性别差异直接解释为某类消费偏好，除非数据中有明确证据。"
                "必须分析人口密度分布，判断哪些区域具备更强的日常消费、夜间活动和文旅场景承接潜力。高密度不等于高消费，但通常代表潜在服务需求更集中；低密度区域不等于无价值，可能更适合公共休闲、开放空间、低强度活动或景观型体验。"
                "必须分析 POI 所反映的业态基础和文旅供给条件。判断 POI 总量是增长、下降、稳定、修复还是结构重组，说明商业服务基础是增强、收缩还是调整。识别末年主导业态、增长业态、稳定业态和弱势业态，判断区域更接近生活消费型、社区配套型、办公服务型、文教服务型、文旅消费型、夜间消费型或复合混合型。"
                "必须优先分析显著增长或显著下降的小类，并判断餐饮增长是否支撑日常消费、社交消费和夜间餐饮；住宿增长是否支撑停留消费、短暂停留和微度假；购物增长是否支撑生活配套和文创零售；科教文化增长是否支撑研学、展陈、文化活动；体育娱乐增长是否支撑休闲社交和夜间活动；旅游类不足是否说明文旅目的地属性仍弱。"
                "必须结合方向、圈层、热点、增长片区信号判断 POI 空间分布是内部加密、核心强化、多点扩散还是外扩不足。不得根据坐标自行编造具体道路、商圈或地标。"
                "必须分析夜间灯光所反映的夜间空间活力和夜间消费基础。分析 total_radiance 的多年变化，判断夜间整体活动强度是增强、稳定、波动还是衰退；分析 mean_radiance，判断夜间亮度提升是否具有整体性；分析 p90_radiance 和 max_radiance，p90用于判断高亮区域稳定性和强度，max用于辅助判断局部极值波动；分析 lit_pixel_ratio，点亮比例高说明夜间基础覆盖完整，但不能直接说明消费活力强。"
                "必须分析 increase_count、decrease_count、stable_count、hotspot_stable、hotspot_emerging、hotspot_faded，判断夜间空间活力属于高稳定活跃型、稳定增强型、增长潜力型、局部热点型、分化调整型或活力衰退型。"
                "核心交叉分析必须遵循：人口需求基础 -> POI业态供给 -> 夜光活力强度 -> 三者是否匹配 -> 文旅消费潜力 -> 项目策划定位 -> 业态与空间策略 -> 风险边界。"
                "必须完成人口密度 × POI供给判断：人口高密度区域是否有足够的餐饮、购物、科教文化、休闲娱乐、住宿等业态承接。人口密度高但POI不足，说明存在服务补位机会；人口密度高且POI丰富，说明具备生活消费和文旅转化基础；POI丰富但人口密度低，说明需进一步验证外来客流或目的性消费能力。"
                "必须完成年龄结构 × POI业态判断：主力年龄段与现有业态是否匹配。年轻人群与餐饮、娱乐、体育、夜间活力匹配时，可判断社交型夜经济潜力较强；亲子或家庭型人群与科教文化、公共休闲、餐饮配套匹配时，可判断亲子研学和家庭休闲潜力较强；中青年人群与餐饮、住宿、购物、夜光活力匹配时，可判断复合消费和夜间停留潜力较强。必须结合输入数据判断，不得套模板。"
                "必须完成性别结构 × 空间服务判断：整体性别比例和网格男女差异对公共空间安全感、夜间照明和导视、活动内容多元化、公共卫生间、休憩设施、亲子友好设施、夜间运营包容性和舒适性的启示。不得把性别差异直接等同于消费偏好。"
                "必须完成人口密度 × 夜间灯光判断：人口高密度区是否对应夜间亮度较强或增强网格较多。人口密度高且夜光增强，说明夜间生活活力和夜间消费基础较强；人口密度高但夜光弱，说明夜间活动转化不足或运营不足；夜光强但人口密度低，可能说明夜间活动来自外来人流、公共设施、照明或非居住活动，需要进一步验证。"
                "必须完成 POI业态 × 夜间灯光判断：餐饮强 + 夜光增强，说明夜间餐饮和社交消费基础较好；住宿增长 + 夜光增强，说明停留消费和延时消费具备基础；文化/体育娱乐增长 + 夜光增强，说明夜间活动和文旅体验具备导入条件；旅游弱 + 夜光增强，说明有夜间活力但缺少文旅吸引物。"
                "必须完成人口分布 × POI空间 × 夜光热点判断：三类空间信号是否一致。人口高密度、POI集聚和夜光热点空间上重合，可判断为空间耦合较强，是优先策划区；三者错位，需要判断是供给不足、夜间运营不足还是文旅内容缺失。只有部分数据有明确空间方向时，不得强行判断完全重合，应说明证据边界。"
                "必须将交叉分析转化为文旅策划语言，至少输出项目定位建议、目标客群建议、业态组合建议、空间组织建议、运营策略建议、风险与验证。"
                "项目定位建议格式应接近：以____客群为核心，以____业态为底盘，以____为夜间活力引擎，以____为内容增量，打造____型城市文旅消费场景。"
                "目标客群建议必须根据人口数据输出主力客群、机会客群和补充客群，每类客群必须说明数据依据和对应消费需求。"
                "业态组合建议可包括主题餐饮、夜间餐饮、轻餐饮、文创零售、文化展陈、研学体验、亲子活动、运动休闲、轻演艺、夜间市集、青年社交、住宿联动、微度假、公共休闲、生活配套等，但不得无依据堆砌业态，必须说明每个方向对应的数据依据。"
                "空间组织建议必须根据人口密度、人口分布、网格男女差异、POI空间、夜光热点提出强化既有热点、串联增强节点、培育新增热点、修复衰退区域、组织夜间消费轴线、多节点联动、分区运营等策略。如果没有明确道路或商圈证据，不得写具体道路或商圈名称。"
                "运营策略建议应以“建议”“可考虑”“适合进一步验证”的方式表达，可包括分时段运营、工作日/周末差异化、夜间活动植入、市集运营、轻演艺运营、餐饮外摆、亲子活动、青年社交活动、夜间导视、灯光氛围、安全管理、交通与停车协同等。"
                "风险与验证必须指出：人口数据不能直接代表消费；POI不能直接代表经营质量；夜光不能直接代表消费额；性别和年龄结构不能被刻板化解释；文旅类POI或文化内容可能不足；局部夜光减弱或热点衰退可能存在空间分化；后续需补充客流、消费、交通、营业时间、活动运营和实地调研验证。"
                "如果证据不足，必须明确写出：当前证据只能支持趋势判断，不能直接证明真实消费规模；仍需叠加客流、消费、交通、商户营业时间、活动运营和实地调研数据验证。"
                "输出中文，专业、理性、适合城市文旅策划报告，不要写成纯技术报告，不要堆砌数据。"
                "必须只输出 JSON，不要输出 markdown。JSON 固定为 {\"title\":\"文旅交叉策划分析\",\"content\":\"...\"}。"
                "content 内部必须使用以下中文分节标题：一、综合判断；二、人口客群与空间需求基础；三、POI业态与商业供给基础；四、夜间灯光与夜间活力基础；五、人口 × POI × 夜光交叉诊断；六、文旅策划转化方向；七、空间与运营策略；八、问题与风险；九、策划结论。"
                "第九节必须输出一句：该地块适合以____为核心客群，以____为底盘，以____为夜间活力引擎，以____为内容增量，以____为空间承载，打造____型城市文旅消费场景。"
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
                "H3 证据可用于判断网格密度、混合度、邻域均值、热点/冷点、LISA、LQ、缺口、类别结构、空间集聚和年度变化；不得用网格坐标编造道路、商圈、地标、客流、收入或外部游客来源。"
                "不得使用证据包之外的信息。不得凭空编造城市发展背景、政策、地铁、道路、商圈、学校、景区、人口、房价、消费等级或外部事件。位置判断只能来自证据中已有区域、方向、圈层、热点或空间信号字段。"
                "证据不足时必须写明“证据信号有限”“无法直接判断原因”或“只能作趋势性推断”。原因分析必须基于证据链，可提出可能原因，但要说明依据来自总量变化、一级业态变化、细分业态变化、空间分布变化、网格变化或显著增减类目。"
                "判断重要变化时优先考虑绝对增减量、末年数量、末年占比、主导程度、连续趋势和空间集中程度，不要只依据百分比增速。"
                "报告必须覆盖这些章节：总体判断、主导业态、业态结构、空间特征、变化原因、策划启示、总结判断。"
                "可选专题章节只在证据显著时出现，例如旅游、文教、体育、商务办公、购物、住宿等；不得固定输出“住宿与停留”。"
                "每个章节写成正式报告段落，遵循“数据现象 -> 结构判断 -> 策划含义”的表达。章节内容要有具体数据依据，避免只有短句。"
                "只输出一个 JSON 对象，不要输出 markdown、解释说明或代码块。唯一允许的 JSON 结构如下："
                "{\"report_title\":\"业态基础分析总结报告\",\"report_sections\":[{\"heading\":\"一、总体判断：...\",\"paragraphs\":[\"数据现象、结构判断与策划含义写成一个完整段落。\"]}],\"report_content\":\"业态基础分析总结报告\\n\\n一、总体判断：...\\n\\n完整报告正文\"}"
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
