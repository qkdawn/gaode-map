from __future__ import annotations

import numpy as np
from fastapi.testclient import TestClient

from modules import embedding_service


class _FakeEmbeddingModel:
    def embed(self, values, *, batch_size):
        assert batch_size == 32
        for index, _value in enumerate(values):
            yield np.full((768,), index + 0.25, dtype=np.float32)


def test_embedding_service_returns_one_valid_vector_per_input(monkeypatch):
    monkeypatch.setattr(embedding_service, "_get_model", lambda: _FakeEmbeddingModel())
    monkeypatch.setenv("EMBEDDING_MODEL", embedding_service.DEFAULT_MODEL)
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", "768")

    with TestClient(embedding_service.app) as client:
        response = client.post(
            "/api/embed",
            json={
                "model": embedding_service.DEFAULT_MODEL,
                "input": ["长沙县政府原址", "步行入口策略"],
                "dimensions": 768,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["model"] == embedding_service.DEFAULT_MODEL
    assert payload["dimensions"] == 768
    assert len(payload["embeddings"]) == 2
    assert all(len(row) == 768 for row in payload["embeddings"])


def test_embedding_service_rejects_model_or_dimension_drift(monkeypatch):
    monkeypatch.setattr(embedding_service, "_get_model", lambda: _FakeEmbeddingModel())
    monkeypatch.setenv("EMBEDDING_MODEL", embedding_service.DEFAULT_MODEL)
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", "768")

    with TestClient(embedding_service.app) as client:
        model_response = client.post(
            "/api/embed",
            json={"model": "different-model", "input": "test", "dimensions": 768},
        )
        dimension_response = client.post(
            "/api/embed",
            json={"model": embedding_service.DEFAULT_MODEL, "input": "test", "dimensions": 512},
        )

    assert model_response.status_code == 400
    assert model_response.json()["detail"] == "embedding_model_mismatch"
    assert dimension_response.status_code == 400
    assert dimension_response.json()["detail"] == "embedding_dimensions_mismatch"
