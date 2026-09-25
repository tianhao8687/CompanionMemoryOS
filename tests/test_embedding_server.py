from __future__ import annotations

import math

import pytest
from fastapi.testclient import TestClient

from companion_agent.embedding_server import DIMENSIONS, MODEL, create_embedding_app


def test_embedding_contract_and_readiness_counters() -> None:
    observed: list[str] = []

    def encode(texts: list[str]) -> list[list[float]]:
        observed.extend(texts)
        return [[1.0] + [0.0] * (DIMENSIONS - 1) for _ in texts]

    with TestClient(create_embedding_app(encode)) as client:
        result = client.post("/v1/embeddings", json={"model": MODEL, "input": ["小雨", "林舟"]})
        assert result.status_code == 200
        assert [row["index"] for row in result.json()["data"]] == [0, 1]
        assert all(len(row["embedding"]) == DIMENSIONS for row in result.json()["data"])
        assert observed == ["小雨", "林舟"]
        assert client.get("/health").json()["texts_embedded"] == 2
        assert client.get("/v1/models").json()["data"][0]["id"] == MODEL


def test_wrong_model_and_bounded_inputs_never_run_inference() -> None:
    def unexpected(texts: list[str]) -> list[list[float]]:
        raise AssertionError("invalid input reached inference")

    with TestClient(create_embedding_app(unexpected)) as client:
        for payload, status in [
            ({"model": "wrong", "input": "text"}, 400),
            ({"model": MODEL, "input": " "}, 422),
            ({"model": MODEL, "input": []}, 422),
            ({"model": MODEL, "input": ["text"] * 17}, 422),
            ({"model": MODEL, "input": "x" * 16001}, 422),
        ]:
            assert client.post("/v1/embeddings", json=payload).status_code == status
        assert client.get("/health").json()["requests"] == 0


@pytest.mark.parametrize("value", [math.nan, math.inf, 0.0])
def test_invalid_vectors_are_rejected_without_echoing_source(value: float) -> None:
    with TestClient(create_embedding_app(lambda texts: [[value] * DIMENSIONS])) as client:
        result = client.post("/v1/embeddings", json={"model": MODEL, "input": "private source"})
        assert result.status_code == 503
        assert "private source" not in result.text
