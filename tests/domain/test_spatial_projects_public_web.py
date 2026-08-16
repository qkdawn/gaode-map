import asyncio

from modules.spatial_projects import public_web


def test_anysearch_timeout_setting_is_interpreted_as_milliseconds(monkeypatch):
    monkeypatch.setattr(public_web.settings, "anysearch_timeout_ms", 12000)

    assert public_web._timeout_seconds() == 12.0


def test_anysearch_page_fetch_keeps_only_verified_full_text(monkeypatch):
    async def fake_call(_tool_name, arguments):
        if "blocked" in arguments["url"]:
            return ["extract_target_blocked\nTarget is blocked by Extract policy."]
        return ["# 官方页面\n\n这是可用于复核的网页正文。"]

    monkeypatch.setattr(public_web, "_call_anysearch", fake_call)
    result = asyncio.run(public_web.fetch_public_web_page(
        ["https://example.gov.cn/verified", "https://example.gov.cn/blocked"],
        "anysearch",
        5000,
    ))

    assert result["status"] == "partial"
    assert result["urls"] == ["https://example.gov.cn/verified"]
    assert result["content"] == ["# 官方页面\n\n这是可用于复核的网页正文。"]
    assert result["failures"] == [{
        "url": "https://example.gov.cn/blocked",
        "error": "public_web_fulltext_unavailable",
    }]


def test_anysearch_page_fetch_reports_unavailable_when_every_page_is_blocked(monkeypatch):
    async def fake_call(_tool_name, _arguments):
        return ["extract_fetch_failed"]

    monkeypatch.setattr(public_web, "_call_anysearch", fake_call)
    result = asyncio.run(public_web.fetch_public_web_page(
        ["https://example.gov.cn/blocked"],
        "anysearch",
        5000,
    ))

    assert result["status"] == "unavailable"
    assert result["content"] == []
    assert result["error"] == "public_web_fulltext_unavailable"
    assert result["retryable"] is True
