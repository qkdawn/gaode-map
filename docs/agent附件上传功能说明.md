# Agent 附件上传功能说明

本文用于简要说明当前 `/analysis` Agent 的附件上传能力：现在能做什么、后台怎么处理、依赖什么开源能力、当前边界在哪里。

## 1. 现在能做什么

当前 Agent 已经支持用户在对话里上传附件，并把附件作为后续问答的证据来源。

它的核心能力不是“把整份文件直接塞给模型”，而是：

```text
上传附件
-> 后台解析
-> 切成可检索片段
-> Agent 在需要时检索片段
-> 引用附件证据回答问题
```

这意味着它更像一个“附件 RAG 证据层”，而不是一个全文精读型文件助手。

## 2. 当前支持的文件类型

当前允许上传的类型包括：

- PDF
- 图片：`jpg`、`jpeg`、`png`、`bmp`、`tiff`、`tif`、`gif`、`webp`
- Office：`doc`、`docx`、`ppt`、`pptx`、`xls`、`xlsx`
- 文本：`txt`、`md`

默认单个附件大小上限是 `30MB`。

相关配置在 [core/config.py](/D:/Coding/map_analyse/gaode-map/core/config.py)。

## 3. 当前上传后的处理流程

后端接口在 [router/domains/agent.py](/D:/Coding/map_analyse/gaode-map/router/domains/agent.py)：

- `POST /api/v1/analysis/agent/attachments`
- `GET /api/v1/analysis/agent/attachments`
- `DELETE /api/v1/analysis/agent/attachments/{attachment_id}`

上传后，系统会先把文件落盘，再异步解析。

本地目录结构大致是：

```text
runtime/agent_uploads/{conversation_id}/{attachment_id}/
  source/    原始文件
  rag/       RAG-Anything 工作目录
  parsed/    解析输出目录
  metadata.json
  chunks.json
```

附件状态有四种：

- `uploaded`
- `processing`
- `ready`
- `failed`

只有当附件进入 `ready` 状态后，才会被 Agent 当作可用证据。

主要处理逻辑在 [modules/retrieval/attachments.py](/D:/Coding/map_analyse/gaode-map/modules/retrieval/attachments.py)。

## 4. Agent 怎么使用附件

当前 Agent 不会默认全文读取附件。

它的做法是：

1. 上传后把附件解析成多个片段 chunk
2. 当用户问题提到文件、附件、报告、图纸、图片、表格时，优先搜索附件上下文
3. 命中后再读取具体片段
4. 把命中的片段作为证据写进回答

对应的两个工具是：

- `search_uploaded_attachment_context`
- `read_uploaded_attachment_context`

工具接线在 [modules/agent/tool_adapters/retrieval_tools.py](/D:/Coding/map_analyse/gaode-map/modules/agent/tool_adapters/retrieval_tools.py)。

换句话说，当前附件能力是“先检索，再引用”，不是“整份文件直接通读”。

## 5. 当前依赖的开源仓库

当前这套附件解析能力依赖的核心开源项目是：

- `raganything[all]==1.3.1`

它对应的主仓库是：

- [HKUDS/RAG-Anything](https://github.com/HKUDS/RAG-Anything)

从当前代码看，项目直接使用了：

- `RAGAnything`
- `RAGAnythingConfig`
- `lightrag.llm.openai`

所以可以理解为：

- 主能力来自 `RAG-Anything`
- 底层还依赖了 `LightRAG` 体系

项目依赖声明在 [pyproject.toml](/D:/Coding/map_analyse/gaode-map/pyproject.toml)。

## 6. 当前产品边界

这套能力现在是可用的，但边界也很明确。

第一，它依赖异步解析。  
上传成功不等于立刻可问，需要等状态变成 `ready`。

第二，它本质上是片段检索。  
更擅长“从附件里找相关证据”，而不是“稳定地对整份长文档做完整结构化理解”。

第三，它是 Agent 的补充证据层。  
附件证据会和地图范围、POI、人口、夜光、路网等分析结果一起被使用，但不会替代这些空间分析能力。

第四，它的答案可信度取决于解析质量。  
如果上游文档解析不完整、图片 OCR 不稳定，最终可检索证据也会受影响。

## 7. 一句话总结

当前 Agent 附件上传功能已经能支持：

```text
上传 PDF / 图片 / Office / 文本材料
-> 后台解析成可检索片段
-> 在后续问答里作为证据引用
```

它当前更适合作为“分析对话的附件证据层”，而不是独立的通用文档问答产品。
