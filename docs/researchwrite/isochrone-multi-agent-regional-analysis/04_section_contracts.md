# Section contracts

## Section: 项目摘要

- Purpose: 用一段话交代问题、方法、验证设计与边界，使读者立即理解 proposal 研究什么。
- Inputs: argument map central question and thesis；evidence table rows 1-12。
- Allowed claims: 已有链路可运行；研究拟检验数据库增强多智能体方法是否改善报告质量。
- Forbidden claims: 方法已经优于基线；系统可以替代规划师。
- Required evidence: 当前成功运行；至少一个等时圈与一个地理空间智能体文献来源。
- Validation checklist:
  - 是否明确写出等时圈、多源空间数据库、多智能体和区域分析报告？
  - 是否区分已有事实和待验证假设？
  - 是否说明评价维度而非只写“高质量”？

## Section: 研究背景与意义

- Purpose: 说明为什么区域分析报告生成需要统一空间范围和可核验数据，而不是泛论人工智能或智慧城市。
- Inputs: canon literature facts 1-7。
- Allowed claims: 网络可达范围、多源空间数据对齐和空间智能体工作流是相关技术基础。
- Forbidden claims: “LLM 已广泛替代规划师”；“现有研究完全没有相关工作”。
- Required evidence: [1]-[7] 中至少四项并形成逻辑链。
- Validation checklist:
  - 背景是否直接收敛到研究问题？
  - 是否解释流畅文本与空间正确性之间的张力？
  - 是否避免文献罗列？

## Section: 国内外研究现状与缺口

- Purpose: 按等时圈、多源数据、规划大模型、地理空间智能体和报告生成五条线综合既有工作，定位组合性缺口。
- Inputs: canon literature facts；evidence table。
- Allowed claims: 现有方向各自提供部分能力；本研究关注其在项目级长篇区域报告中的组合与验证。
- Forbidden claims: 未经系统检索即声称“首次”或“研究空白”。
- Required evidence: 每条研究线至少一个可核验来源。
- Validation checklist:
  - 每段是否以一个研究机制组织而非按作者罗列？
  - 缺口是否与后续方法一一对应？
  - 是否承认相关工作的已有贡献？

## Section: 科学问题与研究目标

- Purpose: 给出可回答、可证伪的核心问题和三个相互衔接的目标。
- Inputs: argument map central question；unresolved claims。
- Allowed claims: 研究将比较空间一致性、数值正确性、可追溯性、完整性、一致性与专家可用性。
- Forbidden claims: 将系统建设任务冒充科学问题；以“完成平台开发”为唯一目标。
- Required evidence: 明确基线、输入控制和目标指标。
- Validation checklist:
  - 核心问题是否可以由实验回答？
  - 每个目标是否对应一个方法和结果？
  - 是否只有一条主线？

## Section: 研究内容

- Purpose: 将方法拆为范围构建、数据整合、智能体分析和报告评价四项研究内容。
- Inputs: supporting arguments 1-4；current workflow facts。
- Allowed claims: 描述拟实现和拟检验的模块及其关系。
- Forbidden claims: 用模块清单代替研究逻辑；把 N8N 或 MultiCa 写成方法本身。
- Required evidence: 每项内容说明输入、处理、输出与验证接口。
- Validation checklist:
  - 模块之间是否有稳定的数据契约？
  - 是否把计算与语言解释分开？
  - 是否保留失败诊断与范围边界？

## Section: 技术路线与评价方法

- Purpose: 给出可复现的研究设计，包括案例、基线、消融、重复运行、自动评价和专家盲评。
- Inputs: evidence table hypotheses；counterarguments。
- Allowed claims: 拟采用匹配模型、输入和预算的公平比较；拟报告效应量和不确定性。
- Forbidden claims: 在未确定样本量前承诺显著性；以单次展示代替实验。
- Required evidence: 数据版本、等时圈参数、基线条件、指标计算和评审协议。
- Validation checklist:
  - 是否能区分数据库、等时圈、多智能体和质量门槛的贡献？
  - 是否记录失败、成本和重复性？
  - 是否报告专家一致性？

## Section: 创新点

- Purpose: 说明可检验的方法贡献，而不是使用宣传性标签。
- Inputs: research gap；technical route。
- Allowed claims: 统一空间范围、数据库查询先于解释、跨智能体状态与报告级评价协议的组合设计。
- Forbidden claims: “首次”“填补空白”“全面提升”。
- Required evidence: 每个创新点指向一个实验或消融。
- Validation checklist:
  - 创新点是否具体到方法结构？
  - 是否都能在实验中被单独检验？
  - 是否避免把工程规模当创新？

## Section: 可行性、风险与边界

- Purpose: 用已有运行证明可执行性，同时公开数据、模型、评审和泛化风险。
- Inputs: experimental facts；counterarguments；forbidden claims。
- Allowed claims: 当前系统具备端到端原型和持久化基础；后续需要跨案例验证。
- Forbidden claims: 以一次成功运行证明稳定性或泛化性。
- Required evidence: run ID、工作流节点与步骤、现有测试；Go/No-Go 与替代路线。
- Validation checklist:
  - 是否区分工程可行性与科学有效性？
  - 每个主要风险是否有缓解措施？
  - 是否说明研究不能回答什么？

## Section: 研究计划与预期成果

- Purpose: 将研究拆成可交付阶段，预期成果与证据强度相匹配。
- Inputs: objectives；technical route；risks。
- Allowed claims: 形成方法原型、评价数据集、实验结果和论文草稿。
- Forbidden claims: 承诺系统一定优于全部基线或能够直接投入规划生产。
- Required evidence: 阶段验收条件和失败后的收缩路径。
- Validation checklist:
  - 每阶段是否有明确产物？
  - 是否先验证后扩展？
  - 预期成果是否没有越过证据边界？
