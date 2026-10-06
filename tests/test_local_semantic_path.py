"""Explicit local semantics must reach the real encoder even with offline chat."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from companion_agent.cognition import CognitionSettings, Embeddings
from companion_agent.deepseek import DeepSeekConfig
from companion_agent.testing.driver import DriverError, ManagedInstance
from tests.test_deepseek import provider


def test_local_semantics_uses_configured_encoder_without_enabling_chat_network():
    with provider(body={"data": [{"embedding": [0.25, 0.75]}]}) as (url, requests):
        settings = CognitionSettings(
            embedding_backend="local_api", embedding=DeepSeekConfig(base_url=url + "/v1")
        )
        encoder = Embeddings(settings, offline=True)
        assert encoder.encode("A query with different wording") == [0.25, 0.75]
        assert encoder.backend == "local_api"
        assert len(requests) == 1
        assert requests[0]["path"] == "/v1/embeddings"
        assert (
            encoder.space
            == Embeddings(
                settings.model_copy(update={"embedding_backend": "api"}), offline=False
            ).space
        )


@pytest.mark.parametrize(
    "url",
    ["https://example.org/v1", "http://localhost:8080/v1", "https://127.0.0.1:8080/v1"],
)
def test_local_semantic_backend_rejects_nonliteral_or_remote_endpoints(url):
    with pytest.raises(ValidationError, match="local embedding"):
        CognitionSettings(embedding_backend="local_api", embedding=DeepSeekConfig(base_url=url))


def test_local_semantics_real_process_trace_budget_and_restart(tmp_path: Path):
    with provider(body={"data": [{"embedding": [0.25, 0.75]}]}) as (url, requests):
        endpoint = url + "/v1"
        instance = ManagedInstance(tmp_path, local_embedding_url=endpoint)
        try:
            client = instance.start()
            settings = client.request("GET", "/api/bootstrap")["settings"]
            settings["cognition"].update(embedding_backend="local_api", extract_memory=False)
            settings["cognition"]["embedding"]["base_url"] = endpoint
            client.request("PUT", "/api/settings", {"settings": settings})
            for index in range(2):
                session = client.new_session()
                response = client.send_message(session, f"Local semantic transport {index}")
                trace = client.inspect_trace(response["trace_id"])
                encoded = [
                    c
                    for c in trace["calls"]
                    if c["source"] == "embedding" and not c.get("background")
                ]
                assert len(encoded) == 1
                assert encoded[0]["vector_dimensions"] == 2
                assert not any(c["live"] for c in trace["calls"])
                assert client.identity["model_mode"] == "offline"
                if index == 0:
                    client = instance.restart()
            assert requests and all(r["path"] == "/v1/embeddings" for r in requests)
            identity = client.request("GET", "/api/testing/discover")
            assert identity["accounting"]["calls"] >= 4
            assert identity["accounting"]["live_calls"] == 0
            settings["cognition"]["embedding"]["base_url"] = "http://127.0.0.1:18081/v1"
            with pytest.raises(DriverError, match="HTTP 403"):
                client.request("PUT", "/api/settings", {"settings": settings})
        finally:
            instance.stop()


def test_larger_call_budget_requires_local_only_batch(tmp_path: Path):
    for changes in [{}, {"allow_live": True, "local_embedding_url": "http://127.0.0.1:8080/v1"}]:
        with pytest.raises(ValueError, match="bounded"):
            ManagedInstance(tmp_path, max_calls=3800, **changes)
    instance = ManagedInstance(
        tmp_path, max_calls=3800, local_embedding_url="http://127.0.0.1:8080/v1"
    )
    instance.stop()
