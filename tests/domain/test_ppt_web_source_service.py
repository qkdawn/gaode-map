import asyncio

from modules.ppt_planning.schemas import PptWebSourceCommitRequest, PptWebSourceLocationDefaultRequest, PptWebSourceSearchRequest
from modules.ppt_web_source import service
from modules.web_crawler import WebPageCrawlResult
from modules.web_crawler import crawler


def test_web_source_location_default_uses_amap_regeo_names(monkeypatch):
    monkeypatch.setattr(
        service.history_repo,
        "get_detail",
        lambda area_id, include_pois=False: {
            "id": area_id,
            "params": {"center": [112.9, 28.2]},
        },
    )
    monkeypatch.setattr(service, "wgs84_to_gcj02", lambda lng, lat: (lng, lat))
    monkeypatch.setattr(
        service,
        "reverse_geocode",
        lambda lng, lat: {
            "addressComponent": {
                "province": "湖南省",
                "city": "长沙市",
                "district": "岳麓区",
                "township": "梅溪湖街道",
                "adcode": "430104",
            },
            "formatted_address": "湖南省长沙市岳麓区梅溪湖街道",
        },
    )

    result = service.build_web_source_location_default(PptWebSourceLocationDefaultRequest(area_id="area-1"))

    assert result.region_name == "岳麓区 梅溪湖街道"
    assert result.administrative_area == "湖南省 长沙市 岳麓区"
    assert result.confidence == "high"


def test_web_source_location_default_fallback_never_uses_coordinates(monkeypatch):
    monkeypatch.setattr(
        service.history_repo,
        "get_detail",
        lambda area_id, include_pois=False: {
            "id": area_id,
            "params": {"center": [112.9, 28.2]},
        },
    )
    monkeypatch.setattr(service, "wgs84_to_gcj02", lambda lng, lat: (lng, lat))

    def fail_regeo(_lng, _lat):
        raise ValueError("regeo failed")

    monkeypatch.setattr(service, "reverse_geocode", fail_regeo)

    result = service.build_web_source_location_default(PptWebSourceLocationDefaultRequest(area_id="area-1"))

    assert result.region_name == "当前分析区域"
    assert "112.9" not in result.region_name
    assert result.confidence == "fallback"


def test_web_source_preview_sanitizes_coordinate_region_without_persisting(monkeypatch):
    captured = {}

    async def fake_fetch(term, source):
        captured.setdefault("terms", []).append(term)
        return {
            "title": f"{term}资料",
            "url": f"https://{source['domain']}/demo",
            "source_name": source["name"],
            "source_domain": source["domain"],
            "published_at": "unknown",
            "accessed_at": "2026-06-23",
            "summary": f"{term}摘要",
            "supported_claims": [term],
            "category": "区域概况",
            "confidence": "medium",
        }

    monkeypatch.setattr(service, "_fetch_whitelisted_result", fake_fetch)
    monkeypatch.setattr(service.analysis_artifact_repo, "upsert", lambda **kwargs: captured.setdefault("upsert", kwargs))

    result = asyncio.run(
        service.preview_ppt_web_source(
            PptWebSourceSearchRequest(
                area_id="area-1",
                region_name="112.9,28.2",
                administrative_area="湖南省 长沙市 岳麓区",
                topic="城市更新",
                categories=["区域概况"],
            )
        )
    )

    assert result.source.source_kind == "web"
    assert result.source.meta["sourceKind"] == "web"
    assert result.source.meta["web_source"]["region_name"] == "当前分析区域"
    assert all("112.9,28.2" not in term for term in captured["terms"])
    assert "upsert" not in captured
    assert result.source.meta["aiPayload"]["included"] == ["evidence"]
    assert "sourceId" not in result.source.meta["aiPayload"]
    assert "sourceKind" not in result.source.meta["aiPayload"]
    assert "evidenceNodes" not in result.source.meta["aiPayload"]


def test_web_source_fetches_and_ranks_searxng_candidates(monkeypatch):
    captured = {}

    class FakeResponse:
        def json(self):
            return {
                "results": [
                    {
                        "title": "普通网页",
                        "url": "https://example.com/noise",
                        "content": "长沙市资料",
                    },
                    {
                        "title": "岳麓区概况",
                        "url": "http://www.yuelu.gov.cn/zjxq/xqsj/demo.html",
                        "content": "岳麓区 桔子洲 街道 概况",
                    },
                ]
            }

        def raise_for_status(self):
            return None

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, params=None):
            captured["url"] = url
            captured["params"] = params
            return FakeResponse()

    monkeypatch.setattr(service.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(service.settings, "searxng_base_url", "http://searxng.local")

    result = asyncio.run(
        service._fetch_whitelisted_result(
            "岳麓区 桔子洲 区域概况",
            {"name": "区县政府公开信息", "domain": "yuelu.gov.cn", "site": "yuelu.gov.cn", "confidence": "high"},
        )
    )

    assert result["url"] == "http://www.yuelu.gov.cn/zjxq/xqsj/demo.html"
    assert result["title"] == "岳麓区概况"
    assert captured["url"] == "http://searxng.local/search"
    assert "site:yuelu.gov.cn" in captured["params"]["q"]


def test_web_source_preview_backfills_open_search_when_trusted_results_are_sparse(monkeypatch):
    async def fake_fetch(term, source):
        return {
            "title": f"{term}可信资料",
            "url": "",
            "source_name": source["name"],
            "source_domain": source["domain"],
            "summary": f"{term}可信摘要",
            "confidence": "medium",
        }

    async def fake_open(term, limit=4, source_modes=None):
        return [
            {
                "title": f"{term}开放资料",
                "url": "https://news.example.com/demo",
                "source_name": "开放网页搜索",
                "source_domain": "news.example.com",
                "summary": f"{term}开放摘要",
                "confidence": "low",
                "search_strategy": "open_web",
            }
        ][:limit]

    async def fake_crawl(url, timeout_ms=20000):
        return WebPageCrawlResult(url=url, title="网页", status="parse_failed", error="timeout")

    monkeypatch.setattr(service, "_fetch_whitelisted_result", fake_fetch)
    monkeypatch.setattr(service, "_fetch_open_search_results", fake_open)
    monkeypatch.setattr(service, "crawl_web_page", fake_crawl)

    result = asyncio.run(
        service.preview_ppt_web_source(
            PptWebSourceSearchRequest(area_id="area-1", region_name="岳麓区", topic="文旅", categories=["区域概况"], limit=2)
        )
    )

    assert any(item.get("search_strategy") == "open_web" for item in result.items)
    assert any("开放网页搜索结果" in warning for warning in result.warnings)
    assert result.source.meta["web_source"]["search_strategy"] == "tiered_sources_trusted_market_optional_community"


def test_web_source_preview_returns_multiple_searxng_results_from_one_site(monkeypatch):
    class FakeResponse:
        def json(self):
            return {
                "results": [
                    {
                        "title": "岳麓区项目一",
                        "url": "https://changsha.gov.cn/demo-1.html",
                        "content": "岳麓区项目一摘要",
                    },
                    {
                        "title": "岳麓区项目二",
                        "url": "https://changsha.gov.cn/demo-2.html",
                        "content": "岳麓区项目二摘要",
                    },
                    {
                        "title": "岳麓区项目三",
                        "url": "https://changsha.gov.cn/demo-3.html",
                        "content": "岳麓区项目三摘要",
                    },
                ]
            }

        def raise_for_status(self):
            return None

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, params=None):
            return FakeResponse()

    async def fake_crawl(url, timeout_ms=20000):
        return WebPageCrawlResult(
            url=url,
            title="岳麓区项目",
            markdown="# 岳麓区项目\n\n岳麓区项目正文资料，可作为区域概况证据。",
            summary="岳麓区项目正文资料，可作为区域概况证据。",
            status="parsed",
            nodes=[{"node_id": "web-node-1", "title": "岳麓区项目", "summary": "岳麓区项目正文资料，可作为区域概况证据。", "text": "岳麓区项目正文资料，可作为区域概况证据。", "ordinal": 1}],
        )

    monkeypatch.setattr(service.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(service, "crawl_web_page", fake_crawl)
    monkeypatch.setattr(service.settings, "searxng_base_url", "http://searxng.local")

    result = asyncio.run(
        service.preview_ppt_web_source(
            PptWebSourceSearchRequest(area_id="area-1", region_name="岳麓区", topic="文旅", categories=["区域概况"], limit=3)
        )
    )

    assert len(result.items) == 3
    assert [item["url"] for item in result.items] == [
        "https://changsha.gov.cn/demo-1.html",
        "https://changsha.gov.cn/demo-2.html",
        "https://changsha.gov.cn/demo-3.html",
    ]


def test_web_source_preview_prioritizes_58_for_rental_category(monkeypatch):
    captured = {}

    async def fake_fetch(term, source):
        captured.setdefault("sources", []).append(source["domain"])
        return {
            "title": "岳麓区租房_58同城",
            "url": "https://cs.58.com/yuelu/zufang/",
            "source_name": source["name"],
            "source_domain": source["domain"],
            "summary": f"{term} 58同城租房线索",
            "confidence": source["confidence"],
            "search_strategy": "trusted_site",
        }

    async def fake_crawl(url, timeout_ms=20000):
        return WebPageCrawlResult(
            url=url,
            title="岳麓区租房",
            markdown="# 岳麓区租房\n\n岳麓区附近有住宅、公寓等出租房源，可用于租金水平核验。",
            summary="岳麓区附近有住宅、公寓等出租房源，可用于租金水平核验。",
            status="parsed",
            nodes=[{"node_id": "web-node-1", "title": "岳麓区租房", "summary": "岳麓区附近有住宅、公寓等出租房源，可用于租金水平核验。", "text": "岳麓区附近有住宅、公寓等出租房源，可用于租金水平核验。", "ordinal": 1}],
        )

    monkeypatch.setattr(service, "_fetch_whitelisted_result", fake_fetch)
    monkeypatch.setattr(service, "crawl_web_page", fake_crawl)

    result = asyncio.run(
        service.preview_ppt_web_source(
            PptWebSourceSearchRequest(area_id="area-1", region_name="岳麓区 梅溪湖街道", topic="商业研判", categories=["周边房租"])
        )
    )

    assert captured["sources"][0] == "58.com"
    assert result.items[0]["source_name"] == "58同城租房"
    assert result.items[0]["source_domain"] == "58.com"


def test_web_source_preview_uses_only_rental_market_sources_for_rent(monkeypatch):
    captured = {}

    async def fake_fetch(term, source):
        captured.setdefault("sources", []).append(source["domain"])
        return {
            "title": f"{term}待核验线索",
            "url": "",
            "source_name": source["name"],
            "source_domain": source["domain"],
            "summary": "",
            "confidence": source["confidence"],
        }

    async def fake_open(term, limit=4, source_modes=None):
        return []

    monkeypatch.setattr(service, "_fetch_whitelisted_result", fake_fetch)
    monkeypatch.setattr(service, "_fetch_open_search_results", fake_open)

    result = asyncio.run(
        service.preview_ppt_web_source(
            PptWebSourceSearchRequest(area_id="area-1", region_name="岳麓区 梅溪湖街道", topic="商业研判", categories=["周边房租"], limit=1)
        )
    )

    assert captured["sources"] == ["58.com"]
    assert result.items[0]["source_name"] == "58同城租房"
    assert result.items[0]["source_domain"] == "58.com"


def test_web_source_preview_does_not_backfill_government_pages_for_rent(monkeypatch):
    async def fake_fetch(term, source):
        return {
            "title": f"{term}待核验线索",
            "url": "",
            "source_name": source["name"],
            "source_domain": source["domain"],
            "source_tier": source["source_tier"],
            "summary": "",
            "confidence": source["confidence"],
        }

    async def fake_open(term, limit=4, source_modes=None):
        return [
            {
                "title": "湖南政府网页",
                "url": "https://www.hunan.gov.cn/demo.html",
                "source_name": "开放网页搜索",
                "source_domain": "www.hunan.gov.cn",
                "source_tier": "trusted",
                "summary": "政府网页摘要",
                "confidence": "medium",
                "search_strategy": "open_web",
            }
        ]

    monkeypatch.setattr(service, "_fetch_whitelisted_result", fake_fetch)
    monkeypatch.setattr(service, "_fetch_open_search_results", fake_open)

    result = asyncio.run(
        service.preview_ppt_web_source(
            PptWebSourceSearchRequest(area_id="area-1", region_name="岳麓区 梅溪湖街道", topic="商业研判", categories=["周边房租"], limit=1)
        )
    )

    assert result.items[0]["source_domain"] == "58.com"
    assert result.items[0]["source_tier"] == "market"
    assert "hunan.gov.cn" not in str(result.items)


def test_web_source_open_search_filters_58_for_rental_terms(monkeypatch):
    captured = {}

    class FakeResponse:
        def json(self):
            return {
                "results": [
                    {
                        "title": "普通租房网页",
                        "url": "https://example.com/rent",
                        "content": "普通网页摘要",
                    },
                    {
                        "title": "岳麓区租房",
                        "url": "https://cs.58.com/yuelu/zufang/",
                        "content": "58同城岳麓区附近出租房源线索",
                    },
                ]
            }

        def raise_for_status(self):
            return None

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, params=None):
            captured["url"] = url
            captured["params"] = params
            return FakeResponse()

    monkeypatch.setattr(service.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(service.settings, "searxng_base_url", "http://searxng.local")

    result = asyncio.run(service._fetch_open_search_results("岳麓区 梅溪湖街道 周边房租", limit=1))

    assert result[0]["url"] == "https://cs.58.com/yuelu/zufang/"
    assert result[0]["source_name"] == "58同城租房"
    assert result[0]["source_domain"] == "cs.58.com"
    assert result[0]["search_strategy"] == "rental_market_open_web"


def test_web_source_open_search_skips_community_by_default(monkeypatch):
    class FakeResponse:
        def json(self):
            return {
                "results": [
                    {"title": "知乎讨论", "url": "https://www.zhihu.com/question/1", "content": "知乎讨论摘要"},
                    {"title": "普通网页", "url": "https://news.example.com/demo", "content": "普通网页摘要"},
                ]
            }

        def raise_for_status(self):
            return None

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, params=None):
            return FakeResponse()

    monkeypatch.setattr(service.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(service.settings, "searxng_base_url", "http://searxng.local")

    result = asyncio.run(service._fetch_open_search_results("岳麓区 文旅案例", limit=2))

    assert all("zhihu.com" not in item["url"] for item in result)


def test_web_source_open_search_allows_community_when_enabled(monkeypatch):
    class FakeResponse:
        def json(self):
            return {"results": [{"title": "知乎讨论", "url": "https://www.zhihu.com/question/1", "content": "知乎讨论摘要"}]}

        def raise_for_status(self):
            return None

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, params=None):
            return FakeResponse()

    monkeypatch.setattr(service.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(service.settings, "searxng_base_url", "http://searxng.local")

    result = asyncio.run(service._fetch_open_search_results("岳麓区 文旅案例", limit=1, source_modes=["trusted", "market", "community"]))

    assert result[0]["url"] == "https://www.zhihu.com/question/1"
    assert result[0]["source_tier"] == "community"
    assert result[0]["confidence"] == "low"


def test_web_source_preview_fails_readably_when_searxng_unavailable(monkeypatch):
    async def fake_search(*args, **kwargs):
        raise service.PptWebSourceSearchUnavailable("searxng_unavailable")

    monkeypatch.setattr(service, "_fetch_whitelisted_results", fake_search)

    try:
        asyncio.run(
            service.preview_ppt_web_source(
                PptWebSourceSearchRequest(area_id="area-1", region_name="岳麓区", topic="文旅", categories=["区域概况"])
            )
        )
    except service.PptWebSourceSearchUnavailable as exc:
        assert str(exc) == "searxng_unavailable"
    else:
        raise AssertionError("expected PptWebSourceSearchUnavailable")


def test_web_source_preview_uses_web_parse_without_persisting(monkeypatch):
    captured = {}

    async def fake_fetch(term, source):
        return {
            "title": "政策网页",
            "url": f"https://{source['domain']}/demo",
            "source_name": source["name"],
            "source_domain": source["domain"],
            "published_at": "unknown",
            "accessed_at": "2026-06-28",
            "summary": f"{term}摘要",
            "supported_claims": [term],
            "category": "政策背景",
            "confidence": "high",
        }

    async def fake_crawl(url, timeout_ms=20000):
        return WebPageCrawlResult(
            url=url,
            title="解析后的政策网页",
            markdown="# 政策\n\n这里是网页正文和政策段落。",
            summary="这里是网页正文和政策段落。",
            status="parsed",
            nodes=[{"node_id": "web-node-1", "title": "政策", "summary": "这里是网页正文和政策段落。", "text": "这里是网页正文和政策段落。", "ordinal": 1}],
        )

    monkeypatch.setattr(service, "_fetch_whitelisted_result", fake_fetch)
    monkeypatch.setattr(service, "crawl_web_page", fake_crawl)
    monkeypatch.setattr(service.analysis_artifact_repo, "upsert", lambda **kwargs: captured.setdefault("upsert", kwargs))

    result = asyncio.run(
        service.preview_ppt_web_source(
            PptWebSourceSearchRequest(
                area_id="area-1",
                region_name="岳麓区 桔子洲街道",
                topic="文旅",
                categories=["政策背景"],
            )
        )
    )

    assert "upsert" not in captured
    assert result.items[0]["parse_status"] == "parsed"
    assert result.items[0]["web_evidence_nodes"][0]["title"] == "政策"
    assert result.source.meta["aiPayload"]["evidence_nodes"][0]["metadata"]["parse_status"] == "parsed"
    assert result.source.meta["aiPayload"]["index_manifest"]["source_kind"] == "web"
    assert result.source.meta["aiPayload"]["index_manifest"]["native_index_kind"] == "webpage_index"
    assert result.source.meta["aiPayload"]["index_manifest"]["model_versions"]["crawler"] == "crawl4ai"
    assert "evidence" not in result.source.meta["aiPayload"]


def test_web_source_preview_direct_url_builds_web_source(monkeypatch):
    async def fake_crawl(url, timeout_ms=20000):
        return WebPageCrawlResult(
            url=url,
            title="单篇政策网页",
            markdown="# 单篇政策网页\n\n这里是直接输入 URL 后抓取到的政策正文段落。",
            summary="这里是直接输入 URL 后抓取到的政策正文段落。",
            status="parsed",
            nodes=[{
                "node_id": "web-node-1",
                "title": "单篇政策网页",
                "summary": "这里是直接输入 URL 后抓取到的政策正文段落。",
                "text": "这里是直接输入 URL 后抓取到的政策正文段落。",
                "ordinal": 1,
            }],
        )

    monkeypatch.setattr(service, "crawl_web_page", fake_crawl)

    result = asyncio.run(
        service.preview_ppt_web_source(
            PptWebSourceSearchRequest(
                area_id="area-1",
                topic="政策背景",
                urls=["https://www.gov.cn/demo.html"],
            )
        )
    )

    assert result.source.id.startswith("web:area-1:")
    assert result.source.type == "web"
    assert result.source.source_kind == "web"
    assert result.source.evidence_count == 1
    assert result.source.availability == "available"
    assert result.source.locator_summary == "https://www.gov.cn/demo.html"
    assert result.source.meta["web_source"]["input_mode"] == "direct_url"
    assert result.source.meta["web_source"]["urls"] == ["https://www.gov.cn/demo.html"]
    evidence_nodes = result.source.meta["aiPayload"]["evidence_nodes"]
    assert evidence_nodes[0]["source_type"] == "web"
    assert evidence_nodes[0]["metadata"]["url"] == "https://www.gov.cn/demo.html"
    assert evidence_nodes[0]["id"].startswith(result.source.id)
    assert result.source.meta["aiPayload"]["index_manifest"]["read_modes"] == ["node_id", "url"]
    assert "evidence" not in result.source.meta["aiPayload"]


def test_web_source_preview_keeps_failed_web_parse_as_warning(monkeypatch):
    async def fake_fetch(term, source):
        return {
            "title": "网页",
            "url": f"https://{source['domain']}/demo",
            "source_name": source["name"],
            "source_domain": source["domain"],
            "summary": f"{term}摘要",
            "confidence": "medium",
        }

    async def fake_crawl(url, timeout_ms=20000):
        return WebPageCrawlResult(url=url, title="网页", status="parse_failed", error="timeout")

    monkeypatch.setattr(service, "_fetch_whitelisted_result", fake_fetch)
    monkeypatch.setattr(service, "crawl_web_page", fake_crawl)

    result = asyncio.run(
        service.preview_ppt_web_source(
            PptWebSourceSearchRequest(area_id="area-1", region_name="岳麓区", topic="文旅", categories=["区域概况"])
        )
    )

    assert result.items[0]["parse_status"] == "parse_failed"
    assert result.items[0]["parse_error"] == "timeout"
    assert result.items[0]["web_evidence_nodes"][0]["title"] == "搜索结果摘要"
    assert any("网页正文解析失败" in warning for warning in result.warnings)


def test_web_source_cleaning_filters_accessibility_navigation_noise():
    markdown = """
    [导航区(1) ALT+1](javascript:; "导航区") [视图区(3) ALT+2](javascript:; "视图区")
    [开启辅助线](javascript:; "开启辅助线") [语速正常](javascript:; "语速正常")

    # 岳麓区统计公报

    2025年岳麓区围绕产业发展、文旅消费和城市更新推进重点项目建设。
    """

    cleaned = crawler._clean_markdown(markdown)
    nodes = crawler._evidence_nodes(cleaned)

    assert "javascript:" not in cleaned
    assert "导航区" not in cleaned
    assert "语速正常" not in cleaned
    assert "岳麓区统计公报" in cleaned
    assert nodes
    assert all("javascript:" not in node["summary"] for node in nodes)


def test_web_source_preview_filters_navigation_noise_from_parsed_fields(monkeypatch):
    async def fake_fetch(term, source):
        return {
            "title": "岳麓区文旅资料",
            "url": "http://www.yuelu.gov.cn/demo.html",
            "source_name": source["name"],
            "source_domain": source["domain"],
            "summary": "岳麓区文旅资料搜索摘要",
            "confidence": "high",
            "supported_claims": ["岳麓区文旅资料搜索摘要"],
        }

    async def fake_crawl(url, timeout_ms=20000):
        noise = '[导航区(1) ALT+1](javascript:; "导航区") [视图区(3) ALT+2](javascript:; "视图区") [开启辅助线](javascript:; "开启辅助线")'
        return WebPageCrawlResult(
            url=url,
            title="导航区(1)",
            markdown=noise,
            summary=noise,
            status="parsed",
            nodes=[{"node_id": "web-node-1", "title": "导航区(1)", "summary": noise, "text": noise, "ordinal": 1}],
        )

    monkeypatch.setattr(service, "_fetch_whitelisted_result", fake_fetch)
    monkeypatch.setattr(service, "crawl_web_page", fake_crawl)

    result = asyncio.run(
        service.preview_ppt_web_source(
            PptWebSourceSearchRequest(area_id="area-1", region_name="岳麓区", topic="文旅", categories=["区域概况"])
        )
    )

    item = result.items[0]
    serialized = str(item)
    assert item["title"] == "岳麓区文旅资料"
    assert item["parse_status"] == "parse_failed"
    assert item["parse_error"] == "low_quality_markdown"
    assert "导航区" not in serialized
    assert "javascript:" not in serialized


def test_web_source_commit_persists_preview(monkeypatch):
    upserts = []
    preview = service._build_web_source_response(
        "area-1",
        PptWebSourceSearchRequest(area_id="area-1", region_name="岳麓区", topic="文旅", categories=["区域概况"]),
        [{"title": "网页", "url": "https://gov.cn/demo", "summary": "摘要", "source_name": "政府网站", "source_domain": "gov.cn"}],
        [],
    )
    monkeypatch.setattr(service.analysis_artifact_repo, "upsert", lambda **kwargs: upserts.append(kwargs) or {"id": len(upserts), **kwargs})

    result = service.commit_ppt_web_source(PptWebSourceCommitRequest(area_id="area-1", preview=preview.model_dump(mode="json")))

    assert result.source.id.startswith("web:area-1:")
    assert result.source.source_kind == "web"
    assert result.source.evidence_count == 1
    assert result.source.availability == "available"
    assert result.source.locator_summary == "https://gov.cn/demo"
    evidence_nodes = result.source.meta["aiPayload"]["evidence_nodes"]
    assert evidence_nodes[0]["id"].startswith(result.source.id)
    assert evidence_nodes[0]["source_type"] == "web"
    assert "evidence" not in result.source.meta["aiPayload"]
    assert upserts[0]["artifact_type"] == service.PPT_WEB_SOURCE_ARTIFACT_TYPE
    manifest_upsert = next(item for item in upserts if item["artifact_type"] == "source_index_manifest")
    assert manifest_upsert["history_id"] == "area-1"
    assert manifest_upsert["params"] == {"source_id": result.source.id}
    assert manifest_upsert["payload"]["manifest"]["native_index_kind"] == "webpage_index"
