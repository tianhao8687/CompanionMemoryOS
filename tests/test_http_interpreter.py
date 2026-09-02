"""Exercise the bundled HTTP adapter against a local stub, without paid/external model calls."""

import json
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from pydantic import ValidationError

from companion_memoryos.config import InterpreterConfig, load_config
from companion_memoryos.interpreter import (
    InterpreterError,
    OpenAICompatibleInterpreter,
    configured_interpreter,
)
from companion_memoryos.schemas import InterpreterContext, InterpreterTurn, RealityLayer


@pytest.fixture
def fake_provider():
    state = {
        "status": 200,
        "headers": {},
        "calls": [],
        "response": {
            "model": "stub-model",
            "choices": [{"finish_reason": "stop", "message": {"content": '{"topics":["雨天"]}'}}],
            "usage": {
                "prompt_tokens": 123,
                "completion_tokens": 15,
                "total_tokens": 138,
                "prompt_tokens_details": {"cached_tokens": 10},
            },
        },
    }

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            state["calls"].append(
                {
                    "path": self.path,
                    "headers": dict(self.headers),
                    "body": json.loads(self.rfile.read(int(self.headers["Content-Length"]))),
                }
            )
            payload = state["response"]
            encoded = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
            self.send_response(state["status"])
            for key, value in state["headers"].items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
    thread.start()
    yield state, f"http://127.0.0.1:{server.server_port}/v1"
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def context():
    return InterpreterContext(
        user_id="user",
        companion_id="ai",
        calendar_timezone="Asia/Singapore",
        reality_layer=RealityLayer.REAL_WORLD,
        current_turn=InterpreterTurn(
            id="turn",
            actor_id="user",
            role="user",
            content="我喜欢雨天",
            occurred_at=datetime.now(UTC),
        ),
    )


def adapter(base_url, **updates):
    config = InterpreterConfig(
        enabled=True,
        base_url=base_url,
        model="configured-stub",
        **updates,
    )
    return OpenAICompatibleInterpreter(config, api_key="test-only-not-a-real-key")


def test_actual_http_request_is_single_bounded_json_call_and_usage_is_reported(fake_provider):
    state, endpoint = fake_provider
    client = adapter(endpoint, max_output_tokens=512)
    output = client.interpret(context())
    assert output.interpretation.topics == ["雨天"]
    assert output.usage.total_tokens == 138
    assert output.model_fingerprint.endswith(":stub-model")
    assert len(state["calls"]) == 1
    call = state["calls"][0]
    assert call["path"] == "/v1/chat/completions"
    body = call["body"]
    assert body["max_completion_tokens"] == 512 and "max_tokens" not in body
    assert body["response_format"] == {"type": "json_object"}
    assert body["n"] == 1 and body["stream"] is False
    assert "tools" not in body
    assert body["messages"][0]["role"] == "system"
    assert "Asia/Singapore" in body["messages"][1]["content"]
    assert "test-only-not-a-real-key" not in repr(body)


def test_gateway_legacy_parameter_and_json_mode_are_explicit_not_automatic_fallback(fake_provider):
    state, endpoint = fake_provider
    client = adapter(
        endpoint, output_token_parameter="max_tokens", json_mode=False, instruction_role="developer"
    )
    client.interpret(context())
    body = state["calls"][0]["body"]
    assert "max_tokens" in body and "max_completion_tokens" not in body
    assert "response_format" not in body and body["messages"][0]["role"] == "developer"
    assert len(state["calls"]) == 1


@pytest.mark.parametrize(
    "body, code",
    [
        (b"not-json SECRET", "interpreter_invalid_output"),
        ({"choices": []}, "interpreter_incomplete_output"),
        (
            {"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]},
            "interpreter_incomplete_output",
        ),
        (
            {
                "choices": [
                    {"finish_reason": "stop", "message": {"content": '{"unexpected":"value"}'}}
                ]
            },
            "interpreter_invalid_output",
        ),
        (
            {
                "choices": [
                    {"finish_reason": "stop", "message": {"content": None, "refusal": "reason"}}
                ]
            },
            "interpreter_refused_or_tool_output",
        ),
        (
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": "{}", "tool_calls": [{"id": "x"}]},
                    }
                ]
            },
            "interpreter_refused_or_tool_output",
        ),
    ],
)
def test_invalid_or_partial_output_is_rejected_without_retry_or_remote_body(
    fake_provider, body, code
):
    state, endpoint = fake_provider
    state["response"] = body
    with pytest.raises(InterpreterError) as raised:
        adapter(endpoint).interpret(context())
    assert str(raised.value) == code and "SECRET" not in str(raised.value)
    assert len(state["calls"]) == 1


def test_remote_error_redirect_and_response_size_do_not_trigger_an_extra_request(fake_provider):
    state, endpoint = fake_provider
    state["status"] = 429
    state["response"] = b"SECRET upstream provider diagnostics"
    with pytest.raises(InterpreterError, match="interpreter_http_error"):
        adapter(endpoint).interpret(context())
    state["status"] = 307
    state["headers"] = {"Location": endpoint + "/redirected"}
    with pytest.raises(InterpreterError, match="interpreter_http_error"):
        adapter(endpoint).interpret(context())
    assert len(state["calls"]) == 2
    state["status"] = 200
    state["headers"] = {}
    with pytest.raises(InterpreterError, match="interpreter_response_too_large"):
        adapter(endpoint, max_response_bytes=1).interpret(context())
    assert len(state["calls"]) == 3


def test_timeout_uses_safe_code_without_implicit_retries(monkeypatch):
    class FailingOpener:
        calls = 0

        def open(self, *_args, **_kwargs):
            self.calls += 1
            raise TimeoutError("PRIVATE DIAGNOSTICS")

    opener = FailingOpener()
    monkeypatch.setattr("companion_memoryos.interpreter.build_opener", lambda *_: opener)
    with pytest.raises(InterpreterError, match=r"^interpreter_timeout$"):
        adapter("http://127.0.0.1/v1").interpret(context())
    assert opener.calls == 1


def test_missing_key_fails_before_network_and_offline_gateway_can_opt_out(
    fake_provider, monkeypatch
):
    state, endpoint = fake_provider
    monkeypatch.delenv("COMPANION_INTERPRETER_API_KEY", raising=False)
    settings = InterpreterConfig(base_url=endpoint, model="stub")
    with pytest.raises(InterpreterError, match="interpreter_api_key_missing"):
        OpenAICompatibleInterpreter(settings).interpret(context())
    assert state["calls"] == []
    OpenAICompatibleInterpreter(settings.model_copy(update={"require_api_key": False})).interpret(
        context()
    )
    assert "Authorization" not in state["calls"][0]["headers"]


def test_config_validates_transport_without_breaking_old_configuration():
    old = load_config().model_dump()
    old.pop("interpreter")
    assert not type(load_config()).model_validate(old).interpreter.enabled
    assert configured_interpreter(InterpreterConfig()) is None
    for options in [
        {"enabled": True},
        {"base_url": "file:///tmp/model"},
        {"base_url": "https://user:secret@example.test/v1"},
        {"base_url": "https://example.test/v1?token=secret"},
        {"timeout_seconds": float("inf")},
        {"max_input_tokens": 0},
    ]:
        with pytest.raises(ValidationError):
            InterpreterConfig(**options)
    first = adapter("https://example.test/v1")
    second = adapter("https://example.test/v1", max_output_tokens=10)
    assert first.fingerprint != second.fingerprint


def test_configured_http_adapter_works_through_unified_process_and_replay(
    fake_provider,
    service,
    monkeypatch,
):
    from companion_memoryos.schemas import MemoryScope, ProcessTurnRequest
    from companion_memoryos.service import CompanionMemoryService

    state, endpoint = fake_provider
    monkeypatch.setenv("COMPANION_INTERPRETER_API_KEY", "local-fixture-only")
    config = service.config.model_copy(
        update={
            "interpreter": InterpreterConfig(enabled=True, base_url=endpoint, model="stub"),
        }
    )
    memory = CompanionMemoryService(service.store, config)
    item = ProcessTurnRequest(
        user_id="user",
        scope=MemoryScope(companion_id="ai", relationship_id="rel", conversation_id="chat"),
        content="我喜欢雨天",
        idempotency_key="http-complete",
        consent="granted",
        model_consent="granted",
    )
    first = memory.process_turn(item)
    cached = memory.process_turn(item)
    assert first.interpretation_status == "completed", first.reasons
    assert cached.interpretation_status == "cached"
    assert first.interpretation.processing_metadata["prompt_sha256"] is not None
    assert len(state["calls"]) == 1
    assert first.model_usage.total_tokens == 138
