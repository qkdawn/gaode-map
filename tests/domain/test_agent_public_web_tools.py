import asyncio

import modules.agent.tool_adapters.public_web_tools as public_web_tools
from modules.agent.schemas import AnalysisSnapshot


class _Response:
    def __init__(self, items, warnings=None):
        self.items = items
        self.warnings = warnings or []
        self.summary = "test"
        self.evidence_refs = [item["url"] for item in items if item.get("url")]


def test_public_web_no_results_is_success_after_three_rounds(monkeypatch):
    requests = []

    async def fake_preview(request):
        requests.append(request)
        return _Response([])

    monkeypatch.setattr(public_web_tools, "preview_ppt_web_source", fake_preview)
    result = asyncio.run(public_web_tools.search_public_web(
        arguments={"history_id": "h-1", "categories": ["历史与文化"]},
        snapshot=AnalysisSnapshot(context={}), artifacts={}, question="test",
    ))

    assert result.status == "success"
    assert result.result["coverage_status"] == "searched_no_usable_source"
    assert len(requests) == 3
    assert [attempt["round"] for attempt in result.result["attempts"]] == [1, 2, 3]
    assert result.result["category_coverage"][0]["attempt_count"] == 3
    assert result.artifacts["public_web_sources"]["coverage_status"] == "searched_no_usable_source"


def test_public_web_stops_category_after_usable_source(monkeypatch):
    requests = []

    async def fake_preview(request):
        requests.append(request)
        return _Response([{
            "title": "城市更新行动方案",
            "url": "https://example.gov.cn/source",
            "source_name": "示例市人民政府",
            "published_at": "2026-01-02",
            "accessed_at": "2026-07-26",
            "parse_status": "parsed",
            "web_evidence_nodes": [{"id": "n1", "content": "推进存量空间活化利用。"}],
        }])

    monkeypatch.setattr(public_web_tools, "preview_ppt_web_source", fake_preview)
    result = asyncio.run(public_web_tools.search_public_web(
        arguments={"history_id": "h-1", "categories": ["政策与规划"]},
        snapshot=AnalysisSnapshot(context={}), artifacts={}, question="test",
    ))

    assert result.status == "success"
    assert result.result["coverage_status"] == "usable_sources_found"
    assert len(requests) == 1
    assert result.result["category_coverage"][0]["usable_source_count"] == 1
    source = result.result["items"][0]
    assert source["publisher"] == "示例市人民政府"
    assert source["publication_date"] == "2026-01-02"
    assert source["access_date"] == "2026-07-26"
    assert source["query"]
    assert source["research_category"] == "政策与规划"
    assert source["original_excerpt"] == "推进存量空间活化利用。"
    assert source["applicable_scope"]
    assert source["inference_boundary"]
    assert source["search_attempt"]["round"] == 1


def test_public_web_page_without_parsed_evidence_retries(monkeypatch):
    requests = []

    async def fake_preview(request):
        requests.append(request)
        return _Response([{"url": "https://example.gov.cn/404", "parse_status": "parse_failed", "web_evidence_nodes": []}])

    monkeypatch.setattr(public_web_tools, "preview_ppt_web_source", fake_preview)
    result = asyncio.run(public_web_tools.search_public_web(
        arguments={"history_id": "h-1", "categories": ["公共服务"]},
        snapshot=AnalysisSnapshot(context={}), artifacts={}, question="test",
    ))

    assert result.status == "success"
    assert len(requests) == 3
    assert result.result["coverage_status"] == "searched_no_usable_source"


def test_public_web_parsed_page_without_body_still_retries(monkeypatch):
    requests = []

    async def fake_preview(request):
        requests.append(request)
        return _Response([{"url": "https://example.gov.cn/empty", "parse_status": "parsed", "web_evidence_nodes": []}])

    monkeypatch.setattr(public_web_tools, "preview_ppt_web_source", fake_preview)
    result = asyncio.run(public_web_tools.search_public_web(
        arguments={"history_id": "h-1", "categories": ["统计"]},
        snapshot=AnalysisSnapshot(context={}), artifacts={}, question="test",
    ))

    assert result.status == "success"
    assert len(requests) == 3
    assert result.result["coverage_status"] == "searched_no_usable_source"


def test_public_web_search_snippet_on_parse_failure_is_not_source_body(monkeypatch):
    requests = []

    async def fake_preview(request):
        requests.append(request)
        return _Response([{
            "url": "https://example.gov.cn/unreadable",
            "parse_status": "parse_failed",
            "summary": "搜索结果摘要，不是已打开的原文。",
            "web_evidence_nodes": [{"summary": "搜索摘要节点"}],
        }])

    monkeypatch.setattr(public_web_tools, "preview_ppt_web_source", fake_preview)
    result = asyncio.run(public_web_tools.search_public_web(
        arguments={"history_id": "h-1", "categories": ["统计"]},
        snapshot=AnalysisSnapshot(context={}), artifacts={}, question="test",
    ))

    assert len(requests) == 3
    assert result.result["coverage_status"] == "searched_no_usable_source"


def test_public_web_service_failure_is_distinct_from_no_results(monkeypatch):
    async def fake_preview(_request):
        raise RuntimeError("search backend unavailable")

    monkeypatch.setattr(public_web_tools, "preview_ppt_web_source", fake_preview)
    result = asyncio.run(public_web_tools.search_public_web(
        arguments={"history_id": "h-1", "categories": ["统计"]},
        snapshot=AnalysisSnapshot(context={}), artifacts={}, question="test",
    ))

    assert result.status == "failed"
    assert result.result["coverage_status"] == "failed"
    assert result.result["items"] == []
    assert result.result["evidence_refs"] == []
    assert result.result["attempts"] == []


def test_public_web_defaults_to_seven_required_research_categories(monkeypatch):
    requests = []

    async def fake_preview(request):
        requests.append(request)
        return _Response([{
            "url": f"https://example.gov.cn/{len(requests)}",
            "parse_status": "parsed",
            "web_evidence_nodes": [{"id": "n1", "content": "公开来源正文摘录"}],
        }])

    monkeypatch.setattr(public_web_tools, "preview_ppt_web_source", fake_preview)
    result = asyncio.run(public_web_tools.search_public_web(
        arguments={"history_id": "h-1"},
        snapshot=AnalysisSnapshot(context={}), artifacts={}, question="test",
    ))

    assert len(requests) == 7
    assert [item["category"] for item in result.result["category_coverage"]] == public_web_tools.DEFAULT_CATEGORIES
    assert all(item["research_category"] in public_web_tools.DEFAULT_CATEGORIES for item in result.result["items"])
    assert all(item["search_attempt"]["round"] == 1 for item in result.result["items"])
    assert all(item["inference_limit"] for item in result.result["items"])
