from __future__ import annotations

import numpy as np
from fastapi.testclient import TestClient

from modules import embedding_service


class _FakeEmbeddingModel:
    def embed(self, values, *, batch_size):
        assert batch_size == 32
        for index, _value in enumerate(values):
            yield np.full((768,), index + 0.25, dtype=np.float32)


def test_openai_embedding_service_returns_one_indexed_vector_per_input(monkeypatch):
    monkeypatch.setattr(embedding_service, "_get_model", lambda: _FakeEmbeddingModel())
    monkeypatch.setenv("EMBEDDING_MODEL", embedding_service.DEFAULT_MODEL)
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", "768")

    with TestClient(embedding_service.app) as client:
        response = client.post(
            "/v1/embeddings",
            json={
                "model": embedding_service.DEFAULT_MODEL,
                "input": ["长沙县政府原址", "步行入口策略"],
                "dimensions": 768,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["object"] == "list"
    assert payload["model"] == embedding_service.DEFAULT_MODEL
    assert [item["index"] for item in payload["data"]] == [0, 1]
    assert all(item["object"] == "embedding" for item in payload["data"])
    assert all(len(item["embedding"]) == 768 for item in payload["data"])
    assert payload["usage"] == {"prompt_tokens": 0, "total_tokens": 0}


def test_embedding_service_rejects_model_or_dimension_drift(monkeypatch):
    monkeypatch.setattr(embedding_service, "_get_model", lambda: _FakeEmbeddingModel())
    monkeypatch.setenv("EMBEDDING_MODEL", embedding_service.DEFAULT_MODEL)
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", "768")

    with TestClient(embedding_service.app) as client:
        model_response = client.post(
            "/v1/embeddings",
            json={"model": "different-model", "input": "test", "dimensions": 768},
        )
        dimension_response = client.post(
            "/v1/embeddings",
            json={"model": embedding_service.DEFAULT_MODEL, "input": "test", "dimensions": 512},
        )

    assert model_response.status_code == 400
    assert model_response.json()["detail"] == "embedding_model_mismatch"
    assert dimension_response.status_code == 400
    assert dimension_response.json()["detail"] == "embedding_dimensions_mismatch"


def test_embedding_service_does_not_expose_the_removed_ollama_contract():
    with TestClient(embedding_service.app) as client:
        response = client.post(
            "/api/embed",
            json={"model": embedding_service.DEFAULT_MODEL, "input": "test", "dimensions": 768},
        )

    assert response.status_code == 404
