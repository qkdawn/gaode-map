# 价值路径与部署样板

本文件唯一拥有正式综合报告的 `价值路径` 定义、状态字段和写作表达。`report-contract.md` 只拥有其状态文件的存在与结构约束；`decision-rulebook.md` 只拥有 R1-R6 如何消费该路径。

## 价值路径

价值路径将已确认的现状、可在现场运行的最小工作流、可观察产出、对特定受益者有意义的结果，以及条件成立后的长期公共、社会、环境或经济影响连成一条因果路径。

它借鉴 theory-based evaluation 的 `输出 -> 结果 -> 影响` 路径，并显式记录“谁从何种价值中受益”。城市更新还必须区分项目介入期与更长的更新期，并记录不同利益相关者的时间单位；居民当下的日常需要不能被远期总体愿景覆盖。

正式运行的 `decision-logic-map.json` 在 `payload.value_path` 保存：

```yaml
baseline: 当前正在发生、且值得改变的具体使用或治理状态
beneficiaries:
  - stakeholder: 受益者或承担者
    current_need: 其当前需要、任务或权益
    timeframe: 其相关的日、周、季节、学年或其他时间单位
desired_outcome: 一期之后应出现的可观察改变
deployable_workflow:
  user: 谁进入或触发工作流
  trigger: 在什么时点、事件或需求下发生
  service: 完成什么服务、参与或协同行为
  space: 在哪个可承接的空间或数字界面完成
  operator: 谁负责现场、内容、协调或系统响应
  record: 用什么真实记录判断该工作流是否运行
outputs:
  - 一期可直接观察到的交付或服务完成记录
outcomes:
  - 一期至近期的使用、协同、能力或价值改变
impacts:
  - 仅在有合理路径时陈述的长期公共、社会、环境或经济影响
assumptions:
  - 连接前一环与后一环、仍须检验的前提
intervention_window: 本次一期介入的明确时段
outcome_horizon: 结果和影响的观察窗口，不等同于介入期
expansion_or_stop: 用哪些记录扩大、调整、缩减或停止
replication_unit: 成功后可复制到的下一服务、空间或组织单元
```

## 部署样板

`部署样板` 是价值路径中的 `deployable_workflow`：一个真实使用者在真实场景中完成一次有承接者的服务或参与，并留下可供下一轮决策使用的记录。概念、活动清单、访谈、展览大纲和风险控制动作只有嵌入这个工作流后才构成样板的一部分。

一个合格样板同时回答：

1. 谁在什么情境下获得什么服务、体验或协同结果；
2. 空间、内容、数字界面和运营者怎样共同承接这次发生；
3. 当天或当期能留下什么产出记录；
4. 哪些近期结果会说明价值路径成立；
5. 哪些记录支持复制，哪些记录要求调整或停止。

## 写作顺序

正文与执行摘要以价值路径的前四环组织：`受益者与当前状态 -> 希望发生的改变 -> 部署样板 -> 可见产出与近期结果`。空间、许可、居民权利、承载、成本与其他边界在说明它们如何塑造部署样板和资源优先级时出现。

对于需要缩减、延后或退出的路径，先说明一期样板保留的价值、未被选择的路径，以及资源优先级如何改变；再说明记录达到何种条件后可重新比较。边界作为部署样板的运行条件表达。

## 证据边界

输出可以由一期服务记录、完成件数、开放时段、参与人数或空间使用记录观察；结果需要重复使用、服务闭合、协同、冲突、投诉、内容供给或组织响应等记录支持；长期影响通常只能作为条件性路径，不能由短期活动、POI、人口、夜光或单个案例直接断言。

价值路径可以包含经济价值，但需区分公开成本基准、项目实际成本、支付/采购记录和推演参数。没有直接交易或采购记录时，报告只陈述条件性经济机制与校准动作。

## 研究依据

- Zohar, Simeone, de Gotzen, and Morelli, [*Mapping urban regeneration through multiple dimensions of temporality*](https://dl.designresearchsociety.org/cgi/viewcontent.cgi?article=1028&context=iasdr), 2023：变革理论把当前条件、预期结果和介入措施连成变化逻辑；城市更新还需让不同主体的时间单位、一期介入期与更长的更新期可见。
- Mens, van Bueren, Vrijhoef, and Heurkens, [*Identifying the merits of bottom-up urban development: theory-based evaluation using a value map model*](https://repository.tudelft.nl/file/File_1f74342e-77fd-4da9-a0f5-07f955d83366), 2023：价值地图以输出、结果和影响区分价值的时间层级，并记录受益者和价值路径；较远的影响需要沿路径保留假设和证据边界。
