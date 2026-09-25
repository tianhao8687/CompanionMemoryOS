from __future__ import annotations

from pathlib import Path

import pytest

from companion_agent.cognition import CognitionSettings, Embeddings
from companion_agent.deepseek import DeepSeekConfig
from companion_agent.llm import MainLLMError
from companion_agent.testing.control import TestControl as DiagnosticControl
from companion_agent.testing.driver import DriverError, ManagedInstance
from tests.test_deepseek import provider


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://example.org/v1",
        "http://localhost:8080/v1",
        "http://127.0.0.1:8080/v1?url=x",
        "http://user:secret@127.0.0.1:8080/v1",
        "http://127.0.0.1:99999/v1",
    ],
)
def test_embedding_opt_in_rejects_nonliteral_or_ambiguous_endpoint(
    tmp_path: Path, endpoint: str
) -> None:
    with pytest.raises(ValueError, match="local embedding URL"):
        ManagedInstance(tmp_path, local_embedding_url=endpoint)


def test_real_process_requires_exact_embedding_opt_in_after_restart(tmp_path: Path) -> None:
    endpoint = "http://127.0.0.1:18080/v1"
    instance = ManagedInstance(tmp_path, local_embedding_url=endpoint)
    try:
        client = instance.start()
        settings = client.request("GET", "/api/bootstrap")["settings"]
        settings["cognition"]["embedding_backend"] = "api"
        settings["cognition"]["embedding"]["base_url"] = endpoint
        client.request("PUT", "/api/settings", {"settings": settings})
        client = instance.restart()
        assert client.request("GET", "/api/bootstrap")["settings"] == settings
        for forbidden in ["http://127.0.0.1:18081/v1", "https://example.org/v1"]:
            settings["cognition"]["embedding"]["base_url"] = forbidden
            with pytest.raises(DriverError, match="HTTP 403"):
                client.request("PUT", "/api/settings", {"settings": settings})
    finally:
        instance.stop()


def test_embedding_calls_consume_persistent_budget_before_network(tmp_path: Path) -> None:
    instance = ManagedInstance(tmp_path, max_calls=1)
    try:
        control = DiagnosticControl(instance.directory, instance.token)
        control.allowed.add("synthetic")
        with provider(body={"data": [{"embedding": [1.0, 0.0]}]}) as (url, requests):
            encoder = Embeddings(
                CognitionSettings(embedding_backend="api", embedding=DeepSeekConfig(base_url=url)),
                offline=False,
            )
            with control.capture("synthetic", "first", "seed") as trace:
                assert encoder.encode("synthetic memory") == [1.0, 0.0]
            assert trace["calls"][0]["source"] == "embedding"
            assert trace["calls"][0]["vector_dimensions"] == 2
            restored = DiagnosticControl(instance.directory, instance.token)
            restored.allowed.add("synthetic")
            with (
                restored.capture("synthetic", "second", "query"),
                pytest.raises(MainLLMError, match="budget"),
            ):
                encoder.encode("synthetic question")
            assert len(requests) == 1
            assert restored.accounting["calls"] == 1
            assert restored.accounting["live_calls"] == 0
    finally:
        instance.cleanup()
