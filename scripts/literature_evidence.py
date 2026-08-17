"""Query the GraphRAG literature corpus through one evidence-oriented contract.

The application invokes this script with the isolated GraphRAG environment.
Input and output are single JSON objects on stdin/stdout.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import sys
import threading
import urllib.request
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT / "runtime" / "graphrag-public-knowledge"
DEFAULT_QUERY_TIMEOUT_SECONDS = 120
PAGE_LIMITATION = "页码根据 GraphRAG 文本单元在原始 PDF 解析文本中的位置估算，正式发布前应核对原始 PDF。"


class LiteratureRequestError(ValueError):
    pass


def _load_dotenv_value(name: str) -> str:
    value = os.getenv(name, "").strip()
    if value:
        return value
    env_path = ROOT / ".env"
    if not env_path.exists():
        return ""
    prefix = f"{name}="
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped.startswith(prefix):
            continue
        value = stripped[len(prefix) :].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        return value
    return ""


def _query_timeout_seconds() -> int:
    raw = os.getenv("GRAPHRAG_QUERY_TIMEOUT_SECONDS", str(DEFAULT_QUERY_TIMEOUT_SECONDS)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError("GRAPHRAG_QUERY_TIMEOUT_SECONDS must be an integer") from exc
    if value < 1:
        raise RuntimeError("GRAPHRAG_QUERY_TIMEOUT_SECONDS must be positive")
    return value


def _read_table(name: str) -> pd.DataFrame:
    path = WORKSPACE / "output" / f"{name}.parquet"
    if not path.exists():
        raise RuntimeError(f"graphrag_index_missing:{name}")
    return pd.read_parquet(path)


def _clean_value(value: Any) -> Any:
    if isinstance(value, str):
        return value.encode("utf-8", "replace").decode("utf-8")
    if isinstance(value, list):
        return [_clean_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_clean_value(item) for item in value)
    if isinstance(value, dict):
        return {key: _clean_value(item) for key, item in value.items()}
    return value


def _clean_frame(frame: pd.DataFrame) -> pd.DataFrame:
    for column in frame.columns:
        if frame[column].dtype == object:
            frame[column] = frame[column].map(_clean_value)
    return frame


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return str(value)


def _manifest() -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    path = WORKSPACE / "source_manifest.json"
    if not path.exists():
        return {}, {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    by_title: dict[str, dict[str, Any]] = {}
    for item in payload.get("documents", []):
        name = Path(str(item.get("input_file") or item.get("source_file") or "")).name
        if name:
            by_title[name] = item
            by_title[Path(name).stem] = item
    return payload, by_title


def _page_range(text: str, document_text: str) -> tuple[int | None, int | None]:
    if not text or not document_text:
        return None, None
    start = document_text.find(text)
    if start < 0:
        return None, None
    page_start = document_text[:start].count("\f") + 1
    page_end = page_start + text.count("\f")
    return page_start, page_end


def _evidence_from_units(
    units: list[dict[str, Any]],
    documents: pd.DataFrame,
    *,
    top_k: int,
) -> list[dict[str, Any]]:
    docs_by_id = {str(row.get("id")): row for row in documents.to_dict(orient="records")}
    evidence: list[dict[str, Any]] = []
    seen_documents: set[str] = set()
    for unit in units:
        document_id = str(unit.get("document_id") or "").strip()
        if not document_id or document_id in seen_documents:
            continue
        document = docs_by_id.get(document_id, {})
        text = str(unit.get("text") or "").strip()
        if not text:
            continue
        short_id = str(unit.get("human_readable_id") or unit.get("id") or "").strip()
        title = str(document.get("title") or "公共知识库文献").strip()
        page_start, page_end = _page_range(text, str(document.get("text") or ""))
        evidence.append({
            "evidence_id": f"literature:text_unit:{short_id}",
            "title": title,
            "source_type": "public_knowledge_graphrag",
            "source_locator": f"text_unit:{short_id}",
            "page_start": page_start,
            "page_end": page_end,
            "content": text,
        })
        seen_documents.add(document_id)
        if len(evidence) >= top_k:
            break
    return evidence


def _embed(question: str) -> tuple[list[float], str]:
    import lancedb
    from graphrag.config.load_config import load_config

    config = load_config(root_dir=WORKSPACE)
    embedding = next(iter(config.embedding_models.values()), None)
    if embedding is None:
        raise RuntimeError("graphrag_embedding_model_missing")
    output_dir = WORKSPACE / "output"
    table = lancedb.connect(output_dir / "lancedb").open_table("text_unit_text")
    dimensions = int(table.schema.field("vector").type.list_size)
    payload = json.dumps({
        "model": str(embedding.model),
        "input": question,
        "dimensions": dimensions,
        "encoding_format": "float",
    }, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{str(embedding.api_base).rstrip('/')}/embeddings",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=min(60, _query_timeout_seconds())) as response:  # noqa: S310 - configured local service
        result = json.load(response)
    rows = sorted(result.get("data", []), key=lambda item: int(item.get("index", 0)))
    if len(rows) != 1 or len(rows[0].get("embedding", [])) != dimensions:
        raise RuntimeError("embedding_response_mismatch")
    return [float(value) for value in rows[0]["embedding"]], str(embedding.model)


def _focused(question: str, top_k: int) -> dict[str, Any]:
    import lancedb

    output_dir = WORKSPACE / "output"
    documents = _clean_frame(_read_table("documents"))
    text_units = _clean_frame(_read_table("text_units"))
    units_by_id = {str(row.get("id")): row for row in text_units.to_dict(orient="records")}
    vector, model = _embed(question)
    table = lancedb.connect(output_dir / "lancedb").open_table("text_unit_text")
    rows = table.search(vector).limit(max(40, top_k * 8)).to_pandas()
    ranked_units = [units_by_id[unit_id] for unit_id in rows["id"].astype(str) if unit_id in units_by_id]
    evidence = _evidence_from_units(ranked_units, documents, top_k=top_k)
    if not evidence:
        raise RuntimeError("literature_evidence_not_found")
    manifest, _ = _manifest()
    return _response(
        status="available",
        mode="focused",
        question=question,
        answer=None,
        evidence=evidence,
        method="graphrag_lancedb_vector",
        coverage={
            "corpus_documents": int(len(documents.index)),
            "candidate_units": int(len(rows.index)),
            "evidence_count": len(evidence),
            "complete": True,
        },
        provenance={
            "corpus": str(manifest.get("corpus") or "urban-renewal-public-knowledge"),
            "embedding_model": model,
            "index": "microsoft_graphrag",
        },
        limitations=[PAGE_LIMITATION],
    )


async def _synthesis(question: str, top_k: int) -> dict[str, Any]:
    os.environ.setdefault("GRAPHRAG_API_KEY", _load_dotenv_value("AI_API_KEY"))
    from graphrag.api import global_search
    from graphrag.config.load_config import load_config

    config = load_config(root_dir=WORKSPACE)
    timeout = _query_timeout_seconds()
    for model_config in config.completion_models.values():
        model_config.call_args = {**model_config.call_args, "timeout": timeout}
        model_config.retry = None
    entities = _clean_frame(_read_table("entities"))
    communities = _clean_frame(_read_table("communities"))
    reports = _clean_frame(_read_table("community_reports"))
    answer, _ = await global_search(
        config=config,
        response_type="Multiple paragraphs",
        query=question,
        entities=entities,
        communities=communities,
        community_reports=reports,
        community_level=2,
        dynamic_community_selection=False,
    )
    focused = _focused(question, top_k)
    evidence = focused["evidence"]
    manifest, _ = _manifest()
    return _response(
        status="available",
        mode="synthesis",
        question=question,
        answer=_json_value(answer),
        evidence=evidence,
        method="microsoft_graphrag_global",
        coverage={
            "corpus_documents": int(focused["coverage"]["corpus_documents"]),
            "candidate_units": int(focused["coverage"]["candidate_units"]),
            "evidence_count": len(evidence),
            "complete": True,
        },
        provenance={
            "corpus": str(manifest.get("corpus") or "urban-renewal-public-knowledge"),
            "index": "microsoft_graphrag",
        },
        limitations=[PAGE_LIMITATION],
    )


def _response(
    *,
    status: str,
    mode: str,
    question: str,
    answer: Any,
    evidence: list[dict[str, Any]],
    coverage: dict[str, Any],
    limitations: list[str],
    method: str,
    provenance: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "status": status,
        "mode": mode,
        "question": question,
        "answer": answer,
        "evidence": evidence,
        "coverage": coverage,
        "limitations": limitations,
        "method": method,
        "provenance": provenance,
    }


async def _run(payload: dict[str, Any]) -> dict[str, Any]:
    question = str(payload.get("question") or "").strip()
    mode = str(payload.get("mode") or "focused").strip().lower()
    try:
        top_k = int(payload.get("top_k", 6))
    except (TypeError, ValueError) as exc:
        raise LiteratureRequestError("top_k_invalid") from exc
    if not question:
        raise LiteratureRequestError("question_required")
    if len(question) > 2000:
        raise LiteratureRequestError("question_too_long")
    if mode not in {"focused", "synthesis"}:
        raise LiteratureRequestError("mode_invalid")
    if not 1 <= top_k <= 10:
        raise LiteratureRequestError("top_k_out_of_range")
    return _focused(question, top_k) if mode == "focused" else await _synthesis(question, top_k)


def _terminate_timed_out_query(timeout: int) -> None:
    response = _response(
        status="unavailable",
        mode="",
        question="",
        answer=None,
        evidence=[],
        coverage={"complete": False, "evidence_count": 0},
        limitations=[f"GraphRAG 文献证据查询超过 {timeout} 秒，已停止等待。"],
        method="",
        provenance={"index": "microsoft_graphrag"},
    )
    response["error"] = f"literature_evidence_timeout:{timeout}"
    try:
        os.write(sys.stdout.fileno(), f"{json.dumps(response, ensure_ascii=False)}\n".encode("utf-8"))
    finally:
        os._exit(0)


def main() -> None:
    timeout = _query_timeout_seconds()
    timer = threading.Timer(timeout, _terminate_timed_out_query, args=(timeout,))
    timer.daemon = True
    timer.start()
    payload: dict[str, Any] = {}
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        result = asyncio.run(_run(payload))
    except LiteratureRequestError as exc:
        result = _response(
            status="invalid_request",
            mode=str(payload.get("mode") or "focused"),
            question=str(payload.get("question") or "").strip(),
            answer=None,
            evidence=[],
            coverage={"complete": False, "evidence_count": 0},
            limitations=[],
            method="",
            provenance={},
        )
        result["error"] = str(exc)
    except Exception as exc:  # noqa: BLE001 - unavailable is safer than fabricated evidence
        timed_out = "timeout" in type(exc).__name__.lower() or "timeout" in str(exc).lower()
        result = _response(
            status="unavailable",
            mode=str(payload.get("mode") or "focused"),
            question=str(payload.get("question") or "").strip(),
            answer=None,
            evidence=[],
            coverage={"complete": False, "evidence_count": 0},
            limitations=["文献索引或推理服务当前不可用，未返回文献结论。"],
            method="",
            provenance={"index": "microsoft_graphrag"},
        )
        result["error"] = f"literature_evidence_timeout:{timeout}" if timed_out else str(exc)
    finally:
        timer.cancel()
    print(json.dumps(result, ensure_ascii=False, default=_json_value))


if __name__ == "__main__":
    main()
