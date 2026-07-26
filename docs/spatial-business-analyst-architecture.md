# Spatial Business Analyst Skill 架构图

这张图描述当前 `spatial-business-analyst` 的运行架构。它不是通用应用分层图，而是一条由用户确认门解锁、以可恢复状态为底座、由多角色纵向审校并以确定性校验收口的空间商业决策报告流水线。

<div style="width: 1200px; box-sizing: border-box; position: relative; background: #fafbfc; padding: 20px; border-radius: 6px; border: 1px solid #e5e7eb;">
  <style scoped>
    .sba-wrapper { display: flex; gap: 12px; align-items: flex-start; }.sba-main { flex: 1; min-width: 0; }.sba-sidebar { width: 196px; flex-shrink: 0; }.sba-title { text-align: center; font-size: 22px; font-weight: 700; color: #1f2937; margin-bottom: 5px; }.sba-subtitle { text-align: center; font-size: 11px; color: #6b7280; margin-bottom: 16px; }.sba-layer { margin: 8px 0; padding: 13px; border-radius: 6px; box-shadow: 0 1px 3px rgba(0,0,0,0.04); }.sba-layer-title { font-size: 13px; font-weight: 700; margin-bottom: 9px; text-align: center; }.sba-grid { display: grid; gap: 7px; }.sba-grid-2 { grid-template-columns: repeat(2, minmax(0, 1fr)); }.sba-grid-3 { grid-template-columns: repeat(3, minmax(0, 1fr)); }.sba-grid-4 { grid-template-columns: repeat(4, minmax(0, 1fr)); }.sba-box { min-width: 0; border-radius: 4px; padding: 8px 7px; text-align: center; font-size: 10.5px; font-weight: 600; line-height: 1.4; color: #1f2937; background: #fff; border: 1px solid #e5e7eb; }.sba-box small { display: block; margin-top: 3px; color: #6b7280; font-size: 9px; font-weight: 400; line-height: 1.35; }.sba-box.highlight { border: 2px solid #2563eb; background: #fff; }.sba-box.gate { border: 2px solid #d97706; background: #fffbeb; }.sba-box.accept { border: 2px solid #16a34a; background: #f0fdf4; }.sba-box.external { border: 1px dashed #9ca3af; background: #f9fafb; }.sba-entry { background: #eff6ff; border: 2px solid #3b82f6; }.sba-entry .sba-layer-title { color: #1d4ed8; }.sba-flow { background: #fffbeb; border: 2px solid #d97706; }.sba-flow .sba-layer-title { color: #92400e; }.sba-role { background: #f0fdf4; border: 2px solid #16a34a; }.sba-role .sba-layer-title { color: #15803d; }.sba-state { background: #fdf2f8; border: 2px solid #db2777; }.sba-state .sba-layer-title { color: #9d174d; }.sba-tool { background: #f3f4f6; border: 2px solid #6b7280; }.sba-tool .sba-layer-title { color: #374151; }.sba-output { background: #ecfeff; border: 2px solid #0891b2; }.sba-output .sba-layer-title { color: #0e7490; }.sba-pipeline { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 18px 24px; counter-reset: stage; }.sba-stage { position: relative; min-width: 0; border-radius: 4px; padding: 9px 7px 8px; background: #fff; border: 1px solid #f1d38b; text-align: center; }.sba-stage::after { content: "→"; position: absolute; right: -19px; top: 42%; color: #9ca3af; font-size: 16px; }.sba-stage:nth-child(4)::after { content: "↓"; right: 48%; top: auto; bottom: -19px; }.sba-stage:nth-child(5)::after { content: "←"; right: auto; left: -19px; }.sba-stage:nth-child(6)::after { content: "←"; right: auto; left: -19px; }.sba-stage:nth-child(7)::after { content: "←"; right: auto; left: -19px; }.sba-stage:nth-child(8)::after { content: ""; }.sba-stage:nth-child(n+5) { grid-row: 2; }.sba-stage:nth-child(5) { grid-column: 4; }.sba-stage:nth-child(6) { grid-column: 3; }.sba-stage:nth-child(7) { grid-column: 2; }.sba-stage:nth-child(8) { grid-column: 1; }.sba-stage-title { font-size: 10.5px; font-weight: 700; color: #78350f; margin-bottom: 4px; }.sba-stage-note { font-size: 9px; color: #6b7280; line-height: 1.35; }.sba-sidebar-panel { border-radius: 6px; padding: 10px; background: #f3f4f6; border: 1px solid #d1d5db; margin-bottom: 8px; }.sba-sidebar-title { font-size: 11px; font-weight: 700; text-align: center; color: #1f2937; margin-bottom: 6px; }.sba-sidebar-item { font-size: 9.5px; text-align: center; color: #374151; background: #fff; padding: 5px 4px; border-radius: 3px; margin: 3px 0; border: 1px solid #e5e7eb; line-height: 1.3; }.sba-sidebar-item.owner { border-color: #93c5fd; background: #eff6ff; color: #1d4ed8; font-weight: 600; }.sba-sidebar-item.reject { border-color: #fca5a5; background: #fef2f2; color: #991b1b; }.sba-arrow { text-align: center; color: #64748b; font-size: 10px; line-height: 18px; }.sba-loop { margin-top: 8px; padding: 7px; border: 1px dashed #16a34a; border-radius: 4px; text-align: center; color: #166534; background: rgba(255,255,255,0.62); font-size: 9.5px; line-height: 1.4; }.sba-legend { display: flex; gap: 7px; flex-wrap: wrap; justify-content: center; margin-top: 11px; font-size: 9px; color: #4b5563; }.sba-legend span { padding: 3px 6px; border-radius: 3px; background: #fff; border: 1px solid #d1d5db; }
  </style>
  <div class="sba-title">Spatial Business Analyst · Skill Runtime Architecture</div>
  <div class="sba-subtitle">问题地图驱动 · 用户确认解锁 · 专业章节所有权 · 双审校闭环 · 可恢复状态 · 低损装配</div>
  <div class="sba-wrapper">
    <div class="sba-main">
      <div class="sba-layer sba-entry">
        <div class="sba-layer-title">入口与模式路由</div>
        <div class="sba-grid sba-grid-3"><div class="sba-box">用户请求与已保存项目<small>材料、范围、数据集、指标目录</small></div><div class="sba-box highlight">Codex 主 Agent<small>理解语义、选择模式、维护依赖与最终裁决</small></div><div class="sba-box">任务分流<small>简单问答 / 单项诊断 / 局部分析直接交付<br>完整项目报告进入 formal_comprehensive</small></div></div>
      </div>
      <div class="sba-arrow">↓ 正式模式必须先建立事实底稿和问题地图；确认前不得锁定定位、决策清单或正式目录</div>
      <div class="sba-layer sba-flow">
        <div class="sba-layer-title">正式综合报告控制流（波次 0–8）</div>
        <div class="sba-pipeline"><div class="sba-stage"><div class="sba-stage-title">波次 0 · 建模</div><div class="sba-stage-note">读取授权原件与范围<br>建立语义模型、问题地图和同快照状态包</div></div><div class="sba-stage"><div class="sba-stage-title">确认门 · 解锁</div><div class="sba-stage-note">awaiting_confirmation<br>用户确认或修订完整问题地图</div></div><div class="sba-stage"><div class="sba-stage-title">波次 1–3 · 专项研究</div><div class="sba-stage-note">区域与人群、空间结构并行<br>定位比较、空间推演、运营与分期</div></div><div class="sba-stage"><div class="sba-stage-title">波次 4 · 决策收敛</div><div class="sba-stage-note">decision_inventory<br>evidence_summary<br>唯一章节所有者与 chapter-index</div></div><div class="sba-stage"><div class="sba-stage-title">波次 5 · 逐章纵向循环</div><div class="sba-stage-note">作者 v1–v3<br>反方审查 + 深度审校<br>定向返写且不覆盖旧稿</div></div><div class="sba-stage"><div class="sba-stage-title">波次 6 · 全稿审校</div><div class="sba-stage-note">检查跨章冲突、隐藏前提、代价、失败场景与改判路径</div></div><div class="sba-stage"><div class="sba-stage-title">波次 7 · 总编与装配</div><div class="sba-stage-note">出版裁决、定向返写<br>逐字装配 accepted 章节<br>运行 assembly validator</div></div><div class="sba-stage"><div class="sba-stage-title">波次 8 · 独立视觉</div><div class="sba-stage-note">视觉证据编辑可选择零图<br>生成后重新校验正文不变</div></div></div>
      </div>
      <div class="sba-arrow">↓ 专业判断留在章节所有者；审校意见只路由回原作者，不由主 Agent 重写专业正文</div>
      <div class="sba-layer sba-role">
        <div class="sba-layer-title">原生 Agent 协作与所有权</div>
        <div class="sba-grid sba-grid-3"><div class="sba-box highlight">专业章节作者<small>区域与人群 · 空间结构 · 定位与产品 · 空间功能 · 运营与分期<br>各自拥有决策、证据包和章节版本</small></div><div class="sba-box">双审校角色<small>反方审查员：替代解释 / 假设 / 代价 / 失败场景<br>深度审校员：机制 / 比较 / 能力 / 动作 / 改判</small></div><div class="sba-box">总编与视觉证据编辑<small>总编拥有读者主线与出版裁决<br>视觉编辑独立选图，不改写已接受判断</small></div></div>
        <div class="sba-loop">章节作者 → `.adversarial.md` + `.depth.md` → 两个 verdict 均为 `accepted` → 下游可消费；否则定向返写为新版本，超过 v3 或仍有重大问题则停止交付</div>
      </div>
      <div class="sba-arrow">↓ 所有角色通过稳定 ID、固定路径、版本和 checksum 共享状态，不依赖对话记忆恢复运行</div>
      <div class="sba-layer sba-state">
        <div class="sba-layer-title">可恢复状态与版本化报告工件</div>
        <div class="sba-grid sba-grid-4"><div class="sba-box">项目语义模型<small>state/project-semantic-model.json<br>对象、角色、关系、证据与置信度</small></div><div class="sba-box gate">问题地图<small>state/problem-map.json<br>awaiting_confirmation / confirmed</small></div><div class="sba-box">决策与证据<small>decision-inventory.json<br>evidence-summary.json</small></div><div class="sba-box highlight">状态清单<small>state/manifest.json<br>固定路径、schema、snapshot_version、SHA-256</small></div><div class="sba-box">章节责任图<small>chapter-index.json<br>唯一作者、依赖、版本、审校状态</small></div><div class="sba-box">不可覆盖版本<small>chapters/&lt;id&gt;.vN.md<br>chapter-reviews/&lt;id&gt;.vN.*.md</small></div><div class="sba-box">装配报告<small>project-report.md<br>章节边界内逐字保留 accepted 正文</small></div><div class="sba-box">视觉清单<small>visual-plan.json<br>visual-manifest.json<br>assets/*</small></div></div>
      </div>
      <div class="sba-arrow">↓ Skill 负责判断和治理；确定性工具负责取数、计算、渲染与契约校验</div>
      <div class="sba-layer sba-tool">
        <div class="sba-layer-title">证据、空间指标与确定性工具面</div>
        <div class="sba-grid sba-grid-4"><div class="sba-box external">项目与原件<small>history project / DOCX / PDF ResourceLink<br>范围、数据集与已有结果</small></div><div class="sba-box">空间指标服务<small>catalog → detail → execute<br>POI · 人口 · 夜光 · 路网 · 等时圈 · H3</small></div><div class="sba-box">查询与推断边界<small>空间条件下查询，不本地伪算距离<br>代理指标不升级为客流、营收或 ROI</small></div><div class="sba-box accept">确定性校验与渲染<small>validate_chapter_assembly.py<br>受限 Vega / ArcGIS 视觉工具链</small></div></div>
      </div>
      <div class="sba-arrow">↓ 装配通过后才允许视觉、HTML 或 PDF；视觉失败不降低正文，也不阻塞文字报告</div>
      <div class="sba-layer sba-output">
        <div class="sba-layer-title">交付边界</div>
        <div class="sba-grid sba-grid-3"><div class="sba-box accept">主交付<small>可独立成立的 Markdown 决策报告</small></div><div class="sba-box">可选格式<small>用户明确要求时导出 HTML / PDF</small></div><div class="sba-box">可追溯性<small>重要选择 → 所有者章节 → 证据 ID → 反证 → 动作 → 改判条件</small></div></div>
      </div>
      <div class="sba-legend"><span>蓝：入口与主控制面</span><span>黄：波次编排与确认门</span><span>绿：Agent 所有权与审校</span><span>粉：可恢复状态</span><span>灰：确定性数据工具</span><span>青：交付边界</span></div>
    </div>
    <div class="sba-sidebar">
      <div class="sba-sidebar-panel"><div class="sba-sidebar-title">唯一事实源</div><div class="sba-sidebar-item owner">report-contract.md<br>状态 / 版本 / 接受 / 装配</div><div class="sba-sidebar-item">report-orchestration.md<br>波次时序</div><div class="sba-sidebar-item">specialist-roles.md<br>专业职责</div><div class="sba-sidebar-item">quality-gates.md<br>分析深度与拒绝条件</div><div class="sba-sidebar-item">publication-editorial.md<br>读者表达与总编裁决</div><div class="sba-sidebar-item">report-visual-workflow.md<br>视觉编排与失败降级</div></div>
      <div class="sba-sidebar-panel"><div class="sba-sidebar-title">关键质量门</div><div class="sba-sidebar-item">问题地图先确认</div><div class="sba-sidebar-item">真实候选同尺度比较</div><div class="sba-sidebar-item">证据改变具体行动</div><div class="sba-sidebar-item">反例、代价与能力承接</div><div class="sba-sidebar-item">唯一决策与章节所有者</div><div class="sba-sidebar-item">上下游只消费 accepted 版本</div><div class="sba-sidebar-item">装配与视觉后再次校验</div></div>
      <div class="sba-sidebar-panel"><div class="sba-sidebar-title">硬性拒绝 / 停止</div><div class="sba-sidebar-item reject">确认前锁定结论或目录</div><div class="sba-sidebar-item reject">指标罗列代替项目机制</div><div class="sba-sidebar-item reject">代理数据伪装经营结论</div><div class="sba-sidebar-item reject">主 Agent 改写 accepted 正文</div><div class="sba-sidebar-item reject">超过 v3 或重大问题未闭合</div><div class="sba-sidebar-item reject">虚构视觉或用失败图替代</div></div>
      <div class="sba-sidebar-panel"><div class="sba-sidebar-title">设计边界</div><div class="sba-sidebar-item">Codex：语义、判断、协作、裁决</div><div class="sba-sidebar-item">Subagent：专业决策与章节所有权</div><div class="sba-sidebar-item">Python / 工具：真实数据与确定性</div><div class="sba-sidebar-item">状态包：跨角色恢复与一致性</div></div>
    </div>
  </div>
</div>

## 读图要点

- **架构主轴是决策闭环，不是工具链。** 工具只提供可复核事实；正式报告从问题地图开始，经过候选比较、决策归属、章节双审校和总编裁决后才形成公开结论。
- **用户确认是硬门。** `problem-map.json` 从 `awaiting_confirmation` 变为 `confirmed` 后，专项研究、决策清单和正式章节才解锁。
- **状态包是运行底座。** 五个固定状态文件使用统一快照和 SHA-256 清单，使主 Agent 与 Subagent 可以校验、恢复和继续运行，而不依赖历史对话。
- **专业正文有唯一所有者。** 主 Agent 负责语义、依赖、验收和出版综合，不从自由散文中重建专业判断，也不在装配阶段改写已接受章节。
- **视觉是独立、可省略的后置层。** 只有装配校验通过后才选图；零视觉是合法结果，视觉失败时保留能够独立成立的文字报告。

## 源文件映射

- 入口与模式边界：`skills/spatial-business-analyst/SKILL.md`
- 波次与完成条件：`skills/spatial-business-analyst/references/report-orchestration.md`
- 状态、版本、接受和装配契约：`skills/spatial-business-analyst/references/report-contract.md`
- 角色所有权：`skills/spatial-business-analyst/references/specialist-roles.md`
- 分析拒绝条件：`skills/spatial-business-analyst/references/quality-gates.md`
- 总编与视觉边界：`skills/spatial-business-analyst/references/publication-editorial.md`、`report-visual-workflow.md`
- 确定性装配入口：`skills/spatial-business-analyst/scripts/validate_chapter_assembly.py`
