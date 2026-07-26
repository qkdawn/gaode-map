# spatial-business-analyst internal regression scenarios

这组场景用于仓库内部回归，评估 Codex 执行 `spatial-business-analyst` Skill 的行为，不是可在论文中报告为公开 benchmark 的评测集。材料刻意使用虚构且每轮可替换的对象名，避免模型记忆示例词汇。

论文评测应使用公开数据、固定测试集、公开评估脚本和已发表的基线。对于本项目，优先采用 MapEval（ICML 2025）和 MapQA；这组内部场景只能作为补充的 failure-mode regression，不能与公开 benchmark 分数混合汇报。

## 推荐运行顺序

1. 先运行 5 个 `forward` case，确认模式边界、对象保留和场景适配。
2. 再运行 `adversarial-confirmation-gate` 和 `adversarial-no-benchmark`，这是最容易产生误导性结论的入口风险。
3. 最后运行 `adversarial-counterexample` 与 `adversarial-assembly-ownership`，检查审校、返写、所有权和确定性装配。

每个 case 保存：输入材料、首次响应、确认后的响应（仅 formal case）、状态工件/章节工件（如有）和评分 JSON。不要把运行结果写入仓库；建议放在 `runtime/benchmarks/<run-id>/`。

## 评分

每个维度按 0/1/2 评分：0=违反或缺失，1=部分满足，2=完整且可追溯。5 个维度总分 10 分。

- `forward`：总分至少 8，且 `mode`、`evidence` 不得为 0。
- `adversarial`：总分至少 9；确认门、无基准、反方退修、装配篡改四项的对应 `must` 必须全部满足。
- 任一 `must_not` 出现即该 case 失败，不用总分抵消。

这套规则与 `references/adaptive-forward-tests.md` 的五类材料包、对抗性深度测试、反方审查、纵向循环和总编装配门一一对应。真正的回归通过条件应同时包含模型响应和已有的 `validate_chapter_assembly.py` 结果。

## 当前执行状态

仓库当前将 `spatial-business-analyst` 注册为 `executable: false`（`Skill 尚未注册执行器`），因此没有可从 API/CLI 批量提交这 9 个语义 case 的本地运行器。当前可执行的契约回归命令是：

```text
python -m pytest tests/benchmarks tests/domain/test_spatial_business_chapter_assembly.py tests/domain/test_spatial_business_region_contract.py tests/domain/test_spatial_business_skill_tools.py tests/domain/test_spatial_project_skills.py -q
```

本轮结果：50 passed。语义 case 仍需在 Codex 原生 Skill 执行环境中逐项运行；在执行器注册前，不应把它们标记为自动通过。

## External Benchmarks

公开 benchmark 与上面的内部回归场景分别计分。外部数据不提交到仓库：MapEval 未在仓库声明数据许可证，MapQA 使用 CC BY-NC 4.0。通过本地、固定提交的副本运行：

```text
git clone https://github.com/MapEval/MapEval-Textual.git external/MapEval-Textual
git -C external/MapEval-Textual checkout 4adde14abd8dbeb820eaed694ec528d5ef3d664f

git clone https://github.com/knowledge-computing/MapQA-dataset.git external/MapQA-dataset
git -C external/MapQA-dataset checkout 385501792cf948baa284dfa0ae65ed77c3c991e8
```

预测文件采用 JSONL。MapEval-Textual 使用原题目 `id` 和一基 option 编号；MapQA 使用 `<csv 文件名>:<原始 ID>` 和文本答案：

```json
{"id": 479, "option_no": 1}
{"case_id": "distance_dataset:1", "answer": "1.76 km"}
```

运行并保存可审计结果：

```text
python scripts/evaluate_external_spatial_benchmarks.py mapeval-textual --dataset external/MapEval-Textual/dataset.json --predictions runtime/benchmarks/mapeval-textual.jsonl --output runtime/benchmarks/mapeval-textual-result.json
python scripts/evaluate_external_spatial_benchmarks.py mapqa --dataset external/MapQA-dataset/llm/illinois_test/question-answer --predictions runtime/benchmarks/mapqa-illinois.jsonl --output runtime/benchmarks/mapqa-illinois-result.json
```

MapQA 对 `distance_dataset` 采用论文中的小于 100 米误差阈值；其他题型采用大小写、空白归一化后的精确答案匹配。结果中保留数据与预测 SHA-256、覆盖率、无效输出和多余 ID。

### Codex-native execution protocol

先构建不含答案的 prompt pack；构建器仅从 MapEval 的 `context/question/options` 与 MapQA 的 `question`、同题 OSM 几何 JSON 读取输入，绝不将 CSV 的 `Answer` 或 MapEval 的 `correct` 写入 prompt：

```text
python scripts/prepare_external_spatial_benchmark_prompts.py mapeval-textual --dataset external/MapEval-Textual/dataset.json --output runtime/benchmarks/mapeval-textual-prompts.jsonl --manifest runtime/benchmarks/mapeval-textual-input-manifest.json
python scripts/prepare_external_spatial_benchmark_prompts.py mapqa --dataset external/MapQA-dataset/llm/illinois_test/question-answer --output runtime/benchmarks/mapqa-illinois-prompts.jsonl --manifest runtime/benchmarks/mapqa-illinois-input-manifest.json
```

对每条 JSONL 记录开启独立、无历史的 Codex 会话；固定模型版本、reasoning effort、系统提示、温度/采样配置和 Skill 提交版本。只收集严格 JSON 响应，再转换为评分器要求的 prediction JSONL。不得把数据集目录、评分器、答案 CSV/JSON，或前一题的输出提供给运行中的 Agent。每个实验保存 prompt manifest、原始响应、转换器版本、prediction JSONL 和结果 JSON。

仓库提供 `run_codex_spatial_benchmark.py`，将每题放在独立的临时空工作区执行，不让 Agent 读取本地 benchmark 文件；`--limit` 适用于预注册 pilot，`--all` 才运行完整测试集：

```text
python scripts/run_codex_spatial_benchmark.py --prompt-pack runtime/benchmarks/mapeval-textual-prompts.jsonl --codex-bin <codex-cli-path> --limit 30 --workers 1 --predictions runtime/benchmarks/mapeval-textual-pilot.jsonl --raw-output-dir runtime/benchmarks/mapeval-textual-pilot-raw
python scripts/evaluate_external_spatial_benchmarks.py mapeval-textual --dataset external/MapEval-Textual/dataset.json --predictions runtime/benchmarks/mapeval-textual-pilot.jsonl --output runtime/benchmarks/mapeval-textual-pilot-result.json
```

pilot 只能用于检查输出契约、成本和失败率，不能作为 MapEval 的正式完整成绩；正式报告使用固定配置下的 `--all` 运行，并分别报告任何未完成项。

对于完整运行，`--workers` 仅并发启动彼此隔离的会话，不共享 prompt、工作区或原始响应。固定并发数并在论文中报告它；不要用并发数改变后的继续运行和原运行混合为同一实验。

MapEval-Textual 是固定证据下的文本地图推理评测，可报告为该 benchmark 的适配运行。MapQA 的 prompt pack 同样固定题目对应的 OSM 几何证据，测量空间推理与答案生成；它**不**证明 Agent 调用了空间工具。要在论文中主张 tool-use / SQL execution，还需要作者发布或自行复现一个隔离的 OSM/PostGIS 工具环境，并在结果中另列为 `MapQA tool-grounded adaptation`，不得与公开数据的纯 QA 分数混报。

`mapeval-api` 被显式拒绝。其官方代码依赖未发布的 `localhost:5000` 地图后端；用高德接口替换工具后只能作为新的适配实验，不能报告为官方 MapEval-API 成绩。
