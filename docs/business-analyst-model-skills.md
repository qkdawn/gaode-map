# ESRI Business Analyst Model Graph 与 Agent Skill 调用体系设计

## 1. 结论先行

当前系统已经逐步形成了几层底座：

- 来源层：系统数据、文档、网页、图片都被处理成统一 `EvidenceNode`。
- 工具层：MCP / tool registry 让 AI 能调用来源、读取当前范围数据、运行已有分析能力。
- Agent 层：ReAct / tool loop 让 AI 能自主调用工具，但它本身不等于专业分析方法。
- 生成层：PPT / 报告本质上是 skill 的可视化和可微调表达。

这些底座都重要，但它们不能自动产生“商业地产分析推理感”。RAG 能让模型找到资料，ReAct 能让模型调用工具，PPT 能把结果可视化，但真正缺的是：

```text
一套显式的、可调用的、可导航的商业分析理论结构。
```

这套结构应该来自 ESRI Business Analyst 的成熟方法论，但不要照搬成固定模板。更好的方向是：

```text
把 Business Analyst 的“模型思想”做成可调用的 domain model，
把模型之间的业务关系做成 Model Graph，
把“分析方法、工具对应关系、执行流程、裁剪策略”写成 Agent Skill，
把“不能越界的判断”留给 guardrail。
```

也就是说，本项目应该形成三层：

```text
Business Analyst for Agent
├─ Model Graph  商业分析模型之间的业务语义关系，AI 在图上导航
├─ Models       商业地理分析模型思想，可计算、可测试、可复用
├─ Skills       给 AI Agent 调用的分析技能，引用模型图并描述工具映射与裁剪策略
└─ Guardrails   证据边界与禁止外推，只负责兜底治理，不主导分析过程
```

这比单纯的 `Reasoning Card + Rule` 更适合当前目标。`Reasoning Card` 可以继续存在，但应退到“模型运行后的解释产物”或“前端展示形态”，不应该成为主架构。主架构应是：

```text
Model Graph + Models + Skills + Guardrails
```

核心原因：

- ESRI BA 的真正价值是成熟的分析模型思想，不是固定报告模板。
- 模型之间的关系不是线性流程，而是一个可裁剪、可跳转、可组合的分析图。
- AI Agent 需要自主判断问题、选择图上的路径、调用工具、调整顺序、追问和停机。
- Skill 应给 AI “专业能力说明书”，而不是把 AI 变成填表机器。
- Model 层负责稳定计算和结构化中间结果，避免所有逻辑都塞进 prompt。
- Guardrail 只阻止胡说，例如禁止把人口直接说成消费力、把 Huff proxy 说成真实市场份额。

一句话定义：

> 用 Business Analyst Model Graph 提供可导航的分析结构，用 Models 提供专业分析算子，用 Skills 说明如何使用图和工具，用 Guardrails 保护证据边界，让现有 AI Agent 在商业地产与选址场景中自主但不失控地分析。

## 2. 推理本体不是 Agent / RAG / MCP / PPT

过去系统的思路经历了几次转变，每次转变都解决了真实问题，但也暴露了各自边界。

### 2.1 EvidenceNode 解决来源统一，不解决分析方法

系统数据、文档、网页、图片被处理成统一 `EvidenceNode` 是正确方向。它解决的是：

```text
不同来源如何被 AI 可靠读取、引用和复盘。
```

但 `EvidenceNode` 本身不是分析方法。它告诉 AI “有什么证据”，不告诉 AI “应该怎样分析这些证据”。

正确关系应该是：

```text
来源 -> EvidenceNode -> Model 输入 -> ModelResult -> Agent 回答 / PPT
```

而不是：

```text
来源 -> EvidenceNode -> 直接让 LLM 写结论
```

### 2.2 MCP / Tool Registry 解决调用，不解决推理

MCP 或工具注册让 AI 能调用来源、搜索数据、运行分析工具。它解决的是：

```text
AI 如何访问系统能力。
```

但它不决定：

- 先看需求还是供给。
- 什么情况下需要 Huff。
- 什么情况下只能做预筛。
- 哪些指标不能外推成商业结果。

所以工具层必须服务于模型图，而不是让 Agent 在工具列表里自由碰运气。

### 2.3 ReAct / Agent 框架解决执行循环，不天然产生分析体系

ReAct 的价值是“边想边调用工具”。但如果它面对的是一堆工具和 EvidenceNode，而没有分析理论结构，就会出现：

- 回复有工具痕迹，但缺乏推理感。
- deep 模式时间更长，但不一定更专业。
- quick 模式更快，但更像摘要。
- Agent 看似会行动，但行动不一定构成商业分析链。

所以问题不是 ReAct 不够复杂，而是 ReAct 缺少一张可导航的 Business Analyst Model Graph。

### 2.4 PPT 是 Skill 的可视化，不是推理本体

PPT 的本质不是另一个 AI 系统，而是 skill 结果的可视化表达。它适合：

- 展示分析过程。
- 修改和微调表达。
- 把模型结果组织成汇报结构。

但 PPT 不应该承担分析推理本体。真正的分析应先发生在 Model Graph 和 Skill 调用里，PPT 只消费结构化结果。

### 2.5 微调不是优先解法

“缺乏推理感”不宜优先用微调解决。微调本质是后训练，让模型更适配某类输出和风格，但它很难可靠固化一套复杂、可复盘、可更新的商业分析体系。

模型能力主要来自预训练、后训练和推理部署端的整体演进。微调不能替代明确的分析结构。更稳的路线是：

```text
把分析体系显式化为 Model Graph + Skill，
让未来更强的模型也能继续沿这套结构工作。
```

### 2.6 对前一版 Card / Rule 方案的修正

前一版把体系设计成 `Reasoning Card + Rule + Card Pack`。这有价值，但问题是它太像专家系统：

```text
Card Pack 规定流程
AI 按卡片顺序填空
Rule 检查是否违规
```

这会带来三个风险：

1. AI 自主性不足  
   用户问题不一定完整符合预设 pack。强行套 pack 会让 Agent 像固定流程系统，而不是分析助手。

2. 模型思想没有沉淀  
   Huff、Trade Area、Retail Gap、Suitability 本质上是可复用模型思想。如果只写进卡片，就难以测试、难以复用、难以进化。

3. Rule 过度主导  
   Rule 应该负责边界治理，而不是负责整个分析逻辑。否则系统会变成“规则推理器”，不是“有专业工具的 AI Agent”。

因此新版建议改为：

```text
旧：Reasoning Card / Rule / Pack 是主架构
新：Model Graph / Model / Skill / Guardrail 是主架构
```

映射关系：

| 旧概念 | 新位置 |
| --- | --- |
| Reasoning Card | 降级为模型结果解释卡、前端过程展示或 Finalizer 的结构化中间产物。 |
| Rule | 降级为 Guardrail，只处理证据边界、禁用结论和审计要求。 |
| Card Pack | 升级为 Skill，但 Skill 允许 AI 自主裁剪、跳步、重排和组合。 |
| Prompt 规则 | 收敛为 Model Graph + Skill spec + Model schema + Guardrail spec。 |

## 3. 这套体系应该是什么形式

推荐目录：

```text
modules/business_analyst/
├─ __init__.py
├─ schemas.py
├─ model_graph.py
├─ model_registry.py
├─ skill_registry.py
├─ guardrails.py
├─ planner.py
├─ graphs/
│  ├─ commercial_site_selection.yaml
│  ├─ area_commercial_diagnosis.yaml
│  └─ competition_impact.yaml
├─ models/
│  ├─ trade_area.py
│  ├─ huff_gravity.py
│  ├─ market_potential.py
│  ├─ retail_gap.py
│  ├─ customer_profile.py
│  └─ site_suitability.py
└─ skills/
   ├─ area_diagnosis.yaml
   ├─ single_category_site_selection.yaml
   ├─ competition_impact.yaml
   ├─ customer_profile_review.yaml
   └─ existing_site_review.yaml
```

其中：

- `graphs/*.yaml` 定义 Business Analyst Model Graph，即模型之间的业务语义关系。
- `models/` 是真正的商业分析模型层，输入输出稳定，可单测。
- `skills/*.yaml` 是给 Agent 看的技能说明，描述什么时候用哪张图、入口节点、目标节点、工具映射和裁剪策略。
- `guardrails.py` 是硬边界，阻止越界表述。
- `planner.py` 不替 AI 做全部决定，只辅助选择候选 skill、查找图路径和补齐模型输入。
- `schemas.py` 统一 `ModelGraph`、`ModelNode`、`ModelEdge`、`ModelInput`、`ModelResult`、`SkillSpec`、`SkillRunPlan`、`GuardrailFinding`。

存储形式建议：

| 资产 | 初期形式 | 后续形式 |
| --- | --- | --- |
| Model Graph | YAML / JSON | 可视化编辑、版本化、灰度 |
| Model 代码 | Python module | 保持 Python，逐步增强算法 |
| Skill 描述 | YAML 或 JSON | 可后台编辑、版本化、灰度 |
| Guardrail | Python 常量 + 函数 | 规则注册表 |
| 模型输出 | Pydantic schema | EvidenceNode / Source 关联 |
| 过程展示 | JSON result | 前端 reasoning trace / card |

第一阶段不要上数据库。先用文件和代码常量，便于 review、测试和快速改。

## 4. Model Graph：把模型之间的关系做成可调用的数据结构

Model Graph 不是文档里的示意图，而是 Agent 和 Skill 可以读取的数据结构。

它回答的问题是：

- 有哪些 BA 模型。
- 每个模型在商业分析中承担什么角色。
- 哪些模型是入口节点。
- 哪些模型是目标节点。
- 模型之间有什么业务语义关系。
- 哪些分支是必须的，哪些是可选增强。
- 缺少证据时可以跳过哪条路径。

这比在线性 skill 里写 `recommended_process` 更好，因为 AI 可以在图上自主导航，而不是机械按步骤填空。

### 4.1 图的节点

节点是模型，不是工具。

示例：

```yaml
nodes:
  TradeAreaModel:
    role: boundary
    purpose: 统一空间范围和商圈口径
    required_for:
      - MarketPotentialModel
      - RetailGapModel
      - HuffGravityModel
      - SiteSuitabilityModel
    outputs:
      - trade_area_context

  MarketPotentialModel:
    role: demand
    purpose: 判断需求基础和市场潜力 proxy
    outputs:
      - market_potential_result

  RetailGapModel:
    role: supply_gap
    purpose: 判断供需缺口、零售空白和空间错配
    outputs:
      - retail_gap_result
      - candidate_zones

  HuffGravityModel:
    role: competition
    purpose: 判断竞争分流和相对吸引力 proxy
    optional: true
    outputs:
      - huff_proxy_result

  CustomerProfileFitModel:
    role: customer_fit
    purpose: 判断人群画像与目标业态匹配
    optional: true
    outputs:
      - customer_profile_fit_result

  SiteSuitabilityModel:
    role: decision
    purpose: 综合需求、供给、竞争、客群和可达性进行候选点排序
    outputs:
      - site_suitability_result
```

### 4.2 图的边

边不是“代码调用顺序”，而是业务语义关系。

```yaml
edges:
  - from: TradeAreaModel
    to: MarketPotentialModel
    relation: defines_scope_for
    required: true

  - from: TradeAreaModel
    to: RetailGapModel
    relation: defines_scope_for
    required: true

  - from: MarketPotentialModel
    to: RetailGapModel
    relation: provides_demand_baseline
    required: false

  - from: RetailGapModel
    to: SiteSuitabilityModel
    relation: provides_candidate_zones
    required: true

  - from: MarketPotentialModel
    to: SiteSuitabilityModel
    relation: contributes_demand_score
    required: true

  - from: HuffGravityModel
    to: SiteSuitabilityModel
    relation: adjusts_for_competition
    required: false
    use_when:
      - 用户询问竞争
      - 当前范围存在同类或替代竞品
      - 有候选点和距离 proxy

  - from: CustomerProfileFitModel
    to: SiteSuitabilityModel
    relation: adjusts_for_target_user_fit
    required: false
    use_when:
      - 用户询问客群
      - 用户提供品牌画像
      - Skill 场景涉及家庭、学生、夜间社交等目标人群
```

边的 `relation` 很重要。它告诉 AI：

- 上游模型给下游模型提供什么。
- 这是范围、需求、供给、竞争、客群还是决策关系。
- 这条路径是必须还是可选。
- 什么条件下走这条分支。

### 4.3 一张选址模型图

`graphs/commercial_site_selection.yaml` 可以是：

```yaml
graph_id: ba.commercial_site_selection_graph.v1
title: 商业选址模型图

entry_nodes:
  - TradeAreaModel

target_nodes:
  - SiteSuitabilityModel

nodes:
  TradeAreaModel:
    role: boundary
    required: true
  MarketPotentialModel:
    role: demand
    required: true
  RetailGapModel:
    role: supply_gap
    required: true
  HuffGravityModel:
    role: competition
    optional: true
  CustomerProfileFitModel:
    role: customer_fit
    optional: true
  SiteSuitabilityModel:
    role: decision
    required: true

edges:
  - from: TradeAreaModel
    to: MarketPotentialModel
    relation: defines_scope_for
    required: true
  - from: TradeAreaModel
    to: RetailGapModel
    relation: defines_scope_for
    required: true
  - from: MarketPotentialModel
    to: RetailGapModel
    relation: provides_demand_baseline
  - from: MarketPotentialModel
    to: SiteSuitabilityModel
    relation: contributes_demand_score
    required: true
  - from: RetailGapModel
    to: SiteSuitabilityModel
    relation: provides_candidate_zones
    required: true
  - from: HuffGravityModel
    to: SiteSuitabilityModel
    relation: adjusts_for_competition
    optional: true
  - from: CustomerProfileFitModel
    to: SiteSuitabilityModel
    relation: adjusts_for_target_user_fit
    optional: true
```

### 4.4 Skill 如何使用 Model Graph

Skill 不再写死完整流程，而是引用模型图：

```yaml
skill_id: ba.single_category_site_selection
title: 单业态开店选址
uses_model_graph: ba.commercial_site_selection_graph.v1

entry_nodes:
  - TradeAreaModel

target_nodes:
  - SiteSuitabilityModel

required_path:
  - TradeAreaModel
  - MarketPotentialModel
  - RetailGapModel
  - SiteSuitabilityModel

optional_branches:
  competition:
    model: HuffGravityModel
    use_when:
      - 用户询问竞争
      - 当前范围存在足够同类或替代竞品
  customer_fit:
    model: CustomerProfileFitModel
    use_when:
      - 用户询问客群
      - 用户提供品牌画像
      - Skill 场景需要目标人群判断

model_tool_map:
  TradeAreaModel:
    - read_current_results
    - run_isochrone
  MarketPotentialModel:
    - aggregate_scope_dataset
    - search_evidence_nodes
  RetailGapModel:
    - analyze_target_supply_gap
    - query_scope_dataset
  HuffGravityModel:
    - query_scope_dataset
    - read_scope_record
  SiteSuitabilityModel:
    - run_site_selection_pack
    - score_site_candidates
```

这样 Skill 的职责变成：

```text
说明业务目标
-> 引用哪张模型图
-> 指定入口节点和目标节点
-> 标出必走路径和可选分支
-> 写清每个模型对应的工具
-> 写清何时跳过、何时追问、何时输出 partial
```

### 4.5 Agent 在图上导航

Agent 的角色不是“自己发明分析方法”，而是“在模型图上自主导航”。

示例：

用户问“这里缺什么业态？”

```text
TradeAreaModel
-> MarketPotentialModel
-> RetailGapModel
```

不需要跑 `HuffGravityModel`，也不需要跑 `SiteSuitabilityModel`。

用户问“开咖啡店选哪里？”

```text
TradeAreaModel
-> MarketPotentialModel
-> RetailGapModel
-> SiteSuitabilityModel
```

如果有竞品，再补：

```text
HuffGravityModel
```

用户问“同类店很多还值得进吗？”

```text
TradeAreaModel
-> RetailGapModel
-> HuffGravityModel
```

必要时再进入：

```text
SiteSuitabilityModel
```

用户问“这个位置适合家庭客群吗？”

```text
TradeAreaModel
-> MarketPotentialModel
-> CustomerProfileFitModel
```

这就是图结构比普通 prompt skill 更有价值的地方：AI 可以依据用户问题和证据状态选择路径。

### 4.6 Model Graph 需要提供的 API

工程上，`model_graph.py` 至少需要提供：

```python
graph.get_node("RetailGapModel")
graph.out_edges("RetailGapModel")
graph.in_edges("SiteSuitabilityModel")
graph.find_paths("TradeAreaModel", "SiteSuitabilityModel")
graph.required_path_for("ba.single_category_site_selection")
graph.optional_branches_for(question, evidence_state)
graph.missing_inputs_for("HuffGravityModel", evidence_state)
```

这使得 Skill 不是普通文本，而是可以被系统执行和检查的结构。

## 5. AI 怎么使用这套体系

运行时不是把整篇文档塞给模型，而是给 AI 一个紧凑、结构化、可执行的 skill context。

主流程：

```text
用户问题
-> Agent gate 判断意图和缺失输入
-> skill_registry 召回 1-3 个候选 Skill
-> Skill 引用 Model Graph
-> Agent 在图上选择入口节点、目标节点、必走路径和可选分支
-> Agent 根据 model_tool_map 调工具补 EvidenceNode / 当前范围数据
-> Agent 调用 Business Analyst Models 得到结构化 ModelResult
-> Guardrails 检查越界风险和必提边界
-> Agent 自主组织最终回答、解释过程和下一步建议
```

关键点：

- Skill 给的是“如何使用模型图和工具”，不是死流程。
- Model Graph 给的是“专业分析结构”，不是展示图。
- Model 给的是“稳定分析结果”，不是自然语言发挥。
- Agent 仍然决定是否跳过模型、是否追问、是否补工具、是否只给部分结论。
- Guardrail 只在最后和关键步骤阻止错误外推。

示例传给 AI 的 skill context：

```json
{
  "selected_skill": {
    "skill_id": "ba.single_category_site_selection",
    "purpose": "判断某一目标业态在当前范围内是否适合进入，并在证据允许时推荐候选区域。",
    "agent_autonomy": {
      "may_skip_models": true,
      "may_reorder_models": true,
      "may_request_clarification": true,
      "may_stop_with_partial_conclusion": true
    },
    "available_models": [
      "TradeAreaModel",
      "MarketPotentialModel",
      "RetailGapModel",
      "HuffGravityModel",
      "CustomerProfileFitModel",
      "SiteSuitabilityModel"
    ],
    "tool_map": {
      "TradeAreaModel": ["read_current_results", "run_isochrone"],
      "MarketPotentialModel": ["read_current_results", "aggregate_scope_dataset"],
      "RetailGapModel": ["analyze_target_supply_gap", "aggregate_scope_dataset"],
      "HuffGravityModel": ["query_scope_dataset", "read_scope_record"],
      "SiteSuitabilityModel": ["run_site_selection_pack", "score_site_candidates"]
    },
    "recommended_process": [
      "确认目标业态、分析范围、时间和交通口径",
      "建立或读取 trade area",
      "评估需求基础和需求 proxy",
      "评估供给缺口与空间错配",
      "如果有候选点和竞品，再运行 Huff proxy",
      "对候选区域做适宜性排序",
      "输出建议、风险、证据缺口和验证动作"
    ],
    "guardrails": [
      "no_revenue_without_source",
      "huff_proxy_not_market_share",
      "population_not_spending_power",
      "recommendation_requires_validation"
    ]
  }
}
```

这才是给 AI 使用的正确形态：不是一堆散文，不是硬编码流程，而是一个“可解释、可执行、可裁剪”的专业技能说明。

## 6. 证据边界与商业运行数据缺口

ESRI Business Analyst 的很多分析在理想状态下会使用消费、客流、租金、销售、客户点、竞品经营状态等数据。但当前系统不应为了完整性伪造这些数据。

更合理的做法是把它们明确写入模型的 `missing_evidence` 和 `confidence policy`。

### 6.1 当前数据能支撑什么

当前系统已经比较适合支撑这些 BA 模型输入：

| 数据 | 当前形态 | 可支持的模型 |
| --- | --- | --- |
| 当前范围 | `scope_polygon`、等时圈、历史范围 | `TradeAreaModel` |
| POI | 当前范围 POI、H3 聚合、scoped dataset | `RetailGapModel`、`MarketPotentialModel`、`SiteSuitabilityModel` |
| H3 / 网格 | 候选格、热点、供给分布 | `RetailGapModel`、`SiteSuitabilityModel` |
| 人口 | 人口总量、密度、结构、网格分布 | `MarketPotentialModel`、`CustomerProfileFitModel` |
| 夜光 | 夜间活动 proxy、热点、变化趋势 | `MarketPotentialModel`、`SiteSuitabilityModel` |
| 路网 / 可达 | road syntax、等时圈、可达范围 | `TradeAreaModel`、`SiteSuitabilityModel`、`HuffGravityModel` proxy |
| 文档/网页/图片 | 统一 `EvidenceNode` | 所有模型的外部补充证据 |

这些数据足以支持“商业预筛”“空间诊断”“供需错配”“候选区域排序”“风险提示”和“后续验证建议”。

### 6.2 当前缺什么

缺失最多的是商业运行数据：

| 数据 | 当前可得性 | 处理策略 |
| --- | --- | --- |
| 租金 | 可能从公开商铺出租信息获得，但合法性、稳定性和结构化质量有风险。 | 作为可选外部来源，不进入 V1 自动能力。 |
| 客流 | 通常需要运营商、地图平台、设备或第三方数据。 | 标记为缺失证据，不伪造。 |
| 营业额 | 基本没有可靠公开来源。 | 禁止输出确定性结论。 |
| 消费交易 | 需要支付、会员、订单或第三方商业数据。 | 标记为缺失证据。 |
| 竞品经营状态 | 可通过点评、营业时间、排队、评论等 proxy 辅助，但不稳定。 | 可作为外部 EvidenceNode，必须标注来源与不确定性。 |

因此模型输出应默认包含：

```json
{
  "decision_type": "pre_screening",
  "confidence": "weak|moderate",
  "missing_evidence": [
    "真实客流",
    "租金",
    "营业额",
    "同类竞品经营状态",
    "客户点或订单来源"
  ]
}
```

这不是削弱系统能力，而是让系统更可信。商业地产分析本来就应该区分“空间预筛”和“投资决策”。

### 6.3 网络来源不是 AI 自主爬取

对于网页资料，当前合理链路是：

```text
SearXNG 找 URL
-> Crawl4AI 打开网页并提取 Markdown
-> 清洗 / chunking
-> EvidenceNode
-> EvidenceRetrievalService
-> BA Model 输入
```

这应该被定义为“网络来源的前序 RAG 管线”，而不是“AI 自动爬取商业运行数据”。

原因：

- AI 不应直接任意访问和抓取网页。
- 网页内容必须先变成来源和 EvidenceNode。
- 来源需要保留 URL、抓取时间、清洗质量、chunk 和 citation。
- 网页证据进入模型时必须带不确定性，不能直接变成经营事实。

因此，未来如果接入租金、商铺出租、点评或竞品网页，也应按这个链路进入：

```text
web source -> EvidenceNode -> Model optional evidence -> Guardrail audit
```

不能绕过来源层直接让 Agent 看网页后写结论。

## 7. Business Analyst Models：把能用的思想做成模型

### 5.1 TradeAreaModel：商圈 / 服务范围模型

对应 ESRI 思想：

- Trade Area
- Drive-time / walk-time area
- Customer-derived area
- Competitive / standard geography area

本项目转译：

`TradeAreaModel` 负责把当前分析对象转换成后续模型共同使用的 `trade_area_context`。

它不只返回一个 polygon，而要返回“范围的业务含义”：

```json
{
  "trade_area_type": "user_scope|isochrone|h3_cluster|admin_area|customer_derived",
  "geometry_ref": "scope_polygon",
  "mobility_mode": "walking|driving|unknown",
  "time_threshold_min": 15,
  "scope_basis": "用户手绘范围 / 15分钟步行等时圈",
  "evidence_level": "explicit|proxy|missing",
  "limits": []
}
```

需要调用的工具：

| 输入需求 | 工具 |
| --- | --- |
| 当前范围 polygon | `read_current_results` |
| 等时圈参数 | `run_isochrone` / snapshot isochrone |
| H3 候选范围 | `query_scope_dataset(current:dataset:h3)` |
| 行政或外部边界 | 后续 Source / EvidenceRetrievalService |

模型自主性：

- 如果用户已经给了明确范围，可以直接使用。
- 如果用户问“开在哪里”，但没有范围，应触发澄清。
- 如果已有等时圈，应优先解释为可达范围，而不是客源范围。
- 如果未来有客户点，可以升级为 customer-derived trade area。

Guardrails：

- 等时圈表示可达性，不等同真实客源。
- 手绘范围表示分析边界，不等同真实市场边界。
- 没有范围时不能做缺口、潜力或选址排序。

### 5.2 MarketPotentialModel：市场潜力模型

对应 ESRI 思想：

- Market Potential
- Demographic demand
- Spending / demand proxy
- Behavioral potential

本项目转译：

`MarketPotentialModel` 不直接预测销售额，而是评估目标业态在当前 trade area 中的“需求基础”和“潜力 proxy”。

输出：

```json
{
  "potential_level": "low|medium|high|unknown",
  "potential_score": 0.0,
  "demand_signals": [
    {
      "signal": "population_density",
      "direction": "supportive",
      "evidence_level": "moderate",
      "explanation": "人口密度支持基础服务需求，但不能证明消费力。"
    }
  ],
  "contradicting_signals": [],
  "missing_evidence": ["真实客流", "消费支出", "目标客群订单数据"],
  "limits": []
}
```

需要调用的工具：

| 输入需求 | 工具 |
| --- | --- |
| 人口总量、密度、年龄、性别 | `read_current_results` / `aggregate_scope_dataset(current:dataset:population)` |
| 夜间活跃 proxy | `read_current_results` / `aggregate_scope_dataset(current:dataset:nightlight)` |
| 功能场景 | `aggregate_scope_dataset(current:dataset:poi)` |
| 可达性基础 | `read_current_results` / road tools |
| 外部市场资料 | `EvidenceRetrievalService` |

模型自主性：

- 不同业态选择不同 demand signals。
- 便利店更看社区人口、通勤路径、竞品覆盖。
- 咖啡更看工作/学习/休闲场景、日间停留、同类集聚与替代业态。
- 夜间社交更看夜光、餐饮娱乐、晚间可达和安全验证。

Guardrails：

- 人口不是消费力。
- 夜光不是消费额。
- POI 场景不是真实交易。
- 没有目标业态时只能做通用市场基础判断。

### 5.3 RetailGapModel：供需缺口 / Leakage / Void 模型

对应 ESRI 思想：

- Retail Gap
- Leakage
- Void Analysis
- Supply-demand mismatch

本项目转译：

`RetailGapModel` 判断目标业态在当前 trade area 中是：

- 总量短缺
- 结构缺口
- 空间错配
- 局部过密
- 证据不足

输出：

```json
{
  "gap_mode": "overall_shortage|category_void|spatial_mismatch|oversupply_risk|balanced|insufficient_evidence",
  "gap_score": 0.0,
  "reference_basis": "within_scope|neighbor_average|selected_reference_area|none",
  "candidate_zones": [],
  "oversupply_zones": [],
  "evidence_level": "weak|moderate|strong",
  "missing_evidence": [],
  "limits": []
}
```

需要调用的工具：

| 输入需求 | 工具 |
| --- | --- |
| 目标业态 POI | `query_scope_dataset(current:dataset:poi)` |
| POI 聚合 | `aggregate_scope_dataset(current:dataset:poi)` |
| H3 供给分布 | `aggregate_scope_dataset(current:dataset:h3)` |
| 现有缺口分析 | `analyze_target_supply_gap` |
| 候选格初筛 | `score_site_candidates` |
| 参考区比较 | 后续 reference source / scoped dataset |

与现有能力关系：

- 现有 `analyze_target_supply_gap_from_scope` 可作为 V1 内核。
- 后续应把它收敛成 `RetailGapModel.run()` 的一部分。
- `current_target_supply_gap` 可以作为 `RetailGapModelResult` 的 artifact。

模型自主性：

- 没有参考区时，不运行严格 leakage，只运行 gap proxy。
- 有目标业态但 POI 样本少时，可输出 partial。
- 如果供给少但需求 proxy 也弱，应标为 `insufficient_evidence` 或 `weak_shortage`，不能直接推荐进入。

Guardrails：

- “缺口”必须说明参考对象。
- POI 少不等于值得进入。
- POI 多不等于不值得进入。
- 没有参考区不能说严格 leakage。

### 5.4 HuffGravityModel：Huff / 竞争分流模型

对应 ESRI 思想：

- Huff Model
- Gravity model
- Distance decay
- Facility attractiveness
- Competitive capture

本项目转译：

`HuffGravityModel` 负责计算候选点与竞争点的相对吸引力 proxy。V1 不输出真实访问概率，只输出 `capture_proxy`。

输入：

```json
{
  "demand_points": [],
  "candidate_sites": [],
  "competitor_sites": [],
  "distance_matrix": [],
  "attractiveness_features": [],
  "decay_parameter": 1.5
}
```

输出：

```json
{
  "result_type": "proxy",
  "capture_proxy": [],
  "relative_attraction": [],
  "sensitive_variables": ["distance", "attractiveness_score"],
  "assumptions": [
    "使用 H3 cell 作为需求点 proxy",
    "使用 POI 集聚和可达性作为吸引力 proxy"
  ],
  "warnings": [
    "缺少真实门店面积、销售额、品牌吸引力和客户点，本结果不能解释为真实市场份额。"
  ]
}
```

需要调用的工具：

| 输入需求 | 工具 |
| --- | --- |
| 候选点 / 候选 H3 | `run_site_selection_pack` / `score_site_candidates` |
| 同类竞品 | `query_scope_dataset(current:dataset:poi)` |
| 替代业态 | `query_scope_dataset(current:dataset:poi)` |
| 需求点 proxy | `query_scope_dataset(current:dataset:h3/population/nightlight)` |
| 距离或可达性 | road / isochrone / geometry helper |
| 吸引力变量 | POI mix、road、nightlight、population summaries |

模型自主性：

- 如果没有竞争点，模型应返回 `skipped:no_competitors`。
- 如果没有候选点，模型应要求先运行 suitability 或 gap。
- 如果距离矩阵不可得，可降级为直线距离并标注限制。
- 如果吸引力变量不足，只输出 partial proxy。

Guardrails：

- Huff proxy 不是真实市场份额。
- 没有真实客户点不能说真实捕获率。
- 没有销售、面积、品牌参数不能说真实吸引力。

### 5.5 CustomerProfileFitModel：客群画像 / 目标客群匹配模型

对应 ESRI 思想：

- Customer Profile
- Segmentation profile
- Customer-derived demographics
- Target segment fit

本项目转译：

`CustomerProfileFitModel` 不凭空生成“消费者画像”，而是判断当前证据能支持哪种层级的人群判断。

证据等级：

| 等级 | 数据 | 可以说什么 |
| --- | --- | --- |
| strong | 真实客户点、订单地址、会员位置 | 真实客户来源和客户画像。 |
| moderate | 范围人口、年龄、性别、外部调研 | 服务人群基础和画像 proxy。 |
| weak | POI 场景、夜光、路网 | 使用场景假设。 |

输出：

```json
{
  "profile_type": "real_customer_profile|area_population_proxy|scenario_proxy|insufficient",
  "fit_level": "low|medium|high|unknown",
  "fit_reasons": [],
  "unsupported_claims": [],
  "missing_evidence": ["客户点", "订单来源", "消费分层"],
  "limits": []
}
```

需要调用的工具：

| 输入需求 | 工具 |
| --- | --- |
| 人口结构 | `read_current_results` / `aggregate_scope_dataset(current:dataset:population)` |
| POI 场景 | `aggregate_scope_dataset(current:dataset:poi)` |
| 夜间活动 | `aggregate_scope_dataset(current:dataset:nightlight)` |
| 外部客群资料 | `EvidenceRetrievalService` |
| 真实客户点 | 未来 customer source |

模型自主性：

- 没有真实客户点时，输出 `area_population_proxy`。
- 如果用户要求品牌客群，可把品牌画像作为 target profile，但必须标明来源。
- 可根据业态场景选择画像维度，不固定套模板。

Guardrails：

- 性别和年龄不能被刻板化解释。
- 没有客户点不能说“真实客户来自哪里”。
- 画像要服务于选址判断，不写营销文案。

### 5.6 SiteSuitabilityModel：适宜性评分 / 候选点排序模型

对应 ESRI 思想：

- Site Suitability
- Weighted criteria
- Candidate ranking
- Suitability score

本项目转译：

`SiteSuitabilityModel` 负责把多个模型结果和证据整合成候选点排序。

输入：

```json
{
  "trade_area": {},
  "market_potential": {},
  "retail_gap": {},
  "competition": {},
  "customer_profile_fit": {},
  "candidate_sites": [],
  "weights": {
    "demand": 0.25,
    "gap": 0.25,
    "accessibility": 0.2,
    "competition": 0.15,
    "scenario_fit": 0.1,
    "evidence_quality": 0.05
  }
}
```

输出：

```json
{
  "ranking": [],
  "candidate_sites": [
    {
      "candidate_id": "h3_xxx",
      "total_score": 76.5,
      "score_parts": {
        "demand": 18,
        "gap": 21,
        "accessibility": 15,
        "competition": 10,
        "scenario_fit": 8,
        "evidence_quality": 4.5
      },
      "why_suitable": [],
      "risks": [],
      "missing_evidence": [],
      "next_validation_steps": []
    }
  ],
  "overall_verdict": "suitable|cautious|not_recommended",
  "confidence": "weak|moderate|strong"
}
```

需要调用的工具：

| 输入需求 | 工具 |
| --- | --- |
| 候选点 | `analyze_target_supply_gap` / `score_site_candidates` |
| 当前选址包 | `run_site_selection_pack` |
| 路网 / 可达性 | `read_current_results` / road tools |
| 竞争点 | `query_scope_dataset(current:dataset:poi)` |
| 分项模型结果 | Business Analyst models |

与现有能力关系：

- 现有 `score_site_candidates` 是 V1 的基础评分器。
- 后续应改造成 `SiteSuitabilityModel` 的内部评分实现。
- `site_selection_service.py` 应返回模型结果摘要，而不是只返回候选点列表。

模型自主性：

- 权重可由 Skill 根据场景选择，例如 `supply_gap`、`traffic_vitality`、`avoid_competition`。
- 如果缺少某些维度，模型可以降低 confidence，而不是失败。
- 如果所有候选点证据弱，应输出 `not_recommended` 或 `cautious`。

Guardrails：

- 分数必须可拆解。
- 推荐必须包含风险和验证动作。
- 证据弱时不能强推荐。
- 不输出租金、坪效、营收、ROI，除非证据源明确提供。

## 8. Skills：把分析流程和工具对应关系写给 AI

Skill 是本体系的核心交互资产。它不是模型代码，也不是硬规则，而是给 AI Agent 的专业技能说明。

一个 Skill 应回答：

- 这个技能解决什么业务问题。
- 适合什么用户意图。
- 可以调用哪些 BA Models。
- 每个 Model 需要哪些工具或证据。
- 推荐流程是什么。
- 哪些步骤可以跳过或重排。
- 输出应包含哪些内容。
- 需要应用哪些 guardrails。

### 6.1 Skill schema

建议 YAML 结构：

```yaml
skill_id: ba.single_category_site_selection
title: 单业态开店选址
version: 1
purpose: >
  判断某一目标业态在当前范围内是否适合进入，并在证据允许时推荐候选区域。

when_to_use:
  question_types:
    - site_selection
    - facility_gap
  user_intents:
    - 开店选址
    - 业态补位
    - 候选区域排序
  examples:
    - 这里适合开咖啡店吗？
    - 便利店应该补在哪里？
    - 哪个候选格更适合夜间社交？

agent_autonomy:
  may_skip_models: true
  may_reorder_models: true
  may_combine_with_other_skills: true
  may_request_clarification: true
  may_stop_with_partial_conclusion: true
  should_explain_skipped_models: true

available_models:
  - TradeAreaModel
  - MarketPotentialModel
  - RetailGapModel
  - HuffGravityModel
  - CustomerProfileFitModel
  - SiteSuitabilityModel

model_tool_map:
  TradeAreaModel:
    required_tools:
      - read_current_results
    optional_tools:
      - run_isochrone
  MarketPotentialModel:
    required_tools:
      - read_current_results
    optional_tools:
      - aggregate_scope_dataset
      - search_evidence_nodes
  RetailGapModel:
    required_tools:
      - analyze_target_supply_gap
    optional_tools:
      - aggregate_scope_dataset
      - query_scope_dataset
  HuffGravityModel:
    required_tools:
      - query_scope_dataset
    optional_tools:
      - read_scope_record
      - run_isochrone
  SiteSuitabilityModel:
    required_tools:
      - run_site_selection_pack
    optional_tools:
      - score_site_candidates

recommended_process:
  - 确认目标业态、当前范围、年份和交通口径。
  - 用 TradeAreaModel 统一后续分析口径。
  - 用 MarketPotentialModel 判断需求基础。
  - 用 RetailGapModel 判断供需缺口和空间错配。
  - 如存在候选点和竞品，用 HuffGravityModel 估计竞争分流 proxy。
  - 用 CustomerProfileFitModel 检查目标人群和场景适配。
  - 用 SiteSuitabilityModel 输出候选点排序、风险和验证动作。

skip_conditions:
  HuffGravityModel:
    - 没有候选点
    - 没有同类或替代竞品
  CustomerProfileFitModel:
    - 用户问题不涉及人群或目标客群
  SiteSuitabilityModel:
    - 用户只问区域总体特征，不要求候选位置

required_outputs:
  - conclusion
  - model_results
  - evidence_used
  - risks
  - missing_evidence
  - next_validation_steps

guardrails:
  - no_revenue_without_source
  - population_not_spending_power
  - nightlight_not_sales
  - poi_not_business_performance
  - huff_proxy_not_market_share
  - recommendation_requires_validation
```

### 6.2 单业态开店选址 Skill

`skill_id`: `ba.single_category_site_selection`

用于：

- “这里适合开咖啡店吗？”
- “开便利店选哪个位置？”
- “哪个网格适合做餐饮补位？”

核心模型：

```text
TradeAreaModel
-> MarketPotentialModel
-> RetailGapModel
-> HuffGravityModel optional
-> CustomerProfileFitModel optional
-> SiteSuitabilityModel
```

AI 自主点：

- 如果用户没说业态，先追问。
- 如果没有候选点，先跑缺口模型或选址 pack。
- 如果没有竞品，跳过 Huff。
- 如果只问“适不适合”，可以不做完整候选排序。
- 如果证据弱，可以输出方向性判断，不强推点位。

### 6.3 区域商业诊断 Skill

`skill_id`: `ba.area_commercial_diagnosis`

用于：

- “这个区域商业基础怎么样？”
- “这里缺什么商业？”
- “这个片区更像社区型还是目的型消费？”

核心模型：

```text
TradeAreaModel
-> MarketPotentialModel
-> RetailGapModel
-> CustomerProfileFitModel
```

可调用工具：

- `read_current_results`
- `aggregate_scope_dataset(current:dataset:poi)`
- `aggregate_scope_dataset(current:dataset:population)`
- `aggregate_scope_dataset(current:dataset:nightlight)`
- `analyze_target_supply_gap`，仅当用户指定业态或系统能明确识别业态
- `EvidenceRetrievalService`，用于外部报告或来源资料

AI 自主点：

- 如果没有目标业态，不跑单业态 gap，只输出结构性缺口方向。
- 如果用户问总体商业基础，不需要 SiteSuitabilityModel。
- 如果外部来源很强，可引用来源，但仍需和当前范围证据分开。

### 6.4 竞争影响 Skill

`skill_id`: `ba.competition_impact`

用于：

- “同类店这么多还值得进吗？”
- “A 点会不会被周边竞品分流？”
- “哪个候选点竞争压力更小？”

核心模型：

```text
TradeAreaModel
-> RetailGapModel
-> HuffGravityModel
-> SiteSuitabilityModel optional
```

可调用工具：

- `query_scope_dataset(current:dataset:poi)` 查同类和替代业态
- `aggregate_scope_dataset(current:dataset:poi)` 看竞争密度
- `read_scope_record` 读取关键竞品
- `run_isochrone` 或距离工具
- `score_site_candidates` 如果需要排序

AI 自主点：

- 如果没有候选点，只做竞争格局诊断。
- 如果没有距离证据，使用 proxy 并提示限制。
- 如果用户比较 A/B 点，优先构造两点的相对竞争解释。

### 6.5 客群画像复盘 Skill

`skill_id`: `ba.customer_profile_review`

用于：

- “这里服务的人群是谁？”
- “这个位置适合年轻人/家庭/学生吗？”
- “这个品牌的目标客群和区域匹配吗？”

核心模型：

```text
TradeAreaModel
-> CustomerProfileFitModel
-> MarketPotentialModel optional
```

可调用工具：

- `read_current_results`
- `aggregate_scope_dataset(current:dataset:population)`
- `aggregate_scope_dataset(current:dataset:poi)`
- `aggregate_scope_dataset(current:dataset:nightlight)`
- `EvidenceRetrievalService` 读取品牌或外部客群资料

AI 自主点：

- 如果没有真实客户点，必须改称“范围人口画像 proxy”。
- 如果用户给了品牌画像，可以用作 target profile。
- 如果只有地图 proxy，不输出强画像。

### 6.6 存量门店复盘 Skill

`skill_id`: `ba.existing_site_review`

用于未来：

- “这个已有门店表现为什么不好？”
- “现有店覆盖的人群和商圈是否匹配？”
- “这个店是否应该扩张/迁址？”

核心模型：

```text
TradeAreaModel
-> CustomerProfileFitModel
-> MarketPotentialModel
-> RetailGapModel
-> HuffGravityModel
```

V1 暂不作为主 demo，因为缺少真实经营、客户点和销售数据。

## 9. Guardrails：只做边界治理，不抢分析主导权

Guardrail 应该短、硬、可审计。

### 7.1 关键 guardrails

| guardrail_id | 内容 |
| --- | --- |
| `population_not_spending_power` | 人口只能支持需求基底，不能直接证明消费力。 |
| `nightlight_not_sales` | 夜光只能作为夜间活动 proxy，不能证明消费额、营业收入或真实人流。 |
| `poi_not_business_performance` | POI 数量只能说明供给存在和结构，不能证明经营质量。 |
| `accessibility_not_stay` | 可达性好可能是穿行，不等于停留或转化。 |
| `huff_proxy_not_market_share` | Huff proxy 不能被表述为真实市场份额或真实到访概率。 |
| `customer_profile_requires_customer_data` | 没有客户点或订单地址时，不能声称真实客户画像。 |
| `no_revenue_without_source` | 没有销售、租金、坪效、客流来源时，禁止输出财务结论。 |
| `recommendation_requires_validation` | 选址推荐必须包含线下验证动作。 |

### 7.2 Guardrail 的运行位置

```text
ModelResult 生成后
-> 检查模型输出是否带 proxy / warning
-> Finalizer 前检查 answer guidance
-> 最终回答后可做一次字符串级风险扫描
```

Guardrail 的输出：

```json
{
  "finding_id": "huff_proxy_not_market_share",
  "severity": "block",
  "message": "当前 Huff 结果缺少真实客户点和吸引力参数，只能表述为相对吸引力 proxy。",
  "required_revision": "把“市场份额”改成“相对吸引力 proxy”。"
}
```

## 10. 与现有 Agent 的接入方式

当前仓库已有基础：

- `modules/agent/gate.py`：识别问题类型。
- `modules/agent/runtime.py`：主 Agent turn。
- `modules/agent/providers/langgraph_react.py`：工具循环。
- `modules/agent/tool_definitions/`：工具注册。
- `modules/agent/tool_adapters/scenario_tools.py`：`run_site_selection_pack`。
- `modules/agent/site_selection_service.py`：选址 tab 数据。
- `modules/agent/reasoning_rubric.py`：证据推理五步法。
- `modules/scope_datasets/`：当前范围明细查询。
- `modules/evidence_retrieval/`：EvidenceNode 统一证据。

当前接入点：

### 10.1 Runtime 不自动注入 BA context

Runtime 只维护用户范围、已选来源、视觉快照和工具循环产物。商业类问题不会在进入 tool loop 前自动生成旧式 BA 上下文对象，也不会把 BA 当作默认报告 payload 注入 finalizer。

### 10.2 工具循环按需调用 BA skeleton

主 Agent 只暴露一个只读工具：

```text
plan_business_analyst_analysis
```

工具输入：

```json
{
  "question": "可选，默认当前用户问题",
  "mode": "auto|area_diagnosis|opportunity_screening|site_selection|competition|customer_fit",
  "question_type": "可选，来自 gate 或调用方判断"
}
```

工具返回 `business_analyst_skeleton`，用于导航而不是替 Agent 生成报告：

```json
{
  "selected_skill": {},
  "candidate_skills": [],
  "recommended_path": [],
  "optional_branches": {},
  "model_tool_map": {},
  "guardrails": [],
  "skip_conditions": {},
  "missing_evidence_defaults": [],
  "answer_guidance": []
}
```

Agent 根据 `recommended_path` 和 `model_tool_map` 决定是否调用当前已注册工具，例如 `read_current_results`、`query_scope_dataset`、`aggregate_scope_dataset`、`search_analysis_context` 和 `read_scope_record`。仓库当前不注册逐模型 BA 工具，避免把模型图误实现成一组僵硬工具步骤。

### 10.3 与选址能力的关系

BA skeleton 只告诉 Agent 什么时候需要 `SiteSuitabilityModel`、什么时候跳过候选排序、什么时候需要补候选点/竞品/到达性证据。具体证据仍来自当前范围数据集、EvidenceNode 和已有分析结果。

选址 UI 或未来专门 BA 报告入口可以显式消费 BA skeleton；普通主回答不默认走旧的 `run_site_selection_pack` 报告路径，也不把 scorecard 作为必要输出。

### 10.4 Finalizer 使用方式

Finalizer 只接收 `answer_evidence_payload.business_analyst_skeleton` 摘要：

```json
{
  "status": "ready|partial|skipped",
  "selected_skill": {},
  "recommended_path": [],
  "optional_branches": {},
  "model_tool_map": {},
  "skip_conditions": {},
  "guardrails": [],
  "answer_guidance": []
}
```

普通回答应把 BA model path 消化成自然判断、候选方向、证据边界和下一步验证动作。只有用户明确要求 ESRI BA 报告、Model Scorecard、表格或审查清单时，才使用 `modules/business_analyst/report_builder.py` 生成报告式结构。

## 11. AI 自主性如何保留

Skill 不是死流程。必须明确写入 autonomy policy。

```yaml
agent_autonomy:
  may_skip_models: true
  may_reorder_models: true
  may_combine_with_other_skills: true
  may_request_clarification: true
  may_stop_with_partial_conclusion: true
  should_explain_skipped_models: true
```

Agent 可以：

- 只跑 TradeArea + RetailGap，不跑 Huff。
- 在用户只问竞争时直接跑 Competition Skill。
- 发现缺目标业态时先追问。
- 发现证据弱时停止在 partial conclusion。
- 将外部文档 EvidenceNode 与当前范围数据组合。
- 在 deep 模式下跑更多模型，在 quick 模式下只跑必要模型。

但 Agent 不可以：

- 绕过 guardrail 输出财务结论。
- 把 proxy 当真实市场份额。
- 没范围就做选址排序。
- 没客户点就声称真实客户画像。

这就是“自主但不失控”。

## 12. 一次完整运行示例

用户问：

> 这个范围里适合开咖啡店吗？推荐哪个位置？

运行：

```text
1. gate 判断为 site_selection，识别 target_place_type = 咖啡。
2. skill_registry 建议 ba.single_category_site_selection。
3. Agent 读取 Skill，决定先跑 TradeAreaModel。
4. TradeAreaModel 使用当前 scope_polygon，标注为 user_scope / explicit。
5. MarketPotentialModel 读取人口、POI、夜光，输出 medium potential proxy。
6. RetailGapModel 调 analyze_target_supply_gap，发现 spatial_mismatch。
7. Agent 查询同类咖啡/饮品 POI，发现有竞品，但缺少真实吸引力参数。
8. HuffGravityModel 输出 relative attraction proxy，而不是 market share。
9. SiteSuitabilityModel 调 run_site_selection_pack，输出候选 H3 排序。
10. Guardrails 要求：不能说营业额，不能说真实客流，必须给验证动作。
11. Finalizer 生成自然回答。
```

回答应该类似：

```text
可以做预筛，但当前证据只能支持方向性选址判断，不能证明真实客流或营业收入。

更值得优先看的候选区域是 A。它的优势来自三个模型信号：当前商圈范围内咖啡类供给存在空间错配；周边人口与功能场景对日常停留型消费有一定支撑；候选格的可达性和周边混合度相对更好。

竞争方面，系统只能做 Huff proxy：它基于距离、同类 POI 和周边吸引力变量估计相对吸引力，不能解释为真实市场份额。当前缺少门店面积、品牌强度、销售额和客户点，因此竞争结论应作为预筛参考。

下一步需要现场验证门头可见性、工作日早晚高峰、同类店营业状态、租金面积和外卖/点评表现。
```

后台保存：

```json
{
  "skill_id": "ba.single_category_site_selection",
  "models_run": [
    "TradeAreaModel",
    "MarketPotentialModel",
    "RetailGapModel",
    "HuffGravityModel",
    "SiteSuitabilityModel"
  ],
  "models_skipped": [
    {
      "model": "CustomerProfileFitModel",
      "reason": "用户未询问客群，且缺少真实客户点。"
    }
  ],
  "guardrail_findings": [
    "huff_proxy_not_market_share",
    "no_revenue_without_source"
  ],
  "overall_confidence": "moderate"
}
```

## 13. 实施计划

### Phase 1：文档与 schema

交付：

- 本文档。
- `modules/business_analyst/schemas.py`。
- `SkillSpec`、`ModelSpec`、`ModelResult`、`SkillRunResult` schema。

验收：

- 能加载 skill YAML。
- 能列出每个 skill 对应模型和工具。

### Phase 2：Skill registry

交付：

- `skill_registry.py`。
- `skills/single_category_site_selection.yaml`。
- `skills/area_commercial_diagnosis.yaml`。
- `skills/competition_impact.yaml`。

验收：

- 输入 “开咖啡店选哪里” 返回 `ba.single_category_site_selection`。
- 输入 “这里缺什么商业” 返回 `ba.area_commercial_diagnosis`。
- 输入 “同类店多还值得进吗” 返回 `ba.competition_impact`。

### Phase 3：Model registry 与 V1 wrappers

交付：

- `TradeAreaModel` wrapper。
- `RetailGapModel` wrapper，复用 `analyze_target_supply_gap`。
- `SiteSuitabilityModel` wrapper，复用 `run_site_selection_pack` / `score_site_candidates`。
- `MarketPotentialModel` 简化版，读取当前人口、夜光、POI summaries。

验收：

- 每个 model 都能独立单测。
- model 输出有 `status`、`evidence_used`、`missing_evidence`、`warnings`。

### Phase 4：Agent tool loop 接入

交付：

- BA model tools 注册到 Agent internal tools。
- Runtime 注入候选 skill context。
- Tool loop 能根据 skill 调用模型工具。

验收：

- site selection 问题会看到 BA skill context。
- deep 模式能跑多个 BA model。
- quick 模式可以只跑必要 model。

### Phase 5：Guardrail audit

交付：

- `guardrails.py`。
- Finalizer 前审计。
- 对 Huff proxy、夜光、人口、财务外推做 block / warning。

验收：

- 没有真实经营数据时回答不出现营收/客流确定性结论。
- Huff proxy 不被写成市场份额。
- 推荐点位必须带验证动作。

### Phase 6：前端过程展示

交付：

- 在 Agent 思考过程展示 “使用 Skill / 运行 Models / 跳过 Models / Guardrails”。
- 在选址 tab 展示模型分项结果。

验收：

- 评审可以看出系统按 BA 模型思想运行，而不是 AI 直接编结论。

## 14. 与 ESRI BA 的对应关系

| ESRI BA 能力 | 本项目 Model | 本项目 Skill |
| --- | --- | --- |
| Trade Area | `TradeAreaModel` | 所有 BA Skill 的前置模型 |
| Huff Model | `HuffGravityModel` | `competition_impact`、`single_category_site_selection` |
| Market Potential | `MarketPotentialModel` | `area_commercial_diagnosis`、`single_category_site_selection` |
| Leakage / Retail Gap / Void | `RetailGapModel` | `area_commercial_diagnosis`、`single_category_site_selection` |
| Customer Profile | `CustomerProfileFitModel` | `customer_profile_review`、`existing_site_review` |
| Site Suitability | `SiteSuitabilityModel` | `single_category_site_selection` |

这个对应关系应该写进 Skill，而不是只写在文档里。文档解释为什么，Skill 告诉 AI 怎么用。

## 15. 最小可落地版本

最小版本不需要一次实现所有模型。

建议先做：

```text
Skill:
- ba.single_category_site_selection
- ba.area_commercial_diagnosis

Models:
- TradeAreaModel
- MarketPotentialModel lightweight
- RetailGapModel wrapper
- SiteSuitabilityModel wrapper

Guardrails:
- population_not_spending_power
- nightlight_not_sales
- poi_not_business_performance
- no_revenue_without_source
- recommendation_requires_validation
```

Huff 可以第二阶段做，因为它需要竞品、距离、吸引力 proxy，工程复杂度更高。但 Skill 里可以先声明：

```yaml
HuffGravityModel:
  status: planned
  use_when:
    - 有候选点
    - 有同类或替代竞品
    - 有距离或可达性 proxy
  fallback:
    - 如果缺少输入，只做竞争格局描述，不做 Huff proxy
```

这样 demo 可以先展示体系完整性，同时不伪造超出当前能力的模型输出。

### 15.1 当前已落地形态

当前代码已经把 BA 收敛为“可被 Agent 调用的分析骨架”，而不是自动注入最终回答的报告模板：

```text
modules/business_analyst/
├─ schemas.py          定义 ModelGraph / SkillSpec / BusinessAnalystInput / BusinessAnalystSkeleton
├─ model_graph.py      内置 Business Analyst Model Graph
├─ skill_registry.py   负责根据问题和 mode 召回 Skill，并维护 model_tool_map
├─ planner.py          对外暴露 build_business_analyst_skeleton(...)
└─ report_builder.py   显式 BA 报告 helper，不接入普通主回答默认链路
```

接入方式：

- `modules/agent/tool_definitions/business_analyst.py` 注册只读工具 `plan_business_analyst_analysis`。
- ReAct loop 在商业诊断、选址、开放式业态机会、竞品或客群问题中按需调用该工具。
- 工具返回 `business_analyst_skeleton`，包含 `selected_skill`、`recommended_path`、`optional_branches`、`model_tool_map`、`skip_conditions`、`guardrails` 和 `answer_guidance`。
- `synthesizer.py` 只把 `business_analyst_skeleton` 放入最终证据 payload，不自动构建 `business_analyst_report`。
- `prompts.py` 明确 BA skeleton 是分析骨架，不是输出模板；普通回答应自然消化模型路径，只有用户明确要求 BA 报告 / scorecard / 表格时才展开报告式结构。

这个形态的重点是先解决：

```text
AI 知道应该按哪套商业分析模型思考
AI 知道每个模型大致对应哪些工具
AI 知道哪些分支可跳过
AI 知道哪些结论不能越界
```

暂时没有做：

- 当前不注册独立 BA 模型工具；模型图只作为 skeleton 导航结构。
- Huff 真实计算。
- 租金、真实客流、营业额、客户点数据推断。
- 前端 BA 模型轨迹可视化。

这些应放到后续阶段，避免在 demo 阶段为了“完整”而制造伪精确。

### 15.2 为什么不再默认生成 BA Report Object

旧产出的问题不在于没有使用 ESRI BA 术语，而在于系统容易在两个极端之间摇摆：

```text
散装指标 + LLM 咨询式叙事
或
固定 BA 报告模板 + 机械 Scorecard
```

前者缺少专业分析结构，后者会让普通问答变成模板填空。当前实现选择中间形态：

```text
BA Model Graph 约束推理
Tool Map 指导补证据
Guardrails 阻止商业外推
Finalizer 自然回答用户问题
```

ESRI BA 的核心不是固定栏目，而是每个判断都知道自己属于哪类模型问题：

```text
Trade Area
-> Market Potential
-> Retail Gap / Leakage
-> Competition / Huff
-> Customer Profile
-> Site Suitability
```

因此当前主链路只默认提供 `business_analyst_skeleton`：

```json
{
  "status": "ready|partial|skipped",
  "selected_skill": {},
  "recommended_path": [],
  "optional_branches": {},
  "model_tool_map": {},
  "skip_conditions": {},
  "guardrails": [],
  "answer_guidance": []
}
```

如果用户明确要求 ESRI BA 报告、Model Scorecard 或表格，才使用显式报告 helper：

```text
modules/business_analyst/report_builder.py
-> 读取 business_analyst_skeleton / EvidenceNode / 当前范围指标
-> 按 Trade Area / Market Potential / Retail Gap / Huff / Customer Profile / Suitability 组织报告
-> 保留模型状态 ready / partial / skipped
```

这使最终产出从：

```text
AI 咨询摘要 / 机械模板报告
```

转向：

```text
Business Analyst 模型化推理 + 自然回答
```

### 15.3 当前仍然不伪造的部分

当前 BA skeleton / 显式报告 helper 都不会伪造以下内容：

- 没有候选点和竞品参数时，`HuffGravityModel.status=skipped`。
- 没有真实客流时，只能说 demand/activity proxy，不能说真实客流。
- 没有租金、面积、营业额、支付流水时，不能说盈利能力。
- 没有客户点或订单地址时，不能声称真实客户画像。
- 没有候选点排序时，`SiteSuitabilityModel` 只能是 partial 或 skipped。

这很重要。一个像 ESRI BA 的报告，不是每个模型都必须强行有结果，而是每个模型都必须有清楚状态：

```text
ready / partial / skipped
```

并清楚说明为什么。

## 16. 高质量实现的判断标准

这套体系做得好不好，不看模型名多不多，而看以下标准：

1. AI 是否知道自己在调用哪个 BA Skill。
2. AI 是否能解释为什么跑某个模型、跳过某个模型。
3. 模型输出是否结构化、可测试、可复盘。
4. Skill 是否明确模型和工具对应关系。
5. Skill 是否允许 AI 自主裁剪，而不是硬填流程。
6. Guardrail 是否阻止了商业外推。
7. 最终回答是否自然，而不是机械报告模板。
8. 前端/后台是否能展示模型运行轨迹。

如果做到这些，本项目就不是“套了 ESRI 名词的 AI 聊天”，而是有一套真正可生长的商业地理 Agent 方法库。

## 17. 结论

可以，而且应该这样做：

```text
能用的 BA 思想 -> 做成 Models
分析方法和流程 -> 写成 Skills
模型和工具对应关系 -> 写进 Skill
证据边界和禁止外推 -> 做成 Guardrails
AI Agent -> 自主选择 Skill、调用工具、运行 Model、组织回答
```

这比把全部内容做成卡片和规则更好，因为它保留了 AI 的自主性，也让专业分析能力可以被测试、复用和迭代。

最终产品表达可以是：

> 我们不是复刻 ESRI Business Analyst 的界面，而是把其核心商业地理思想转译为 Agent 可调用的模型与技能。模型负责专业分析，Skill 负责组织方法和工具，AI 负责自主编排，Guardrail 负责证据边界。这让系统既有行业方法论，又不会变成僵硬的规则机。

## 参考资料

- [An overview of the Trade Areas toolset | ArcGIS Pro documentation](https://doc.esri.com/en/arcgis-pro/latest/tool-reference/business-analyst/an-overview-of-the-trade-areas-toolset.html)
- [Perform a suitability analysis | ArcGIS Business Analyst help](https://doc.arcgis.com/en/business-analyst/web/suitability-analysis.htm)
- [Suitability analysis reference | ArcGIS Business Analyst help](https://doc.arcgis.com/en/business-analyst/web/understand-suitability-analysis.htm)
- [How Huff Model works | ArcGIS Pro documentation](https://pro.arcgis.com/en/pro-app/3.5/tool-reference/business-analyst/understanding-huff-model.htm)
- [Huff Model | ArcGIS Pro documentation](https://pro.arcgis.com/en/pro-app/3.4/tool-reference/business-analyst/huff-model.htm)
- [Void analysis reference | ArcGIS Business Analyst help](https://doc.arcgis.com/en/business-analyst/web/understand-void-analysis.htm)
- [Generate Customer Segmentation Profile | ArcGIS Pro documentation](https://doc.esri.com/en/arcgis-pro/latest/tool-reference/business-analyst/generate-customer-segmentation-profile.html)
