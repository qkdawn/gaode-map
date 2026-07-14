---
name: spatial-project-data
description: Read history-backed spatial projects through the Spatial Project MCP. Use when answering questions about a history record's scope, linked project documents, POI, population, nightlight, road, grid data, coverage, source year, or data-quality limitations.
---

# Spatial Project Data

Use `list_history_projects` to find a history-backed spatial project. Start with `read_history_project`, then use `list_history_project_documents` and `list_history_project_datasets`.

Use `aggregate_history_project_dataset` for counts and category summaries. Use `query_history_project_dataset` only for a bounded page of records; state its pagination and do not present it as the full dataset. Use `read_history_project_dataset_record` only after locating the record through a dataset query.

Quote the `history_id`, source ID, data year, spatial scope, linked document role, and warnings returned by MCP. Treat POI, nightlight, population, road, and grid values as the indicators they are. Do not infer sales, footfall, spending, revenue, or investment return from them.

When a needed dataset, year, source, or spatial coverage is absent, return the gap and the decision it prevents. Do not fill the gap from model knowledge or unscoped RAG content.
