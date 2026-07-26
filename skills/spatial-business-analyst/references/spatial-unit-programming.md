# 多建筑与空间单元功能策划

## 适用条件

城市更新、园区、校园、街区、文旅和多建筑项目应创建“空间功能策划与建筑再利用”任务。它不替代商业、可达性或运营分析，而是回答：

> 每个空间单元未来分别做什么，它们如何共同形成完整项目？

## 层级关系

根据 `project_semantic_model` 的真实对象和关系选择合适层级。存在多层空间结构时，可使用系统、组团、单元或线性关系；单体、开放式或非建筑项目不强行套用三级结构。原始对象名称始终保留，通用角色只用于组织分析。

## 单元交付

每个确认单元必须产生一条 `ObjectDecision`：

```yaml
object_id:
object_name:
object_type:
recommendation_status: planned | blocked | excluded
recommended_use:
serves:
project_role:
rationale:
prerequisites: []
finding_ids: []
evidence_links: []
limitations: []
```

- `planned`：给出建议用途、服务对象、项目作用、理由和实施前提；
- `blocked`：明确缺少产权、测绘、安全、相关方意愿或运营数据，并给出补齐动作；
- `excluded`：说明为什么不纳入当前阶段或不适合目标功能；
- 不允许静默省略。

## 项目组合检查

空间功能章节必须检查：

- 功能是否过度重复；
- 公共卫生、仓储、设备、后勤等支持功能是否缺失；
- 关键到达、连接、服务和使用关系是否连续；
- 不同使用者、运营或安全流线是否冲突；
- 实际存在的时段和使用方式是否失衡；
- 消防、无障碍、产权和保护要求是否构成前置依赖；
- 首期激活是否能在不完成全部改造时成立。

组合检查必须写入 `portfolio_check`，不能只分散在单元卡片中。

## 覆盖验收

主 Agent 核对：

```text
required_object_ids
= planned object IDs
+ blocked object IDs
+ excluded object IDs
```

发现遗漏时补齐对应对象。资料不足时给出组团级或条件性建议，不静默删除对象。
