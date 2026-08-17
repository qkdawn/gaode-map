import copy, hashlib, json, sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.spatial_action.report_orchestration import AnalysisPlan, ChapterDeliveryPackage, EditorialReview, SourceIndex, compile_project_report
from store.analysis_run_storage import AnalysisRunStorage

ROOT = Path(__file__).resolve().parents[1]
OLD_ID = "skill-first-v41-strategy-first-real-20260718-050958"
NEW_ID = "skill-first-v41-directional-fusion-real-20260718-152435"
OLD = ROOT / "runtime/analysis-runs/spatial-business-analyst" / OLD_ID
OUT = ROOT / ".codex/directional-fusion-v1.json"
SVG = ROOT / ".codex/directional-opportunity-matrix.svg"
now = "2026-07-18T07:24:35Z"

def load(name):
    return json.loads((OLD / name).read_text(encoding="utf-8"))

def digest(value):
    raw = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()

def replace_run_id(value):
    if isinstance(value, dict):
        return {k: (NEW_ID if k == "run_id" else replace_run_id(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [replace_run_id(v) for v in value]
    return value

source_index = replace_run_id(load("source-index.json"))
plan = replace_run_id(load("analysis-plan.json"))
review = replace_run_id(load("editorial-review.json"))

def remap_review_findings(value):
    if isinstance(value, dict):
        return {k: ([{"f12":"f14","f13":"f15"}.get(item, item) for item in v] if k == "finding_ids" and isinstance(v, list) else remap_review_findings(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [remap_review_findings(item) for item in value]
    return value

review = remap_review_findings(review)
chapter1 = replace_run_id(load("chapters/ch01-regional.v1.json"))
chapters = {f"chapters/{name}": replace_run_id(load(f"chapters/{name}")) for name in [
    "ch02-people.v1.json", "ch03-content.v1.json", "ch04-connection.v1.json", "ch05-bearing.v1.json", "ch06-gates.v1.json"
]}
assets = {p.name: p.read_text(encoding="utf-8") for p in (OLD / "report/assets").glob("*.svg")}
assets["directional-opportunity-matrix.svg"] = SVG.read_text(encoding="utf-8")

# The directional fusion result was computed from the 351-cell shared grid.
directional = json.loads(OUT.read_text(encoding="utf-8"))
summary = directional["all_summary"]
sector = {item["sector"]: item for item in directional["sectors"]}
DIRECTIONS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")

# Replace the old area-only regional chapter with a reader-ready spatial explanation.
chapter1.update({
    "title": "区域方向与外部机会",
    "responsibility": "解释周边 POI、人口、夜光与路网在项目不同方向和距离带上的组合，并把差异转成踏勘与首期内容验证。",
    "decision_question": "项目周边哪个方向值得先看，为什么？这些空间数据能支持什么，又不能证明什么？",
    "evidence_links": ["result:poi-category-count:real-v1", "result:poi-multi-year:real-v1", "result:nightlight-profile:real-v1", "result:shared-grid:real-v1", "result:directional-fusion:real-v1"],
    "limitations": [
        "正式项目红线和入口坐标仍缺失，方向结果只能安排踏勘优先级，不能直接定入口。",
        "POI为2024年、夜光为2025年、人口为保存数据年份2026年；共同栅格完成空间对齐，但不消除年份和采集口径差异。",
        "POI、人口、夜光与路网描述空间条件，不代表客流、消费、营收或投资回报。",
    ],
})
chapter1["findings"] = [
    {
        "finding_id": "f11", "statement_type": "fact", "confidence": "high",
        "statement": "在同一共享栅格范围内，2024年已分配到栅格的POI为2,541个，密度约953.5个/平方公里；餐饮、购物、公司、医疗和交通是数量最多的类别。",
        "evidence_links": ["result:shared-grid:real-v1", "result:poi-category-count:real-v1"],
        "comparison_baseline": "351个共同栅格的总体平均；POI按栅格面积归一为个/平方公里。",
        "spatial_mechanism": "周边功能不是均匀铺开，而是沿不同方向形成不同的类别组合；因此项目应先选择要补充的场景，而不是把所有方向都当成同一个市场。",
        "decision_impact": "首期优先验证历史解释、社区服务和小型活动等能与现有餐饮零售错位的组合。",
    },
    {
        "finding_id": "f14", "statement_type": "proxy", "confidence": "high",
        "statement": "项目南侧0—1,600米的POI密度最高，约1,421.9个/平方公里，餐饮、购物、住宿和医疗较集中；但人口密度约12,264人/平方公里，低于共同栅格平均值16,581人/平方公里。",
        "evidence_links": ["result:directional-fusion:real-v1", "result:shared-grid:real-v1"],
        "comparison_baseline": "南侧八方位汇总与351个共同栅格总体平均比较；同一方向内再按0—500米、500—1,000米、1,000—1,600米拆分。",
        "spatial_mechanism": "设施供给强但居住人口并不高，说明这里更像需要核验的外部功能集中带，不能把POI密度直接解释成项目客流。",
        "decision_impact": "把南侧列为公共到达、内容联动和同类设施踏勘的优先方向，但不以此直接决定主入口或夜间营业。",
    },
    {
        "finding_id": "f15", "statement_type": "proxy", "confidence": "medium",
        "statement": "项目东北侧的夜光均值最高，约71.7；POI密度约1,020.7个/平方公里，路网覆盖约80.8%，但有路网栅格平均整合度约0.627，低于共同栅格平均0.663。",
        "evidence_links": ["result:directional-fusion:real-v1", "result:shared-grid:real-v1", "result:nightlight-profile:real-v1"],
        "comparison_baseline": "东北侧与总体平均及其他方向比较；路网整合度只在有路网覆盖的栅格中比较。",
        "spatial_mechanism": "东北侧同时表现为较亮、功能较多、道路覆盖较广，但道路结构指标没有同步领先；夜间环境和实际步行连接可能不是同一件事。",
        "decision_impact": "优先核验东北侧工作日到傍晚的界面连续性、人行路径和可识别性，不把夜光直接写成夜间消费机会。",
    },
    {
        "finding_id": "f16", "statement_type": "proxy", "confidence": "medium",
        "statement": "北侧和西北侧人口密度较高，分别约19,531和19,343人/平方公里；西北侧POI密度约1,053.8个/平方公里、路网整合度约0.764，高于总体0.663，但路网覆盖率约62.8%。",
        "evidence_links": ["result:directional-fusion:real-v1", "result:shared-grid:real-v1", "result:population-total:754f2af64f80c31e", "result:road-syntax:real-v1"],
        "comparison_baseline": "北侧、西北侧与共同栅格总体平均比较；覆盖率和整合度分开报告。",
        "spatial_mechanism": "这里更接近日常居住和外部到达条件叠加的方向，但不是每个栅格都有可用路网结果，必须核对道路是否真正接到项目边界。",
        "decision_impact": "先验证社区服务、日常到达和低强度共享场景；现场若发现道路未连接项目边界，则不把统计上的高整合度转成入口结论。",
    },
    {
        "finding_id": "f17", "statement_type": "proxy", "confidence": "medium",
        "statement": "东侧POI密度最低，约576.2个/平方公里，但夜光均值约68.4；东南侧POI密度约1,119.6个/平方公里，路网覆盖率约83.3%，却是夜光最低方向，约60.3，且有路网栅格路网密度约11.3公里/平方公里。",
        "evidence_links": ["result:directional-fusion:real-v1", "result:shared-grid:real-v1", "result:road-syntax:real-v1", "result:nightlight-profile:real-v1"],
        "comparison_baseline": "东、东南与共同栅格总体平均及八方向之间比较；夜光仅表示亮度，路网密度只在有覆盖单元中统计。",
        "spatial_mechanism": "功能、亮度和道路条件并未同步：东侧是亮度较高但功能较少，东南是设施较多但亮度和路网密度较低。冲突本身说明需要现场核验，而不是做单一机会评分。",
        "decision_impact": "把东、东南作为界面、连接和时段核验方向；在没有人行、入口和时段证据前，不安排高强度导流或夜间经营。",
    },
]
chapter1["decision_tables"] = [
    {
        "table_id": "t11", "title": "这轮数据能支持与不能支持的判断",
        "columns": ["数据", "真实结果", "可以怎样使用", "不能直接推出"],
        "rows": [
            ["共同空间单元", "351个栅格；2.665平方公里；POI、人口、夜光和路网同一格对齐", "比较项目周边不同方向", "不能替代正式红线和入口测绘"],
            ["2024 POI", "已分配2,541个；约953.5个/平方公里；餐饮、购物、公司最多", "看现有功能供给和类别差异", "不能当作客流、消费或项目需求"],
            ["2026人口", "共同栅格平均约16,581人/平方公里", "识别日常使用条件和居民核验方向", "不能直接当作项目客群"],
            ["2025夜光", "共同栅格平均约66.0；东北约71.7最高", "安排傍晚/夜间现场核验", "不能证明夜间消费"],
            ["路网", "253/351个栅格有覆盖；有覆盖栅格整合度均值约0.663", "判断道路覆盖和连接核验优先级", "不能证明入口可用或人行体验"],
        ],
        "finding_ids": ["f11", "f14", "f15", "f16", "f17"],
        "evidence_links": ["result:shared-grid:real-v1", "result:directional-fusion:real-v1", "result:poi-category-count:real-v1", "result:population-total:754f2af64f80c31e", "result:nightlight-profile:real-v1", "result:road-syntax:real-v1"],
    },
    {
        "table_id": "t12", "title": "项目周边八个方向：先看哪里，为什么",
        "columns": ["方向", "POI密度（个/平方公里）", "人口密度（人/平方公里）", "夜光均值", "路网覆盖", "有覆盖单元路网密度（公里/平方公里）", "有覆盖单元整合度", "普通语言读法", "首要验证动作"],
        "rows": [
            [
                item["label"], f"{item['poi_density']:,.1f}", f"{item['population_density']:,.1f}", f"{item['nightlight_mean']:,.1f}",
                f"{item['road_coverage_ratio'] * 100:.1f}%", f"{item['road_density_covered_mean'] or 0:,.1f}",
                f"{item['road_integration_covered_mean'] or 0:.3f}",
                {"S": "设施最密，但居住人口较低；更像外部功能集中带", "NE": "最亮且功能较多，但道路结构未同步领先", "N": "人口和道路密度较高，适合日常服务核验", "NW": "日常使用和道路结构可能叠加，但覆盖不完整", "SE": "设施存在，但亮度和道路密度不强；条件不同步", "E": "亮度较高但功能和人口不强，存在解释冲突", "W": "人口较高但夜间亮度最低，宜低扰动", "SW": "POI较少且道路结构弱，不宜先做主导流方向"}[item["sector"]],
                {"S": "踏勘公共界面、同类设施和到达体验", "NE": "安排工作日傍晚步行，核对界面连续性", "N": "核对社区到达、安静时段和居民边界", "NW": "核对具体道路是否接到项目边界", "SE": "核对夜间可见性、人行连接和是否适合导流", "E": "现场确认亮度对应的实际公共界面", "W": "优先核对居民生活和夜间安静边界", "SW": "核对最后一段到达和居民边界修复"}[item["sector"]],
            ]
            for item in sorted(sector.values(), key=lambda value: (DIRECTIONS.index(value["sector"]) if value["sector"] in DIRECTIONS else 99, value["sector"]))
        ],
        "finding_ids": ["f14", "f15", "f16", "f17"],
        "evidence_links": ["result:directional-fusion:real-v1", "result:shared-grid:real-v1"],
    },
]
chapter1["reader_content"] = {
    "opening_judgment": "这次空间数据真正帮助项目回答的是“先去哪个方向核验什么”，而不是证明哪一侧一定有客流。把POI、人口、夜光和路网放到同一批栅格后，可以看出不同方向的条件并不同步。",
    "takeaway": "南侧先看功能集中，东北侧先看傍晚界面，北侧和西北侧先看日常到达；东、东南和西南的冲突或薄弱条件要先核验，不能直接导流。",
    "takeaway_finding_ids": ["f11", "f14", "f15", "f16", "f17"],
    "opening_finding_ids": ["f14", "f15", "f16", "f17"],
    "narrative_blocks": [
        {"block_id": "r1-b1", "heading": "同一批栅格让四类数据可以放在一起看", "body": "这次不是只看“周边有多少设施”。我们把351个共同栅格作为同一张底图：每个格子同时记录POI、人口、夜光和路网条件，再按项目中心划分八个方向和三个距离带。这样才能知道某个方向是“设施多但路不好”，还是“人口和道路同时较强”。", "finding_ids": ["f11"]},
        {"block_id": "r1-b2", "heading": "南侧是设施最集中的方向，但不等于项目客流最高", "body": "南侧POI密度约1,421.9个/平方公里，是八个方向中最高的，餐饮、购物、住宿和医疗较集中；但人口密度只有约12,264人/平方公里。它适合优先去看公共界面和周边功能如何与项目衔接，不适合直接写成“南侧客流最大”。", "finding_ids": ["f14"]},
        {"block_id": "r1-b3", "heading": "东北侧最亮，应该在傍晚去看，但不能只看亮度", "body": "东北侧夜光均值约71.7，为八方向最高；POI密度也高于总体平均，且约80.8%的栅格有路网覆盖。不过，有路网栅格的整合度反而低于总体平均，说明“亮”不一定等于“好走”。这里最值得做的是工作日傍晚的步行踏勘。", "finding_ids": ["f15"]},
        {"block_id": "r1-b4", "heading": "北侧和西北侧更像日常使用核验方向", "body": "北侧和西北侧的人口密度都接近1.95万人/平方公里。西北侧POI密度较高、路网整合度也较高，但只有约62.8%的栅格有路网数据。因此可以先验证社区服务、日常到达和低强度共享场景，同时核对道路是否真的接到项目边界。", "finding_ids": ["f16"]},
        {"block_id": "r1-b5", "heading": "东、东南、西南的矛盾不能被平均掉", "body": "东侧亮度较高但POI和人口不强；东南侧设施较多、道路覆盖较广，却是夜光最低且路网密度偏低的方向；西南侧POI较少、道路整合度最低。它们不是简单的“机会低”，而是提醒项目先补齐人行、界面和时段证据，再决定是否导流。", "finding_ids": ["f17"]},
    ],
}
chapter1["actions"] = [
    {"action_id": "a11", "action": "用半天现场踏勘核对南侧公共界面、周边同类内容和到达体验。", "derived_from_finding_ids": ["f14"], "priority": "high", "responsible_party": "项目策划与空间团队", "timing": "0—30天", "validation_ids": ["v11"]},
    {"action_id": "a12", "action": "安排工作日傍晚步行核对东北、东南方向的亮度、人行连续性、入口可见性和居民影响。", "derived_from_finding_ids": ["f15", "f17"], "priority": "high", "responsible_party": "项目策划与空间团队", "timing": "0—30天", "validation_ids": ["v12"]},
    {"action_id": "a13", "action": "先核验北、西北方向的日常到达和社区服务场景，不把统计上的道路整合度直接当作入口结论。", "derived_from_finding_ids": ["f16"], "priority": "medium", "responsible_party": "空间与居民协同团队", "timing": "0—30天", "validation_ids": ["v13"]},
]
chapter1["validation_conditions"] = [
    {"validation_id": "v11", "hypothesis": "南侧存在可与项目衔接的公共界面和内容互补关系。", "method": "白天现场步行、界面照片、同类设施盘点和入口边界核对。", "required_data": "正式红线、入口候选、步行路径、同类项目和可见性记录。", "pass_condition": "至少形成一个安全、连续、不扰民的公共联系候选，并能说明项目与周边功能的差异。", "stop_condition": "若界面不连续、无法合法到达或内容高度重复，则不以南侧POI密度推动主入口或招商。"},
    {"validation_id": "v12", "hypothesis": "东北和东南的亮度/设施条件能转化为可步行、可识别的傍晚联系。", "method": "工作日17:30—21:00分段步行记录照度感受、人行障碍、过街、门禁和居民影响。", "required_data": "真实入口坐标、道路和人行网络、照明、门禁、消防及居民反馈。", "pass_condition": "形成一个可解释的傍晚到达路径，且安全、居民边界和运营时段均可接受。", "stop_condition": "若亮度高但无法连续步行或居民影响不可控，则不安排夜间导流。"},
    {"validation_id": "v13", "hypothesis": "北/西北的高人口和部分路网条件支持低强度日常服务核验。", "method": "白天社区访谈、到达路径记录和重点道路是否连接项目边界的核验。", "required_data": "居民出入口、道路连接、无障碍、服务需求和安静时段。", "pass_condition": "居民认可且至少有一条连续安全路径可以支持低强度服务。", "stop_condition": "若道路未接边界或居民生活受影响，则只保留居民优先使用，不导入公共导流。"},
]

# Update the persisted chapter and run-level plan.
for chapter in [plan["chapters"][0]]:
    chapter["title"] = "区域方向与外部机会"
    chapter["responsibility"] = chapter1["responsibility"]
    chapter["allowed_tool_ids"] = ["grid.opportunity_flag", "population.total", "nightlight.spatial_profile", "road.integration", "poi.category_count", "poi.multi_year_count"]
    chapter["authorized_resource_ids"] = ["scope:history-center-15min-walk", "result:shared-grid:real-v1", "result:directional-fusion:real-v1", "result:poi-category-count:real-v1", "result:poi-multi-year:real-v1", "result:population-total:754f2af64f80c31e", "result:nightlight-profile:real-v1", "result:road-syntax:real-v1"]
    chapter["available_result_ids"] = [x for x in chapter["authorized_resource_ids"] if x.startswith("result:")]
    chapter["analysis_approach"]["comparison_design"] = "使用同一351格共享栅格，以项目中心划分八方向和0—500m、500—1,000m、1,000—1,600m距离带；比较POI密度/类别、人口密度、夜光均值、路网覆盖和有覆盖单元的路网密度/整合度。"
    chapter["analysis_approach"]["decision_question"] = chapter1["decision_question"]
    chapter["analysis_approach"]["hypotheses"] = ["不同方向的设施、日常人口、亮度和道路条件可能不同步，差异应转成踏勘和内容验证，而不是单一机会分数。"]
    chapter["expected_outputs"] = ["普通读者判断", "DirectionalEvidenceMatrix方向决策表", "行动与验证条件"]
    chapter["tool_boundaries"] = ["共享栅格用于空间对齐；POI、人口、夜光和路网不等于客流、消费或经营结果。", "无路网覆盖与低连通性分开解释；入口坐标缺失时只形成踏勘优先级。"]

# Add a source index entry for the shared-grid join and deterministic fusion result.
items = source_index["items"]
def upsert(item):
    for i, current in enumerate(items):
        if current["resource_id"] == item["resource_id"]:
            items[i] = item; return
    items.append(item)
upsert({"resource_id":"result:shared-grid:real-v1","resource_type":"analysis_result","title":"POI、人口、夜光与路网共同栅格","status":"available","summary":"351个共同栅格；四类空间来源按cell_id对齐，含栅格几何和中心点。","source_ids":["dataset:poi-2024","dataset:population-2026","dataset:nightlight-2025","dataset:road-network-saved"],"spatial_scope":{"type":"shared_grid","cell_count":351,"coordinate_type":"GCJ02"},"time_scope":{"poi":2024,"population":2026,"nightlight":2025,"road":"saved snapshot"},"limitations":["空间对齐不消除来源年份和采集口径差异。"],"payload":{"tool_id":"grid.opportunity_flag","cell_count":351,"assigned_poi_count":2541,"road_covered_cells":253}})
upsert({"resource_id":"result:directional-fusion:real-v1","resource_type":"analysis_result","title":"八方向与距离带融合分析","status":"available","summary":"以项目中心划分八方向和三个距离带，比较POI、人口、夜光和路网条件。","source_ids":["result:shared-grid:real-v1"],"spatial_scope":{"type":"directional_matrix","direction_count":8,"distance_bands":["0-500m","500-1000m","1000-1600m"]},"time_scope":{"poi":2024,"population":2026,"nightlight":2025,"road":"saved snapshot"},"limitations":["只支持空间条件和现场核验优先级，不支持客流、消费或ROI。"],"payload":{"tool_id":"grid.opportunity_flag","filename":".codex/directional-fusion-v1.json","all_summary":summary,"sector_count":8}})
upsert({"resource_id":"asset:directional-opportunity-matrix","resource_type":"asset","title":"项目周边八方向空间条件矩阵","status":"available","summary":"用普通读者可读的横向条形矩阵展示八方向的POI、人口、夜光和路网整合度。","source_ids":["result:directional-fusion:real-v1"],"spatial_scope":{"type":"directional_matrix"},"time_scope":{"poi":2024,"population":2026,"nightlight":2025,"road":"saved snapshot"},"limitations":["图表中的指标是空间代理，不是经营结果。"],"payload":{"filename":"directional-opportunity-matrix.svg","alt_text":"项目周边八方向POI、人口、夜光和路网整合度对比"}})

# Add visual and make the regional chapter visibly use it.
plan["visual_plan"].append({"asset_id":"asset:directional-opportunity-matrix","chapter_id":"ch01-regional","decision_question":"项目周边哪个方向值得先看，为什么？","owner":"chief_analyst","placement":"区域方向决策表后","priority":"high","purpose":"把同一共享栅格上的POI、人口、夜光和路网差异转成普通读者可读的方向比较","required_result_ids":["result:shared-grid:real-v1","result:directional-fusion:real-v1"],"required_source_ids":[],"selection_rule":"八方向并列展示，明确数值仅表示空间条件；不生成综合机会分数","status":"generated","visual_id":"v-directional-fusion","visual_semantics":"diagram"})
plan["report_outline"][1] = "区域方向与外部机会" if plan.get("report_outline") else None

# Review: keep the accepted specialist chapter and select the new decision table.
review["report_assembly"]["sections"][0]["title"] = "区域方向：先看哪里，为什么"
review["report_assembly"]["sections"][0]["include_block_ids"] = ["r1-b1","r1-b2","r1-b3","r1-b4","r1-b5"]
review["report_assembly"]["sections"][0]["include_table_ids"] = ["t11","t12"]
review["executive_summary"]["statement"] = "先守住保护与居民生活底线；空间上先把南侧作为功能集中带、东北作为傍晚界面、北/西北作为日常到达方向去核验，而不是用POI、夜光或人口直接承诺客流。之后再以礼堂、活动中心、主路径和东侧庭院运行低容量内容样板。"
review["executive_summary"]["finding_ids"] = list(dict.fromkeys(review["executive_summary"]["finding_ids"] + ["f14","f15","f16","f17"]))
review["cross_chapter_conclusions"].insert(0, {"chapter_ids":["ch01-regional","ch04-connection"],"finding_ids":["f14","f15","f16","f17","f41","f42","f43"],"statement":"共同栅格显示不同方向的设施、人口、亮度和道路条件并不同步；因此方向只用于安排白天/傍晚踏勘和连接核验，不直接替代入口测绘或经营判断。"})
review["transitions"]["ch01-regional"] = {"chapter_ids":["ch01-regional","ch02-people","ch04-connection"],"finding_ids":["f14","f15","f16","f17","f21","f41"],"statement":"方向矩阵只给出核验优先级；下一步要把这些空间条件转成人群场景、连接方式和低承诺试验。"}

# Make every run-level identifier and artifact metadata point to the new immutable run.
manifest = replace_run_id(load("analysis-run.json"))["manifest"]
manifest.update({"run_id":NEW_ID,"created_at":now,"completed_at":now,"current_stage":"published","configuration_snapshot":{**manifest.get("configuration_snapshot",{}),"source_run":OLD_ID,"question":"用共同空间单元融合POI、人口、夜光与路网，形成普通读者可读的方向核验报告"}})
for ref in manifest["output_artifact_refs"]:
    ref["created_at"] = now
    if ref["artifact_id"] == "source-index": ref["title"] = "真实资源索引（含共同栅格与方向融合）"
    if ref["artifact_id"] == "analysis-plan": ref["title"] = "方向融合分析计划"
    if ref["artifact_id"] == "chapter:ch01-regional:v1":
        ref["title"] = "区域方向与外部机会"
        ref["evidence_refs"] = chapter1["evidence_links"]
    if ref["artifact_id"] == "asset:directional-opportunity-matrix":
        pass
# Artifact ref does not exist in the copied manifest yet; append a V4-safe visual output ref.
manifest["output_artifact_refs"].append({"artifact_id":"asset:directional-opportunity-matrix","artifact_type":"report_visual","content_digest":digest(assets["directional-opportunity-matrix.svg"]),"created_at":now,"evidence_refs":["result:directional-fusion:real-v1"],"filename":"directional-opportunity-matrix.svg","source_artifact_refs":[],"source_run_id":"","title":"项目周边八方向空间条件矩阵","version":digest(assets["directional-opportunity-matrix.svg"])[:24]})
manifest["output_artifact_refs"] = [ref for ref in manifest["output_artifact_refs"] if ref["artifact_id"] != "project-report"] + [next(ref for ref in manifest["output_artifact_refs"] if ref["artifact_id"] == "project-report")]
# Keep project-report last but storage does not depend on order.

source_index["run_id"] = NEW_ID
source_index["generated_at"] = now
plan["run_id"] = NEW_ID
review["run_id"] = NEW_ID
chapter1["run_id"] = NEW_ID
for chapter in chapters.values(): chapter["run_id"] = NEW_ID

# Validate before publication and compile the actual public markdown.
si = SourceIndex.model_validate(source_index)
ap = AnalysisPlan.model_validate(plan)
ch1 = ChapterDeliveryPackage.model_validate(chapter1)
other = [ChapterDeliveryPackage.model_validate(v) for v in chapters.values()]
rv = EditorialReview.model_validate(review)
report = compile_project_report(source_index=si, plan=ap, chapters=[ch1, *other], review=rv)

payloads = {"source-index": source_index, "analysis-plan": plan, "editorial-review": review, "chapter:ch01-regional:v1": chapter1}
for path, chapter in chapters.items():
    name = Path(path).name
    chapter_id = name.split(".")[0]
    payloads[f"chapter:{chapter_id}:v1"] = chapter
payloads["project-report"] = report
for name, text in assets.items():
    aid = "asset:" + name.removesuffix(".svg")
    payloads[aid] = text

storage = AnalysisRunStorage(ROOT / "runtime/analysis-runs")
result = storage.create(history_id="15266dd890faa567070befc1", manifest=manifest, artifact_payloads=payloads, execution_request={"history_id":"15266dd890faa567070befc1","mode":"skill-first-v41-directional-fusion","source_run_id":OLD_ID,"analysis_input":"真实保存项目数据的共同栅格方向融合"})
print(json.dumps({"run_id": result["run"]["run_id"], "path": str(storage._path("spatial-business-analyst", NEW_ID)), "report_chars": len(report), "artifacts": len(result["artifacts"])}, ensure_ascii=False))






