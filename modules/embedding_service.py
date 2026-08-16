"""Small CPU embedding service consumed by n8n's EMB-00 workflow.

The HTTP contract intentionally mirrors Ollama's ``/api/embed`` shape so the
workflow does not know which local inference runtime is used.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator


DEFAULT_MODEL = "jinaai/jina-embeddings-v2-base-zh"
DEFAULT_DIMENSIONS = 768


class EmbedRequest(BaseModel):
    model: str = DEFAULT_MODEL
    input: str | list[str]
    dimensions: int = Field(default=DEFAULT_DIMENSIONS, ge=1, le=4096)
    truncate: bool = True
    keep_alive: str = ""

    @field_validator("model", mode="before")
    @classmethod
    def normalize_model(cls, value: object) -> str:
        return str(value or "").strip()

    @field_validator("input", mode="before")
    @classmethod
    def normalize_input(cls, value: object) -> str | list[str]:
        values = value if isinstance(value, list) else [value]
        normalized = [str(item or "").strip() for item in values]
        if not normalized or any(not item for item in normalized):
            raise ValueError("input must contain non-empty text")
        return normalized if isinstance(value, list) else normalized[0]


class EmbedResponse(BaseModel):
    model: str
    embeddings: list[list[float]]
    dimensions: int
    prompt_eval_count: int = 0


def _configured_model() -> str:
    return str(os.getenv("EMBEDDING_MODEL") or DEFAULT_MODEL).strip() or DEFAULT_MODEL


def _configured_dimensions() -> int:
    raw = str(os.getenv("EMBEDDING_DIMENSIONS") or DEFAULT_DIMENSIONS).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError("EMBEDDING_DIMENSIONS must be an integer") from exc
    if value < 1:
        raise RuntimeError("EMBEDDING_DIMENSIONS must be positive")
    return value


def _configured_batch_size() -> int:
    raw = str(os.getenv("EMBEDDING_BATCH_SIZE") or "32").strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError("EMBEDDING_BATCH_SIZE must be an integer") from exc
    if value < 1:
        raise RuntimeError("EMBEDDING_BATCH_SIZE must be positive")
    return value


@lru_cache(maxsize=1)
def _get_model() -> Any:
    from fastembed import TextEmbedding

    cache_dir = Path(os.getenv("EMBEDDING_CACHE_DIR") or "runtime/embedding-models")
    cache_dir.mkdir(parents=True, exist_ok=True)
    return TextEmbedding(model_name=_configured_model(), cache_dir=str(cache_dir))


def _encode(values: list[str]) -> list[list[float]]:
    try:
        rows = list(_get_model().embed(values, batch_size=_configured_batch_size()))
    except Exception as exc:  # inference/download errors are an API readiness failure
        raise HTTPException(status_code=503, detail=f"embedding_model_unavailable:{exc}") from exc
    dimensions = _configured_dimensions()
    result = [[float(value) for value in row] for row in rows]
    if len(result) != len(values) or any(len(row) != dimensions for row in result):
        raise HTTPException(status_code=502, detail="embedding_dimension_mismatch")
    return result


app = FastAPI(title="Gaode Map Embedding Service", version="1.0")


@app.get("/live")
def live() -> dict[str, str]:
    return {"status": "alive"}


@app.get("/health")
def health() -> dict[str, object]:
    _encode(["health check"])
    return {"status": "healthy", "model": _configured_model(), "dimensions": _configured_dimensions()}


@app.post("/api/embed", response_model=EmbedResponse)
def embed(request: EmbedRequest) -> EmbedResponse:
    if request.model and request.model != _configured_model():
        raise HTTPException(status_code=400, detail="embedding_model_mismatch")
    if request.dimensions != _configured_dimensions():
        raise HTTPException(status_code=400, detail="embedding_dimensions_mismatch")
    values = request.input if isinstance(request.input, list) else [request.input]
    embeddings = _encode(values)
    return EmbedResponse(
        model=_configured_model(),
        embeddings=embeddings,
        dimensions=request.dimensions,
        prompt_eval_count=0,
    )
