"""Small Main LLM adapter. Hosts can supply any implementation of MainLLM."""

from __future__ import annotations

import json
import os
from typing import Any, Protocol, runtime_checkable
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from pydantic import Field

from companion_agent.context import ChatMessage
from companion_agent.persona.models import PersonaModel
from companion_memoryos.config import InterpreterConfig
from companion_memoryos.diagnostics import model_call
from companion_memoryos.schemas import InterpreterUsage
from companion_memoryos.tokens import TokenCounter


class ModelResponse(PersonaModel):
    text: str = Field(min_length=1, max_length=50_000)
    model: str = Field(min_length=1)
    usage: InterpreterUsage | None = None
    sticker_id: str | None = None


class MainLLM(Protocol):
    def generate(self, messages: list[ChatMessage]) -> ModelResponse: ...


@runtime_checkable
class InputBudgetModel(Protocol):
    """Pure preview of text added by an adapter; must never generate or execute tools."""

    def input_tokens(self, messages: list[ChatMessage], counter: TokenCounter) -> int: ...


def wire_input_tokens(
    messages: list[dict[str, Any]],
    counter: TokenCounter,
    tools: list[dict[str, Any]] | None = None,
) -> int:
    # This is the application's text budget. Image token accounting is provider
    # specific: a base64 transport string is not a textual model input.
    text_messages = []
    for message in messages:
        copy = dict(message)
        if isinstance(copy.get("content"), list):
            copy["content"] = [p for p in copy["content"] if p.get("type") == "text"]
        text_messages.append(copy)
    payload: dict[str, Any] = {"messages": text_messages}
    if tools is not None:
        payload["tools"] = tools
    return counter.count(json.dumps(payload, ensure_ascii=False))


def model_input_tokens(model: MainLLM, messages: list[ChatMessage], counter: TokenCounter) -> int:
    if isinstance(model, InputBudgetModel):
        return model.input_tokens(messages, counter)
    return wire_input_tokens([message.wire() for message in messages], counter)


class MainLLMError(RuntimeError):
    """Fixed error code without provider bodies or credentials."""


class ContextBudgetError(ValueError):
    """Required input cannot fit even after optional context has been removed."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


class OpenAICompatibleMainLLM:
    def __init__(
        self, config: InterpreterConfig, *, api_key: str | None = None, use_environment: bool = True
    ) -> None:
        # Reuse the project's validated endpoint, timeout and credential configuration.
        if config.base_url is None or config.model is None:
            raise ValueError("Main LLM requires base_url and model")
        self.config = config
        self._api_key = api_key
        self._use_environment = use_environment

    def payload(self, messages: list[ChatMessage]) -> dict[str, Any]:
        return {
            "model": self.config.model,
            "messages": [message.wire() for message in messages],
            self.config.output_token_parameter: self.config.max_output_tokens,
            "stream": False,
            "n": 1,
        }

    def request(self, payload: dict[str, Any], timeout: float | None = None) -> dict[str, Any]:
        from companion_agent.streaming import listener

        stream = listener.get() is not None
        if stream:
            payload = {**payload, "stream": True, "stream_options": {"include_usage": True}}
        with model_call("chat", payload) as call:
            bounded_timeout = min(
                timeout or self.config.timeout_seconds,
                call.get("remaining_seconds", self.config.timeout_seconds),
            )
            result = self._request(payload, bounded_timeout, stream=stream)
            call["response"] = result
            return result

    def _request(
        self, payload: dict[str, Any], timeout: float | None, *, stream: bool
    ) -> dict[str, Any]:
        from companion_agent.streaming import read_sse

        config = self.config
        key = self._api_key or (
            os.environ.get(config.api_key_env) if self._use_environment else None
        )
        if config.require_api_key and not key:
            raise MainLLMError("main_llm_api_key_missing")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        request = Request(
            f"{config.base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with build_opener(_NoRedirect()).open(
                request, timeout=min(config.timeout_seconds, timeout or config.timeout_seconds)
            ) as response:
                if stream:
                    return read_sse(
                        response,
                        config.max_response_bytes,
                        min(config.timeout_seconds, timeout or config.timeout_seconds),
                    )
                raw = response.read(config.max_response_bytes + 1)
        except TimeoutError:
            raise MainLLMError("main_llm_timeout") from None
        except HTTPError as error:
            code = {
                401: "main_llm_auth_failed",
                402: "main_llm_insufficient_balance",
                403: "main_llm_access_denied",
                429: "main_llm_rate_limited",
            }.get(error.code, "main_llm_http_error")
            error.close()
            raise MainLLMError(code) from None
        except (URLError, OSError):
            raise MainLLMError("main_llm_unavailable") from None
        if len(raw) > config.max_response_bytes:
            raise MainLLMError("main_llm_response_too_large")
        try:
            envelope = json.loads(raw)
            if not isinstance(envelope, dict):
                raise ValueError("invalid envelope")
            return envelope
        except (ValueError, TypeError):
            raise MainLLMError("main_llm_invalid_output") from None

    def generate(self, messages: list[ChatMessage]) -> ModelResponse:
        envelope = self.request(self.payload(messages))
        try:
            choices = envelope["choices"]
            if len(choices) != 1 or choices[0].get("finish_reason") != "stop":
                raise MainLLMError("main_llm_incomplete_output")
            message = choices[0]["message"]
            if message.get("refusal") or message.get("tool_calls") or message.get("function_call"):
                raise MainLLMError("main_llm_non_text_output")
            if not isinstance(message["content"], str) or not message["content"].strip():
                raise ValueError("empty response")
            usage = envelope.get("usage")
            return ModelResponse(
                text=message["content"],
                model=envelope.get("model") or self.config.model or "unknown",
                usage=InterpreterUsage.model_validate(
                    {name: usage[name] for name in InterpreterUsage.model_fields if name in usage}
                )
                if isinstance(usage, dict)
                else None,
            )
        except (ValueError, KeyError, TypeError, IndexError, AttributeError):
            raise MainLLMError("main_llm_invalid_output") from None
