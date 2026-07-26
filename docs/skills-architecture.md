# 项目级 Skill-first 架构

这张图描述当前仓库的项目级 Skill 架构。全局安装的通用技能作为 Codex 的可选支撑能力存在；产品主链路由两个项目级 Skill 驱动。

<div style="width: 1200px; box-sizing: border-box; position: relative; background: #fafbfc; padding: 20px; border-radius: 6px; border: 1px solid #e5e7eb;">
  <style scoped>
    .arch-wrapper { display: flex; gap: 12px; align-items: flex-start; }.arch-sidebar { width: 190px; flex-shrink: 0; }.arch-main { flex: 1; min-width: 0; }.arch-title { text-align: center; font-size: 22px; font-weight: bold; color: #1f2937; margin-bottom: 6px; }.arch-subtitle { text-align: center; font-size: 11px; color: #6b7280; margin-bottom: 16px; }.arch-layer { margin: 8px 0; padding: 14px; border-radius: 6px; box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04); }.arch-layer-title { font-size: 13px; font-weight: bold; margin-bottom: 10px; text-align: center; }.arch-grid { display: grid; gap: 8px; }.arch-grid-2 { grid-template-columns: repeat(2, 1fr); }.arch-grid-3 { grid-template-columns: repeat(3, 1fr); }.arch-grid-4 { grid-template-columns: repeat(4, 1fr); }.arch-grid-5 { grid-template-columns: repeat(5, 1fr); }.arch-box { border-radius: 4px; padding: 8px; text-align: center; font-size: 11px; font-weight: 600; line-height: 1.35; color: #1f2937; background: #ffffff; border: 1px solid #e5e7eb; }.arch-box.highlight { background: #ffffff; border: 2px solid #2563eb; }.arch-box.tech { font-size: 10px; color: #4b5563; background: #f9fafb; }.arch-layer.user { background: linear-gradient(135deg, #eff6ff 0%, #dbeafe 100%); border: 2px solid #3b82f6; }.arch-layer.user .arch-layer-title { color: #1d4ed8; }.arch-layer.application { background: linear-gradient(135deg, #fffbeb 0%, #fef3c7 100%); border: 2px solid #d97706; }.arch-layer.application .arch-layer-title { color: #92400e; }.arch-layer.ai { background: linear-gradient(135deg, #f0fdf4 0%, #dcfce7 100%); border: 2px solid #16a34a; }.arch-layer.ai .arch-layer-title { color: #15803d; }.arch-layer.data { background: linear-gradient(135deg, #fdf2f8 0%, #fce7f3 100%); border: 2px solid #db2777; }.arch-layer.data .arch-layer-title { color: #9d174d; }.arch-layer.infra { background: linear-gradient(135deg, #f3f4f6 0%, #e5e7eb 100%); border: 2px solid #6b7280; }.arch-layer.infra .arch-layer-title { color: #374151; }.arch-layer.external { background: linear-gradient(135deg, #f9fafb 0%, #f3f4f6 100%); border: 1px dashed #9ca3af; }.arch-layer.external .arch-layer-title { color: #6b7280; }.arch-sidebar-panel { border-radius: 6px; padding: 10px; background: linear-gradient(135deg, #f3f4f6 0%, #e5e7eb 100%); border: 1px solid #d1d5db; margin-bottom: 8px; }.arch-sidebar-title { font-size: 12px; font-weight: bold; text-align: center; color: #1f2937; margin-bottom: 6px; }.arch-sidebar-item { font-size: 10px; text-align: center; color: #374151; background: #ffffff; padding: 6px 5px; border-radius: 3px; margin: 3px 0; border: 1px solid #e5e7eb; }.arch-sidebar-item.metric { background: #eff6ff; border: 1px solid #93c5fd; color: #1d4ed8; font-weight: 600; }.arch-product-group { display: flex; gap: 10px; }.arch-product { flex: 1; border-radius: 6px; padding: 10px; background: rgba(255, 255, 255, 0.65); border: 1px dashed rgba(0, 0, 0, 0.18); }.arch-product-title { font-size: 12px; font-weight: bold; color: #374151; margin-bottom: 8px; text-align: center; }.arch-note { margin-top: 8px; font-size: 10px; line-height: 1.45; color: #4b5563; text-align: center; }.arch-arrow { text-align: center; color: #64748b; font-size: 18px; line-height: 20px; }.arch-legend { display: flex; gap: 8px; flex-wrap: wrap; justify-content: center; margin-top: 12px; font-size: 10px; color: #4b5563; }.arch-legend span { padding: 3px 7px; border-radius: 3px; border: 1px solid #d1d5db; background: #fff; }.arch-legend .control { border-color: #3b82f6; }.arch-legend .knowledge { border-color: #d97706; }.arch-legend .data { border-color: #db2777; }.arch-legend .artifact { border-color: #16a34a; }
  </style>
  <div class="arch-title">Project Skill-first Architecture</div>
  <div class="arch-subtitle">判断与协作由 Codex / Skill 承担，数据与确定性由 Python 领域代码承担</div>
  <div class="arch-wrapper">
    <div class="arch-sidebar">
      <div class="arch-sidebar-panel"><div class="arch-sidebar-title">Codex 能力注册表</div><div class="arch-sidebar-item metric">architecture / diagram</div><div class="arch-sidebar-item">research / writing</div><div class="arch-sidebar-item">browser / QA</div><div class="arch-sidebar-item">frontend / visualization</div><div class="arch-note">通用技能按任务按需加载，不改变项目领域契约。</div></div>
      <div class="arch-sidebar-panel"><div class="arch-sidebar-title">共享治理边界</div><div class="arch-sidebar-item">授权资源边界</div><div class="arch-sidebar-item">证据等级与代理限制</div><div class="arch-sidebar-item">质量门槛</div><div class="arch-sidebar-item">一次定向退修</div><div class="arch-sidebar-item">不可变 Run</div></div>
    </div>
    <div class="arch-main">
      <div class="arch-layer user">
        <div class="arch-layer-title">入口与控制面</div>
        <div class="arch-grid arch-grid-3"><div class="arch-box">用户问题与项目材料<br><small>决策目标 / 范围 / 约束</small></div><div class="arch-box highlight">Codex 主 Agent<br><small>理解问题 · 规划任务 · 验收交付</small></div><div class="arch-box">Codex 原生 Subagent<br><small>按依赖波次并行执行</small></div></div>
      </div>
      <div class="arch-arrow">↓ 选择项目级 Skill，形成问题地图与任务依赖</div>
      <div class="arch-layer application">
        <div class="arch-layer-title">项目级 Skill 层</div>
        <div class="arch-product-group">
          <div class="arch-product"><div class="arch-product-title">spatial-business-analyst</div><div class="arch-grid arch-grid-2"><div class="arch-box">项目语义模型</div><div class="arch-box">问题地图确认</div><div class="arch-box">专业章节编排</div><div class="arch-box">受约束综合</div></div><div class="arch-note">完整空间商业决策报告；以 accepted ChapterDeliveryPackage 为综合输入。</div></div>
          <div class="arch-product"><div class="arch-product-title">urban-strategy-stage1</div><div class="arch-grid arch-grid-2"><div class="arch-box">Stage 1 证据整理</div><div class="arch-box">四类专家 Workpack</div><div class="arch-box">策略选项比较</div><div class="arch-box">Stage 2 Design Handoff</div></div><div class="arch-note">回答“场所应做什么”；不进入建筑形态与施工设计。</div></div>
        </div>
      </div>
      <div class="arch-arrow">↓ 读取授权材料、知识卡、工具结果；专业任务只获得最小必要上下文</div>
      <div class="arch-layer ai">
        <div class="arch-layer-title">共享知识与交付契约</div>
        <div class="arch-grid arch-grid-4"><div class="arch-box tech">references/<br><small>角色 · 编排 · 指标 · 质量 · 出版</small></div><div class="arch-box tech">ChapterAssignment<br><small>决策问题 · 授权资源 · 上游依赖</small></div><div class="arch-box tech">ChapterDeliveryPackage<br><small>finding · action · validation · evidence</small></div><div class="arch-box tech">Schema / Completion Gate<br><small>引用、状态、可恢复性、一致性</small></div></div>
      </div>
      <div class="arch-arrow">↓ 调用稳定工具接口，返回可复用 result ID 与数据健康信息</div>
      <div class="arch-layer data">
        <div class="arch-layer-title">Python 领域数据面</div>
        <div class="arch-grid arch-grid-4"><div class="arch-box">项目输入与资源读取<br><small>文档 · 范围 · 数据集</small></div><div class="arch-box highlight">空间分析与指标工具<br><small>POI · H3 · 人口 · 夜光 · 路网 · 等时圈</small></div><div class="arch-box">数据健康与结果复用<br><small>年份 · NoData · 几何 · 可用性</small></div><div class="arch-box">确定性校验与报告编译<br><small>不调用 LLM，不替换专业判断</small></div></div>
      </div>
      <div class="arch-arrow">↓ 生成公开白名单工件</div>
      <div class="arch-layer infra">
        <div class="arch-layer-title">运行工件与保存边界</div>
        <div class="arch-grid arch-grid-5"><div class="arch-box tech">source-index.json</div><div class="arch-box tech">analysis-plan.json</div><div class="arch-box tech">chapters/*.json</div><div class="arch-box tech">report/*.md + SVG</div><div class="arch-box tech">design_handoff.json<br><small>run_manifest.json</small></div></div>
      </div>
      <div class="arch-layer external">
        <div class="arch-layer-title">外部与项目数据来源</div>
        <div class="arch-grid arch-grid-4"><div class="arch-box tech">高德地图与 POI</div><div class="arch-box tech">GIS / 栅格 / 路网数据</div><div class="arch-box tech">DOCX / PDF / 图片</div><div class="arch-box tech">用户现场验证与经营数据</div></div>
      </div>
      <div class="arch-legend"><span class="control">蓝：控制面</span><span class="knowledge">黄：Skill 与契约</span><span class="data">粉：领域数据面</span><span class="artifact">绿：交付与验证边界</span></div>
    </div>
    <div class="arch-sidebar">
      <div class="arch-sidebar-panel"><div class="arch-sidebar-title">当前主链路</div><div class="arch-sidebar-item">1. 读取项目与范围</div><div class="arch-sidebar-item">2. 建立问题地图</div><div class="arch-sidebar-item">3. 分派专业任务</div><div class="arch-sidebar-item">4. 验收 / 退修一次</div><div class="arch-sidebar-item">5. 受约束综合</div><div class="arch-sidebar-item">6. 校验与编译</div></div>
      <div class="arch-sidebar-panel"><div class="arch-sidebar-title">明确不在 Skill 内</div><div class="arch-sidebar-item">Python LLM Runtime</div><div class="arch-sidebar-item">Provider 驱动调度器</div><div class="arch-sidebar-item">自由章节散文直出</div><div class="arch-sidebar-item">V3 双路径兼容层</div><div class="arch-note">Skill 只保留判断、协作、上下文授权和交付语义。</div></div>
    </div>
  </div>
</div>

## 读图要点

- **控制面**：`Codex 主 Agent` 负责理解项目、生成专业任务、按依赖分派 Subagent，并对章节交付做 `accepted / revision_required / failed` 验收。
- **领域数据面**：`modules/`、`core/`、`store/` 与相关工具负责材料读取、空间计算、数据健康、结果复用、Schema 校验和确定性报告编译。
- **两个项目级 Skill**：`spatial-business-analyst` 面向完整空间商业决策报告；`urban-strategy-stage1` 面向 Stage 1 城市与区域策略，并输出后续设计交接。
- **统一交付契约**：专业 Subagent 输出结构化 `ChapterDeliveryPackage`，使 finding、action、validation condition 和 evidence link 可追溯，避免总编从自由散文中猜测推导关系。
- **边界原则**：判断与协作由 Codex 承担，数据与确定性由 Python 承担；不恢复 Python 内置 LLM 编排器、V3 双路径或旧字段兼容层。
