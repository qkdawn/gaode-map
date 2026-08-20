from __future__ import annotations

import json
import mimetypes
import os
import re
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping

import httpx

from core.config import settings

from .schemas import SpatialStrategyReportDeliveryRequest, SpatialStrategyReportFinalizeRequest
from .docx_export import write_markdown_docx


SOURCE_TYPE_LABELS = {
    "project_data": "项目数据",
    "project_data_record": "项目数据",
    "project_document": "项目材料",
    "project_computed_result": "空间数据",
    "knowledge_base": "公开资料",
}

INTERNAL_TERM_PATTERNS = (
    re.compile(r"step[_-]?\d{1,2}", re.IGNORECASE),
    re.compile(r"decision_state|quality_gate|evidence_index", re.IGNORECASE),
    re.compile(r"\bn8n\b", re.IGNORECASE),
    re.compile(r"(?:node|节点)[ _-]?(?:id|编号)", re.IGNORECASE),
    re.compile(r"(?:run|workflow|response)[ _-]?id", re.IGNORECASE),
    re.compile(r"\b(?:queued|running|completed|failed|cancelled|revision_required)\b", re.IGNORECASE),
    re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b", re.IGNORECASE),
    re.compile(r"(?:project|result|document):[a-z0-9._:-]{6,}", re.IGNORECASE),
    re.compile(r"\bE\d{3,}\b", re.IGNORECASE),
    re.compile(r"(?:page|block|chunk)[ _:-]?\d+", re.IGNORECASE),
    re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b", re.IGNORECASE),
    re.compile(r"\bphase\s*\d+\b", re.IGNORECASE),
)

def _text(value: Any) -> str:
    return str(value or "").strip()


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _project_name(project_context: Mapping[str, Any], project_question: str = "") -> str:
    project = _mapping(project_context.get("project"))
    for key in ("project_name", "name", "title"):
        candidate = _text(project.get(key))
        if candidate and not re.search(r"\bPOIs?\b|\d+\s*min\b|\d{2,3}\.\d+\s*[,，]\s*\d{1,2}\.\d+", candidate, re.IGNORECASE):
            return candidate
    question_match = re.search(r"(?:完成|分析|针对)?([^，。；]{2,60}?城市更新项目)", _text(project_question))
    if question_match:
        return question_match.group(1).lstrip("基于围绕针对")
    document_names = []
    for document in _list(project_context.get("documents")):
        title = re.sub(r"\.(?:docx?|pdf)$", "", _text(_mapping(document).get("title")), flags=re.IGNORECASE)
        title = re.sub(r"^(?:基于|关于)", "", title)
        match = re.search(r"([^，。；]{2,60}?城市更新项目)", title)
        if match:
            document_names.append(match.group(1))
    if document_names:
        return min(document_names, key=len)
    return "项目"


def _citation_id(value: Any, *, fallback: str = "") -> str:
    item = _mapping(value)
    if isinstance(value, Mapping):
        for key in ("citation_id", "chunk_id", "chunk_key", "document_id", "source_locator"):
            candidate = _text(item.get(key))
            if candidate:
                return candidate
        return _text(fallback)
    return _text(value)


def _citation_entries(steps: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Collect citations selected by completed decision analyses."""
    entries: dict[str, dict[str, Any]] = {}

    def add(value: Any, *, fallback: str = "") -> None:
        item = _mapping(value)
        citation_id = _citation_id(item or value, fallback=fallback)
        if not citation_id:
            return
        if item:
            item = {**item, "citation_id": citation_id}
        else:
            item = {"citation_id": citation_id}
        current = entries.get(citation_id)
        if current is None:
            entries[citation_id] = item
        else:
            entries[citation_id] = {**item, **current}

    def add_many(value: Any, *, fallback: str = "") -> None:
        for item in _list(value):
            add(item, fallback=fallback)

    for step in steps.values():
        output = _mapping(step)
        add_many(output.get("citations"))

    return list(entries.values())


def _render_section(*, index: int, section: Mapping[str, Any]) -> list[str]:
    title = _text(section.get("title")) or f"分析判断 {index}"
    content = _text(section.get("content"))
    return [f"## {index}. {title}", "", content, ""]


def _validate_reader_text(value: Any, *, field: str, minimum_length: int = 1) -> str:
    text = _text(value)
    if len(text) < minimum_length:
        raise ValueError(f"{field}_missing")
    if any(pattern.search(text) for pattern in INTERNAL_TERM_PATTERNS):
        raise ValueError(f"{field}_contains_internal_terms")
    return text


def _report_visual_assets(value: Any) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    for raw_asset in _list(value):
        asset = _mapping(raw_asset)
        kind = _text(asset.get("kind"))
        title = _text(asset.get("title"))
        if kind not in {"image", "table"} or not title:
            continue
        if kind == "image" and not _text(asset.get("relative_path")):
            continue
        if kind == "table" and not _text(asset.get("markdown")):
            continue
        assets.append(asset)
    return assets


def build_spatial_strategy_report(request: SpatialStrategyReportFinalizeRequest) -> dict[str, Any]:
    state = request.decision_state
    steps = _mapping(state.get("steps"))
    sections = [
        _mapping(item)
        for item in _list(state.get("report_sections"))
        if isinstance(item, Mapping) and _text(item.get("content"))
    ]
    sections.sort(key=lambda item: (int(item.get("section_order", 0) or 0), _text(item.get("section_id"))))
    if not sections:
        raise ValueError("report_requires_completed_sections")
    for index, section in enumerate(sections, 1):
        _validate_reader_text(section.get("content"), field=f"report_section_{index}", minimum_length=1)
    editorial_narrative = _validate_reader_text(
        request.editorial_narrative,
        field="editorial_narrative",
        minimum_length=1,
    )

    citation_entries = _citation_entries(steps)
    citations: list[dict[str, Any]] = []
    for index, citation in enumerate(citation_entries, 1):
        citation_id = _citation_id(citation)
        label = f"E{index:03d}"
        citations.append({"label": label, "citation_id": citation_id, **citation})

    project_name = _project_name(request.project_context, request.project_question)
    title = f"{project_name}空间策略与行动方案"
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    lines = [
        f"# {title}", "", f"分析问题：{request.project_question}", "",
        "## 总判断", "", editorial_narrative, "",
    ]

    visual_assets = _report_visual_assets(request.visual_assets)
    if visual_assets:
        lines.extend(["## 项目数据图件", ""])
        for asset in visual_assets:
            caption = _text(asset.get("caption")) or _text(_mapping(asset.get("design")).get("caption"))
            if asset["kind"] == "image":
                lines.extend([f"### {_text(asset['title'])}", "", f"![{_text(asset['title'])}]({_text(asset['relative_path'])})", ""])
            else:
                lines.extend([f"### {_text(asset['title'])}", "", _text(asset["markdown"]), ""])
            if caption:
                lines.extend([f"图注：{caption}", ""])

    for index, section in enumerate(sections, 1):
        lines.extend(_render_section(index=index, section=section))

    markdown = "\n".join(lines).rstrip() + "\n"
    return {
        "run_id": str(request.run_id),
        "history_id": request.history_id,
        "title": title,
        "generated_at": generated_at,
        "markdown": markdown,
        "citations": citations,
        "summary": editorial_narrative,
        "visual_assets": visual_assets,
    }


class SpatialStrategyReportStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or Path(settings.spatial_strategy_report_dir)).resolve()

    def write(self, report: Mapping[str, Any]) -> Path:
        run_id = _text(report.get("run_id"))
        if not re.fullmatch(r"[0-9a-f-]{36}", run_id, re.IGNORECASE):
            raise ValueError("report_run_id_invalid")
        directory = self.root / run_id
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / "spatial-strategy-report.md"
        temporary = target.with_suffix(".md.tmp")
        temporary.write_text(_text(report.get("markdown")) + "\n", encoding="utf-8", newline="\n")
        os.replace(temporary, target)
        return target

    def write_docx(self, markdown_path: Path, *, title: str = "") -> Path:
        target = markdown_path.with_suffix(".docx")
        temporary = target.with_suffix(".docx.tmp")
        write_markdown_docx(markdown_path, temporary, title=title)
        os.replace(temporary, target)
        return target

    def read_delivery(self, run_id: str) -> dict[str, Any] | None:
        path = self.root / run_id / "feishu-delivery.json"
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return payload if isinstance(payload, dict) and payload.get("file_message_id") else None

    def write_delivery(self, run_id: str, delivery: Mapping[str, Any]) -> None:
        directory = self.root / run_id
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / "feishu-delivery.json"
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(delivery, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        os.replace(temporary, target)


@dataclass(frozen=True)
class FeishuConfig:
    app_id: str
    app_secret: str
    chat_id: str
    api_root: str

    @classmethod
    def from_settings(cls) -> "FeishuConfig":
        values = {
            "FEISHU_APP_ID": _text(settings.feishu_app_id),
            "FEISHU_APP_SECRET": _text(settings.feishu_app_secret),
            "FEISHU_CHAT_ID": _text(settings.feishu_chat_id),
        }
        missing = [key for key, value in values.items() if not value]
        if missing:
            raise RuntimeError("feishu_not_configured:" + ",".join(missing))
        return cls(
            app_id=values["FEISHU_APP_ID"],
            app_secret=values["FEISHU_APP_SECRET"],
            chat_id=values["FEISHU_CHAT_ID"],
            api_root=_text(settings.feishu_api_root).rstrip("/"),
        )


class FeishuReportSender:
    def __init__(self, config: FeishuConfig, *, client: httpx.AsyncClient) -> None:
        self.config = config
        self.client = client
        self._token = ""

    async def deliver(
        self,
        *,
        report: Mapping[str, Any],
        markdown_path: Path,
        document_path: Path | None = None,
        visual_paths: list[Path] | None = None,
    ) -> dict[str, Any]:
        self._token = await self._tenant_access_token()
        summary_message_id = await self._send_message("text", {"text": self._summary(report)})
        attachment = document_path or markdown_path
        file_key = await self._upload_file(attachment)
        file_message_id = await self._send_message("file", {"file_key": file_key})
        visual_message_ids = []
        for path in visual_paths or []:
            visual_message_ids.append(await self._send_message("file", {"file_key": await self._upload_file(path)}))
        return {
            "provider": "feishu",
            "chat_id": self.config.chat_id,
            "summary_message_id": summary_message_id,
            "file_message_id": file_message_id,
            "file_name": attachment.name,
            "visual_message_ids": visual_message_ids,
            "delivered_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }

    async def _tenant_access_token(self) -> str:
        response = await self.client.post(
            f"{self.config.api_root}/auth/v3/tenant_access_token/internal",
            json={"app_id": self.config.app_id, "app_secret": self.config.app_secret},
        )
        payload = self._payload(response, "feishu_authentication")
        token = _text(payload.get("tenant_access_token"))
        if not token:
            raise RuntimeError("feishu_authentication_returned_no_token")
        return token

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    async def _upload_file(self, path: Path) -> str:
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        with path.open("rb") as source:
            response = await self.client.post(
                f"{self.config.api_root}/im/v1/files",
                headers=self._headers,
                data={"file_type": "stream", "file_name": path.name},
                files={"file": (path.name, source, media_type)},
            )
        payload = self._payload(response, "feishu_file_upload")
        file_key = _text(_mapping(payload.get("data")).get("file_key"))
        if not file_key:
            raise RuntimeError("feishu_file_upload_returned_no_file_key")
        return file_key

    async def _send_message(self, msg_type: str, content: Mapping[str, Any]) -> str:
        response = await self.client.post(
            f"{self.config.api_root}/im/v1/messages",
            params={"receive_id_type": "chat_id"},
            headers=self._headers,
            json={
                "receive_id": self.config.chat_id,
                "msg_type": msg_type,
                "content": json.dumps(content, ensure_ascii=False),
            },
        )
        payload = self._payload(response, f"feishu_send_{msg_type}")
        message_id = _text(_mapping(payload.get("data")).get("message_id"))
        if not message_id:
            raise RuntimeError(f"feishu_send_{msg_type}_returned_no_message_id")
        return message_id

    @staticmethod
    def _payload(response: httpx.Response, operation: str) -> dict[str, Any]:
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("code", 0) != 0:
            raise RuntimeError(
                f"{operation}_failed:code={payload.get('code') if isinstance(payload, dict) else 'invalid'}:"
                f"message={payload.get('msg', 'invalid_response') if isinstance(payload, dict) else 'invalid_response'}"
            )
        return payload

    @staticmethod
    def _summary(report: Mapping[str, Any]) -> str:
        summary = re.sub(r"\s+", " ", _text(report.get("summary")))[:600]
        state = _mapping(report.get("decision_state"))
        sections = state.get("report_sections") if isinstance(state.get("report_sections"), list) else []
        total = len([item for item in sections if isinstance(item, Mapping) and _text(item.get("content"))])
        return "\n".join(
            [
                _text(report.get("title")) or "空间策略与行动方案",
                f"状态：{total} 个报告部分完成",
                f"核心结论：{summary or '详见完整报告'}",
                "完整 Word 报告见随后发送的文件。",
            ]
        )


async def finalize_spatial_strategy_report(
    request: SpatialStrategyReportFinalizeRequest,
    *,
    store: SpatialStrategyReportStore | None = None,
) -> dict[str, Any]:
    report_store = store or SpatialStrategyReportStore()
    report = build_spatial_strategy_report(request)
    return await deliver_spatial_strategy_report(
        SpatialStrategyReportDeliveryRequest(
            run_id=request.run_id,
            title=report["title"],
            summary=report["summary"],
            markdown=report["markdown"],
            citations=report["citations"],
            decision_state=request.decision_state,
            visual_assets=report["visual_assets"],
        ),
        store=report_store,
    )


async def compose_spatial_strategy_report(
    request: SpatialStrategyReportFinalizeRequest,
    *,
    store: SpatialStrategyReportStore | None = None,
) -> dict[str, Any]:
    report_store = store or SpatialStrategyReportStore()
    report = build_spatial_strategy_report(request)
    markdown_path = report_store.write(report)
    document_path = report_store.write_docx(markdown_path, title=_text(report.get("title")))
    artifact = {
        "kind": "docx_report",
        "filename": document_path.name,
        "path": str(document_path),
        "media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "sha256": sha256(document_path.read_bytes()).hexdigest(),
        "markdown_filename": markdown_path.name,
        "markdown_path": str(markdown_path),
        "markdown_sha256": sha256(markdown_path.read_bytes()).hexdigest(),
        "visual_assets": report.get("visual_assets", []),
    }
    return {**report, "status": "draft", "asset_manifest": artifact, "decision_state": request.decision_state}


def _visual_paths(report_store: SpatialStrategyReportStore, report: Mapping[str, Any]) -> list[Path]:
    run_id = _text(report.get("run_id"))
    directory = (report_store.root / run_id).resolve()
    paths: list[Path] = []
    for asset in _report_visual_assets(report.get("visual_assets")):
        if asset["kind"] != "image":
            continue
        path = Path(_text(asset.get("path"))).resolve()
        if path.is_file() and path.is_relative_to(directory):
            paths.append(path)
    return paths


async def deliver_spatial_strategy_report(
    request: SpatialStrategyReportDeliveryRequest,
    *,
    store: SpatialStrategyReportStore | None = None,
) -> dict[str, Any]:
    report_store = store or SpatialStrategyReportStore()
    report = request.model_dump(mode="json")
    markdown_path = report_store.write(report)
    document_path = report_store.write_docx(markdown_path, title=_text(report.get("title")))
    visual_paths = _visual_paths(report_store, report)
    delivery = report_store.read_delivery(str(request.run_id))
    if delivery is None:
        async with httpx.AsyncClient(timeout=httpx.Timeout(settings.feishu_timeout_s)) as client:
            sender = FeishuReportSender(FeishuConfig.from_settings(), client=client)
            delivery = await sender.deliver(
                report=report,
                markdown_path=markdown_path,
                document_path=document_path,
                visual_paths=visual_paths,
            )
        report_store.write_delivery(str(request.run_id), delivery)

    artifact = {
        "kind": "docx_report",
        "filename": document_path.name,
        "path": str(document_path),
        "media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "sha256": sha256(document_path.read_bytes()).hexdigest(),
        "markdown_filename": markdown_path.name,
        "visual_assets": report.get("visual_assets", []),
        "delivery": delivery,
    }
    return {**report, "status": "ready", "asset_manifest": artifact, "delivery": delivery}
