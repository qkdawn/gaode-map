# 自适应决策报告契约

`report-contract.md` 是 `formal_comprehensive` 的硬契约唯一事实来源。它拥有状态、章节版本、接受依赖、装配和视觉前置条件；分析深度由 `quality-gates.md` 判断，专业职责由 `specialist-roles.md` 判断，读者表达与总编裁决由 `publication-editorial.md` 判断。装配校验只验证本契约的结构，不裁定研究是否 evidence-closed；该裁定属于主 Skill 与 `quality-gates.md`。

## 可恢复状态契约

正式运行把跨角色共享状态持久化到固定目录，并在 `chapter-index.json` 中声明 `state_manifest: "state/manifest.json"`：

```text
report/state/project-semantic-model.json
report/state/problem-map.json
report/state/decision-logic-map.json
report/state/decision-inventory.json
report/state/evidence-summary.json
report/state/manifest.json
```

每个状态文件包含 `state_id`、对应 `schema`、统一的 `snapshot_version`、ISO-8601 `updated_at` 和对象型 `payload`。`manifest.json` 使用 `spatial-business-state-manifest`，列出固定路径、schema、同一 `snapshot_version` 和文件 SHA-256。恢复和装配通过 manifest、路径、快照、身份和摘要校验后继续。

当前契约使用 `spatial-business-chapter-index`、`spatial-business-state-manifest`、`spatial-business-project-semantic-model`、`spatial-business-problem-map`、`spatial-business-decision-logic-map`、`spatial-business-decision-inventory` 和 `spatial-business-evidence-summary`。`snapshot_version` 表达运行中的状态快照变化。

问题地图的 `payload.status` 使用 `awaiting_confirmation` 或 `confirmed`。已确认的问题地图为专项研究、决策逻辑图、决策清单和章节责任提供同一快照；用户修订后，后续工作从更新后的快照继续。

`decision-logic-map.json` 的 `payload` 使用 `status: ready`，并保存非空 `rules`。每条规则至少含 `id`、`decision_question`、非空 `when`、`judgment`、`action`、`alternatives`、`counterexample`、`evidence_refs`、`limitations`、`validation` 与 `status`；可选 `metric_refs` 的每项含 `result_id`、`tool_id`、`observation`、`comparison_basis`、`decision_effect` 与 `does_not_prove`。它是正式报告各项选择的推理来源，不替代章节正文。

## 审校与接受契约

每个章节版本保存两个独立审校文件：`chapter-reviews/<chapter-id>.vN.adversarial.md` 和 `chapter-reviews/<chapter-id>.vN.depth.md`。两个文件使用严格 Markdown frontmatter：

```text
---
review_type: adversarial | depth
verdict: accepted | revision_required
---
（对决策有影响的审校理由）
```

反方文件记录替代解释、隐藏假设、代价和失败场景；深度文件记录机制、候选比较、承接能力、动作和改判路径。章节的 `review_status` 由两个 verdict 推导。最新版本的两个 verdict 均为 `accepted` 时，章节和下游依赖进入下一阶段。

## 章节所有权与正文保真

正式运行保存 `report/chapter-index.json`、独立版本章节和对应审校意见。每项重要决策在 `decision_inventory` 和章节索引中拥有唯一章节作者；共享证据通过依赖关系复用。

索引使用 `schema: "spatial-business-chapter-index"`。每个版本条目声明 `adversarial_review_path`、`depth_review_path` 和由两个 verdict 推导的 `review_status`；索引顶层声明 `state_manifest: "state/manifest.json"`。

`report/project-report.md` 在章节边界注释之间完整、逐字包含每个接受版本；执行摘要、过渡和综合结论位于标记外，并引用接受章节。

## 装配与视觉前置条件

`validate_chapter_assembly.py` 是装配契约的唯一执行入口。它读取本文件定义的索引、状态、审校和章节边界规则。成功装配为视觉、HTML 和 PDF 建立前置条件。

视觉规则的模板、资产和多格式验收细节由 `report-visual-workflow.md` 拥有。视觉资产置于接受章节边界之外，生成后重新运行装配校验。

## 正式模式范围

用户要求完整项目报告、正式综合报告或同等深度成果时进入 `formal_comprehensive`。每个专业章节由唯一 Subagent 所有，通常为 1,500-3,000 个中文内容字符；长度带为审校提供阅读信号，接受由双审校 verdict 决定。执行摘要、章节过渡、综合结论与证据审计位于专业章节之外。

简单问答、单项诊断和局部分析直接交付，不创建章节版本、章节索引或正式状态目录。
