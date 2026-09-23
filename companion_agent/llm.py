"""Small Main LLM adapter. Hosts can supply any implementation of MainLLM."""

from __future__ import annotations

import json
import os
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from pydantic import Field

from companion_agent.context import ChatMessage
from companion_agent.persona.models import PersonaModel
from companion_memoryos.config import InterpreterConfig
from companion_memoryos.schemas import InterpreterUsage


class ModelResponse(PersonaModel):
    text: str = Field(min_length=1, max_length=50_000)
    model: str = Field(min_length=1)
    usage: InterpreterUsage | None = None


class MainLLM(Protocol):
    def generate(self, messages: list[ChatMessage]) -> ModelResponse: ...


class MainLLMError(RuntimeError):
    """Fixed error code without provider bodies or credentials."""


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
            "messages": [message.model_dump() for message in messages],
            self.config.output_token_parameter: self.config.max_output_tokens,
            "stream": False,
            "n": 1,
        }

    def request(self, payload: dict[str, Any], timeout: float | None = None) -> dict[str, Any]:
        from companion_agent.streaming import listener, read_sse

        stream = listener.get() is not None
        if stream:
            payload = {**payload, "stream": True, "stream_options": {"include_usage": True}}
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
