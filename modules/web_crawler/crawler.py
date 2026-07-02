from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List
from urllib.parse import urlparse


MAX_MARKDOWN_CHARS = 12000
MAX_SUMMARY_CHARS = 480
MAX_NODE_TEXT_CHARS = 900
MAX_NODES = 8
NOISE_PATTERNS = (
    r"javascript:",
    r"ALT\+\d+",
    r"导航区",
    r"视图区",
    r"交互区",
    r"服务区",
    r"列表区",
    r"正文区",
    r"开启显示",
    r"开启鼠标",
    r"开启辅助线",
    r"开启静音",
    r"开启指读",
    r"开启连读",
    r"黑底白字",
    r"点击切换至黑底白字",
    r"语速正常",
    r"切换语速",
    r"字号放大",
    r"文字放大",
)
NOISE_RE = re.compile("|".join(NOISE_PATTERNS), re.IGNORECASE)


class WebCrawlerUnavailable(RuntimeError):
    pass


@dataclass
class WebPageCrawlResult:
    url: str
    title: str = ""
    markdown: str = ""
    summary: str = ""
    status: str = "pending"
    error: str = ""
    nodes: List[Dict[str, Any]] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def is_noise_text(value: Any) -> bool:
    text = _clean_text(value)
    if not text:
        return True
    if NOISE_RE.search(text):
        return True
    bracket_count = text.count("[")
    if bracket_count >= 4 and "javascript" in text.lower():
        return True
    return False


def clean_visible_text(value: Any) -> str:
    text = str(value or "")
    if is_noise_text(text):
        return ""
    text = re.sub(r"\[[^\]]{0,60}\]\(javascript:[^)]+\)", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\[[^\]]*(?:导航区|视图区|交互区|服务区|列表区|正文区)[^\]]*\]", " ", text)
    text = _clean_text(text)
    return "" if is_noise_text(text) else text


def _is_noise_text(value: Any) -> bool:
    return is_noise_text(value)


def _strip_inline_noise(value: Any) -> str:
    return clean_visible_text(value)


def _clean_markdown(value: Any) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    lines = [line.rstrip() for line in text.splitlines()]
    cleaned: List[str] = []
    blank = False
    for line in lines:
        stripped = _strip_inline_noise(line)
        if not stripped:
            if not blank:
                cleaned.append("")
            blank = True
            continue
        cleaned.append(stripped)
        blank = False
    return "\n".join(cleaned).strip()


def _markdown_title(markdown: str, fallback: str = "") -> str:
    for line in markdown.splitlines():
        stripped = clean_visible_text(line.strip())
        if stripped.startswith("#"):
            title = clean_visible_text(stripped.lstrip("#").strip())
            if title:
                return title[:255]
    for line in markdown.splitlines():
        text = clean_visible_text(re.sub(r"[*_`>#-]+", " ", line))
        if len(text) >= 6:
            return text[:255]
    return clean_visible_text(fallback)[:255]


def _summary_from_markdown(markdown: str) -> str:
    paragraphs = [
        clean_visible_text(re.sub(r"^[#>*\-\d.、\s]+", "", part))
        for part in re.split(r"\n{2,}", markdown)
    ]
    paragraphs = [part for part in paragraphs if len(part) >= 20]
    if not paragraphs:
        fallback = clean_visible_text(markdown)
        paragraphs = [fallback] if fallback else []
    return _clean_text(" ".join(paragraphs[:2]))[:MAX_SUMMARY_CHARS]


def _node_title(text: str, index: int) -> str:
    for line in text.splitlines():
        stripped = clean_visible_text(line.strip().lstrip("#").strip())
        if stripped:
            return stripped[:80]
    return f"网页段落 {index}"


def _evidence_nodes(markdown: str) -> List[Dict[str, Any]]:
    parts = [
        part.strip()
        for part in re.split(r"\n(?=#{1,4}\s)|\n{2,}", markdown)
        if _clean_text(part)
    ]
    nodes: List[Dict[str, Any]] = []
    for index, part in enumerate(parts, start=1):
        text = clean_visible_text(re.sub(r"#{1,6}\s*", "", part))
        if len(text) < 20:
            continue
        nodes.append(
            {
                "node_id": f"web-node-{len(nodes) + 1}",
                "title": _node_title(part, len(nodes) + 1),
                "level": 1,
                "summary": text[:MAX_SUMMARY_CHARS],
                "text": text[:MAX_NODE_TEXT_CHARS],
                "ordinal": len(nodes) + 1,
            }
        )
        if len(nodes) >= MAX_NODES:
            break
    return nodes


def _markdown_from_result(result: Any) -> str:
    markdown = getattr(result, "markdown", "")
    if isinstance(markdown, str):
        return markdown
    if markdown is None:
        return ""
    for attr in ("fit_markdown", "raw_markdown", "markdown"):
        value = getattr(markdown, attr, "")
        if value:
            return str(value)
    return str(markdown or "")


async def crawl_web_page(url: str, *, timeout_ms: int = 20000) -> WebPageCrawlResult:
    normalized_url = str(url or "").strip()
    parsed = urlparse(normalized_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return WebPageCrawlResult(url=normalized_url, status="parse_failed", error="invalid_url")

    try:
        from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
    except Exception as exc:
        raise WebCrawlerUnavailable("crawl4ai_unavailable") from exc

    try:
        browser_config = BrowserConfig(
            headless=True,
            verbose=False,
            channel="chrome",
            chrome_channel="chrome",
        )
        run_config = CrawlerRunConfig(page_timeout=max(1000, int(timeout_ms or 20000)))
        async with AsyncWebCrawler(config=browser_config) as crawler:
            result = await crawler.arun(url=normalized_url, config=run_config)
    except TypeError:
        async with AsyncWebCrawler() as crawler:
            result = await asyncio.wait_for(crawler.arun(url=normalized_url), timeout=max(1, int(timeout_ms / 1000)))
    except Exception as exc:
        return WebPageCrawlResult(
            url=normalized_url,
            status="parse_failed",
            error=type(exc).__name__,
            meta={"crawler": "crawl4ai"},
        )

    success = bool(getattr(result, "success", True))
    markdown = _clean_markdown(_markdown_from_result(result))[:MAX_MARKDOWN_CHARS]
    parsed_title = clean_visible_text(getattr(result, "title", ""))
    title = parsed_title or _markdown_title(markdown, normalized_url)
    if not success or not markdown:
        error = _clean_text(getattr(result, "error_message", "")) or ("low_quality_markdown" if not markdown else "crawl_failed")
        return WebPageCrawlResult(
            url=normalized_url,
            title=title,
            markdown=markdown,
            status="parse_failed",
            error=error[:240],
            meta={"crawler": "crawl4ai"},
        )
    nodes = _evidence_nodes(markdown)
    return WebPageCrawlResult(
        url=normalized_url,
        title=title,
        markdown=markdown,
        summary=_summary_from_markdown(markdown),
        status="parsed" if nodes else "parse_failed",
        error="" if nodes else "no_evidence_nodes",
        nodes=nodes,
        meta={"crawler": "crawl4ai", "markdown_chars": len(markdown)},
    )
