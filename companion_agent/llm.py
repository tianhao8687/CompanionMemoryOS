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
    def __init__(self, config: InterpreterConfig) -> None:
        # Reuse the project's validated endpoint, timeout and credential configuration.
        if config.base_url is None or config.model is None:
            raise ValueError("Main LLM requires base_url and model")
        self.config = config

    def generate(self, messages: list[ChatMessage]) -> ModelResponse:
        config = self.config
        key = os.environ.get(config.api_key_env)
        if config.require_api_key and not key:
            raise MainLLMError("main_llm_api_key_missing")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        payload = {
            "model": config.model,
            "messages": [message.model_dump() for message in messages],
            config.output_token_parameter: config.max_output_tokens,
            "stream": False,
            "n": 1,
        }
        request = Request(
            f"{config.base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with build_opener(_NoRedirect()).open(
                request, timeout=config.timeout_seconds
            ) as response:
                raw = response.read(config.max_response_bytes + 1)
        except TimeoutError:
            raise MainLLMError("main_llm_timeout") from None
        except HTTPError:
            raise MainLLMError("main_llm_http_error") from None
        except (URLError, OSError):
            raise MainLLMError("main_llm_unavailable") from None
        if len(raw) > config.max_response_bytes:
            raise MainLLMError("main_llm_response_too_large")
        try:
            envelope = json.loads(raw)
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
                model=envelope.get("model") or config.model or "unknown",
                usage=InterpreterUsage.model_validate(
                    {name: usage[name] for name in InterpreterUsage.model_fields if name in usage}
                )
                if isinstance(usage, dict)
                else None,
            )
        except (ValueError, KeyError, TypeError, IndexError, AttributeError):
            raise MainLLMError("main_llm_invalid_output") from None
