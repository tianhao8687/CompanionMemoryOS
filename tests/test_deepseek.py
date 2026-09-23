from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import Any

import pytest
from pydantic import ValidationError

from companion_agent.context import ChatMessage
from companion_agent.deepseek import DeepSeekConfig, DeepSeekLLM
from companion_agent.llm import MainLLMError


@contextmanager
def provider(
    status: int = 200, body: Any = None, *, raw: bytes | None = None
) -> Iterator[tuple[str, list[dict[str, Any]]]]:
    captured: list[dict[str, Any]] = []
    response = (
        body
        if body is not None
        else {
            "model": "deepseek-flash",
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": "小雨，今天想从哪里说起？",
                        "reasoning_content": "private reasoning",
                    },
                }
            ],
            "usage": {
                "prompt_tokens": 20,
                "completion_tokens": 10,
                "total_tokens": 30,
                "prompt_cache_hit_tokens": 0,
            },
        }
    )

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            captured.append(
                {
                    "path": self.path,
                    "authorization": self.headers.get("Authorization"),
                    "body": json.loads(self.rfile.read(int(self.headers["Content-Length"]))),
                }
            )
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            if status == 302:
                self.send_header("Location", "/do-not-follow")
            self.end_headers()
            self.wfile.write(raw if raw is not None else json.dumps(response).encode())

        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", captured
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_deepseek_real_http_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-provider-key")
    with provider() as (url, requests):
        reply = DeepSeekLLM(DeepSeekConfig(base_url=url + "/v1/")).generate(
            [
                ChatMessage(role="system", content="温柔地回应当前消息"),
                ChatMessage(role="user", content="你好"),
            ]
        )
    request = requests[0]
    assert request["path"] == "/v1/chat/completions"
    assert request["authorization"] == "Bearer test-provider-key"
    assert request["body"]["max_tokens"] == 4096
    assert "max_completion_tokens" not in request["body"]
    assert "n" not in request["body"]
    assert request["body"]["thinking"] == {"type": "disabled"}
    assert reply.text == "小雨，今天想从哪里说起？"
    assert "private reasoning" not in reply.model_dump_json()
    assert reply.usage and reply.usage.total_tokens == 30


@pytest.mark.parametrize(
    "model,thinking,temperature",
    [
        ("deepseek-flash", "enabled", False),
        ("deepseek-v4-pro", "disabled", True),
        ("deepseek-reasoner", "disabled", False),
        ("deepseek-chat", "enabled", True),
    ],
)
def test_model_modes(model: str, thinking: str, temperature: bool) -> None:
    config = DeepSeekConfig.model_validate({"model": model, "thinking": thinking})
    body = DeepSeekLLM(config).payload([ChatMessage(role="user", content="你好")])
    assert ("temperature" in body) is temperature
    assert ("thinking" in body) is (model not in {"deepseek-chat", "deepseek-reasoner"})


@pytest.mark.parametrize(
    "url",
    [
        "http://api.deepseek.com",
        "https://example.com/chat/completions",
        "https://secret:password@example.com",
        "https://example.com?key=secret",
        "ftp://example.com",
    ],
)
def test_reject_bad_endpoints(url: str) -> None:
    with pytest.raises(ValidationError):
        DeepSeekConfig(base_url=url)


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "main_llm_auth_failed"),
        (402, "main_llm_insufficient_balance"),
        (403, "main_llm_access_denied"),
        (429, "main_llm_rate_limited"),
        (500, "main_llm_http_error"),
        (302, "main_llm_http_error"),
    ],
)
def test_provider_errors_are_sanitized(status: int, code: str) -> None:
    with (
        provider(status, {"error": "secret credential in provider body"}) as (url, requests),
        pytest.raises(MainLLMError, match=f"^{code}$"),
    ):
        DeepSeekLLM(DeepSeekConfig(base_url=url), api_key="private-key").generate(
            [ChatMessage(role="user", content="你好")]
        )
    assert len(requests) == 1  # No redirect or automatic paid retry.


@pytest.mark.parametrize(
    "body,code",
    [
        (
            {"choices": [{"finish_reason": "length", "message": {"content": "半句话"}}]},
            "main_llm_incomplete_output",
        ),
        (
            {"choices": [{"finish_reason": "stop", "message": {"content": ""}}]},
            "main_llm_invalid_output",
        ),
        (
            {
                "choices": [
                    {"finish_reason": "stop", "message": {"content": "text", "tool_calls": [1]}}
                ]
            },
            "main_llm_non_text_output",
        ),
        ({"unexpected": "shape"}, "main_llm_invalid_output"),
    ],
)
def test_invalid_provider_output_not_accepted(body: Any, code: str) -> None:
    with provider(body=body) as (url, _), pytest.raises(MainLLMError, match=code):
        DeepSeekLLM(DeepSeekConfig(base_url=url), api_key="key").generate(
            [ChatMessage(role="user", content="你好")]
        )


def test_missing_key_does_not_connect(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with provider() as (url, requests), pytest.raises(MainLLMError, match="api_key_missing"):
        DeepSeekLLM(DeepSeekConfig(base_url=url)).generate(
            [ChatMessage(role="user", content="你好")]
        )
    assert not requests


def test_explicit_no_environment_never_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "must-not-leak")
    with pytest.raises(MainLLMError, match="api_key_missing"):
        DeepSeekLLM(use_environment=False).generate([ChatMessage(role="user", content="你好")])
