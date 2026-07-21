# Codex 原生分析编排

正式综合报告使用“问题驱动研究 -> 专业章节纵向循环 -> 全稿冲突审校 -> 低损耗合编”。专业 Subagent 对自己的章节及其中决策负责，主 Agent 负责语义、依赖和出版装配，不充当压缩专业内容的 reducer。

本流程只产生 Markdown 与 JSON 运行产物，不恢复旧版 `ChapterPackage`、数据库 schema、compiler 或后端报告管线。

## 波次 0：事实底稿与问题地图

主 Agent 读取授权原件、分析范围、数据集目录和已有指标目录，按 `adaptive-report-model.md` 建立项目事实表、保留原始名称的对象清单、`project_semantic_model`、待确认的 `problem_map`、材料冲突和口径修正。

此时只定义要作出的选择、候选解释、共享证据和可能的专业责任范围：

- 不作确定定位，不生成 `decision_inventory` 或正式目录；
- 不按人口、POI、夜光、路网等数据类型预设章节；
- 每个重要决策只有一个预定专业所有者，跨章只声明证据共享和必要依赖；
- 标题、顺序、章节数量和拆分方式保持开放。

主 Agent 以自然 Markdown 展示“项目理解 -> 需要共同确认的问题地图 -> 拟开展的证据研究 -> 请确认或修订上述问题地图”。用户明确确认前，不读取专项指标结果、不执行新指标、不启动 Subagent。用户修订后重新展示完整问题地图，直至确认。

## 波次 1-3：问题驱动的专项研究

确认后，主 Agent 以问题为分派单位，为角色投影必要事实、候选假设、所需证据和反证，不按数据来源生成待填工作包。

1. 区域与人群分析师、空间结构分析师并行研究外部条件如何支持或推翻候选解释。
2. 定位与产品策略师接收两者的研究备忘录，比较真实候选方向并形成工作定位、使用者、产品层级和方向取舍。
3. 空间功能策划师、运营与分期策略师接收定位结论并行推演实际对象、使用系统、内容服务、实施阶段和调整机制。

波次 1-3 可以输出简洁研究备忘录。它们是证据收敛的输入，不是最终章节，也不能被主 Agent直接压缩成正式报告。

## 波次 4：决策底稿与章节责任

主 Agent 把已研究问题、候选比较、支持与反证、空间后果和运营承接要求收敛为 `decision_inventory`。仍会改变行动的未解决问题必须补充研究，或形成带明确改判条件的条件性判断。

随后建立章节责任图：

- 每项重要决策只有一个章节所有者；
- 章节边界跟随决策关系，不跟随数据类型或固定角色模板；
- 每章记录所有者、决策 ID、共享证据、依赖和可消费的上游接受版本；
- 标题、小节和最终顺序可随专业写作与审校调整；
- 最终目录由接受章节自然形成，不在波次 0 冻结。

正式运行将责任图持续写入 `report/chapter-index.json`。最小契约如下：

~~~json
{
  "schema_version": "spatial-business-chapter-index.v1",
  "report_mode": "formal_comprehensive",
  "chapters": [
    {
      "chapter_id": "regional-people",
      "role": "区域与人群分析师",
      "decision_ids": ["decision:people"],
      "dependencies": [],
      "versions": [
        {
          "version": 1,
          "path": "chapters/regional-people.v1.md",
          "review_path": "chapter-reviews/regional-people.v1.md",
          "review_status": "accepted"
        }
      ],
      "accepted_version": 1,
      "status": "accepted",
      "character_count": 1860
    }
  ]
}
~~~

`chapters` 的顺序就是接受版本的依赖与最终装配顺序。依赖只能指向列表中更早且已经接受的章节。`character_count` 是接受版本的中文内容字符审计值，不是接受与否的唯一标准。

## 波次 5：专业章节纵向循环

原专业 Subagent 持有自己的证据包、决策和章节，从研究持续写到接受版本：

~~~text
v1 出版级章节
-> 逐章反方审查与深度审校
-> 问题路由回原章节所有者
-> 原证据包上的定向返写 v2
-> 必要时再次审校与定向返写 v3
-> 接受或阻止交付
~~~

每章通常为 1,500-3,000 个中文内容字符，并形成完整论证，而不是五段式摘要。长度仅用于发现过短或异常冗长章节；审校必须实质检查判断、证据比较、项目特有机制、方案代价、反例与失效条件、能力缺口、动作、验证和退出方式。

版本与审校产物为：

~~~text
report/
  chapter-index.json
  chapters/<chapter-id>.v1.md
  chapters/<chapter-id>.v2.md
  chapters/<chapter-id>.v3.md
  chapter-reviews/<chapter-id>.v1.md
  chapter-reviews/<chapter-id>.v2.md
  chapter-reviews/<chapter-id>.v3.md
~~~

初稿加最多两次返写。新版本不得覆盖旧版本；审校员只指出问题和返写要求，不直接代写正文。三版后仍不合格，章节状态不得标为 `accepted`，正式报告停止交付。

依赖消费遵循接受门槛：区域与人群、空间结构章节可并行；定位与产品只能读取两者的接受版本；空间功能、运营与分期只能读取定位与产品的接受版本并可并行。下游不得读取上游草稿或未解决审校意见来替代接受版本。

## 波次 6：全稿审校与定向返写

所有章节接受后，反方审查员和分析深度审校员读取全部接受版本、`problem_map`、`decision_inventory` 与证据摘要，检查：

- 定位、服务对象、产品、空间和运营机制是否互相冲突；
- 某章是否把其他章的条件误写成已确认事实；
- 方案代价、能力障碍、失败场景和退出路径是否跨章闭合；
- 依赖关系是否造成无法兑现的实施顺序或隐藏前提；
- 最强替代解释是否会推翻、降级或改变当前判断。

审校员逐项裁定重大意见，不直接修改章节。问题必须路由到拥有相关决策的原章节 Subagent；该作者使用原证据包与审校意见生成下一版本，再复核受影响章节和全稿。若某章已用完 v3 仍有重大问题，阻止交付。主 Agent 不得静默调和冲突或用风险句关闭问题。

## 波次 7：低损耗合编与装配验收

深度通过后，主 Agent 才生成 `report/project-report.md`。它只能确定顺序、统一术语、添加短过渡、编写执行摘要和综合结论。每个接受章节必须在以下标记之间逐字完整包含：

~~~md
<!-- chapter:start id="regional-people" version="v2" -->
此处原样放入 chapters/regional-people.v2.md 的完整正文
<!-- chapter:end id="regional-people" -->
~~~

需要删除重复、改变论证、压缩实质内容或统一正文措辞时，退回章节所有者生成新版本。主 Agent 不在标记内部编辑。执行摘要、过渡和综合结论位于标记外，也不能用来替代任何接受章节。

合编后先运行：

~~~text
python skills/spatial-business-analyst/scripts/validate_chapter_assembly.py --report-dir <report-directory>
~~~

验收器检查决策唯一所有权、依赖顺序、版本上限、接受状态、审校产物、字符审计、章节标记顺序和正文完整包含关系。失败时不得进入视觉渲染或导出。

## 波次 8：独立视觉证据编辑

`formal_comprehensive` 每次都启动独立视觉证据编辑 Subagent，允许评估后选择零张视觉。它只读取通过装配验收的 `project-report.md`、接受章节索引、`decision_inventory`、真实持久化指标、数据范围和现有视觉清单；主 Agent、章节作者与渲染器都不兼任视觉策划。

视觉 Subagent 负责视觉价值判断、当前批准模板选择、插入位置、计划、渲染编排和实际验收。正式报告中的锚点、图片和题注只能出现在章节标记之外；需要支持某章时，放在该章结束标记之后，不得改变接受正文。视觉完成后重新运行装配验证，再核验视觉资产与 manifest。

正式报告即使零图也保存 `report/visual-plan.json` 与 `report/visual-manifest.json` 并记录省略原因。具体输入、工具链、插入、失败降级和多格式验收遵守 `report-visual-workflow.md`。PDF 使用自然分页；除封面、目录和确有出版必要的主分隔外，不按标题强制一章一页。

## 简单任务边界

简单问答、单项诊断和局部分析仍由主 Agent 直接完成，不创建 `chapter-index.json`、版本章节或审校目录，也不受 1,500-3,000 字符带约束。只有用户要求完整项目报告、正式综合报告或同等深度成果时才进入上述正式流程。
