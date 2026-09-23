"""DeepSeek chat transport, with explicit provider parameters and no SDK dependency."""

from __future__ import annotations

import ipaddress
from contextlib import suppress
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator

from companion_agent.context import ChatMessage
from companion_agent.llm import MainLLMError, OpenAICompatibleMainLLM
from companion_agent.persona.models import PersonaModel
from companion_memoryos.config import InterpreterConfig


class DeepSeekConfig(PersonaModel):
    base_url: str = "https://api.deepseek.com"
    model: str = Field(default="deepseek-flash", min_length=1, max_length=128)
    api_key_env: str = Field(default="DEEPSEEK_API_KEY", pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    timeout_seconds: float = Field(default=120, gt=0, le=300, allow_inf_nan=False)
    max_tokens: int = Field(default=4096, ge=128, le=32768)
    temperature: float = Field(default=0.9, ge=0, le=2, allow_inf_nan=False)
    thinking: Literal["disabled", "enabled"] = "disabled"

    @field_validator("base_url")
    @classmethod
    def endpoint(cls, value: str) -> str:
        endpoint = InterpreterConfig.valid_endpoint(value.strip())
        assert endpoint is not None
        parts = urlsplit(endpoint)
        if parts.path.rstrip("/").endswith("/chat/completions"):
            raise ValueError("base_url must not include /chat/completions")
        local = parts.hostname == "localhost"
        with suppress(ValueError):
            local = local or ipaddress.ip_address(parts.hostname or "").is_loopback
        if parts.scheme != "https" and not local:
            raise ValueError("remote model endpoints require HTTPS")
        return endpoint

    @field_validator("model")
    @classmethod
    def model_name(cls, value: str) -> str:
        value = value.strip()
        if not value or any(character.isspace() for character in value):
            raise ValueError("model must be a nonblank model identifier")
        return value


class DeepSeekLLM(OpenAICompatibleMainLLM):
    def __init__(
        self,
        config: DeepSeekConfig | None = None,
        *,
        api_key: str | None = None,
        use_environment: bool = True,
    ) -> None:
        self.deepseek = config or DeepSeekConfig()
        super().__init__(
            InterpreterConfig(
                base_url=self.deepseek.base_url,
                model=self.deepseek.model,
                api_key_env=self.deepseek.api_key_env,
                timeout_seconds=self.deepseek.timeout_seconds,
                max_output_tokens=self.deepseek.max_tokens,
                max_response_bytes=1_048_576,
                output_token_parameter="max_tokens",
            ),
            api_key=api_key,
            use_environment=use_environment,
        )

    def payload(self, messages: list[ChatMessage]) -> dict[str, Any]:
        config = self.deepseek
        payload = super().payload(messages)
        payload.pop("n")
        # Legacy aliases already select their mode. Modern models accept `thinking`.
        if config.model not in {"deepseek-chat", "deepseek-reasoner"}:
            payload["thinking"] = {"type": config.thinking}
        thinking = config.model == "deepseek-reasoner" or (
            config.model != "deepseek-chat" and config.thinking == "enabled"
        )
        if not thinking:
            payload["temperature"] = config.temperature
        return payload

    def generate_step(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], timeout: float
    ) -> Any:
        from companion_agent.automation.loop import ModelStep, ToolCall

        payload = self.payload([])
        payload["messages"] = messages
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
        envelope = self.request(payload, timeout)
        try:
            choices = envelope["choices"]
            if len(choices) != 1:
                raise ValueError("one choice required")
            choice = choices[0]
            if choice.get("finish_reason") not in {"stop", "tool_calls"}:
                raise MainLLMError("main_llm_incomplete_output")
            raw = choice["message"]
            if raw.get("refusal") or raw.get("function_call"):
                raise MainLLMError("main_llm_non_text_output")
            calls = []
            for call in raw.get("tool_calls") or []:
                if call.get("type") != "function":
                    raise ValueError("invalid tool call type")
                calls.append(
                    ToolCall(
                        id=call["id"],
                        name=call["function"]["name"],
                        arguments=call["function"]["arguments"],
                    )
                )
            content = raw.get("content") or ""
            if not calls and (not isinstance(content, str) or not content.strip()):
                raise ValueError("empty output")
            message = {"role": "assistant", "content": content}
            if calls:
                message["tool_calls"] = [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {
                            "name": c.name,
                            "arguments": c.arguments,
                        },
                    }
                    for c in calls
                ]
            # DeepSeek requires this field to be returned during thinking-mode tool turns.
            # It stays in this in-memory loop and is never saved to chat/action history.
            if isinstance(raw.get("reasoning_content"), str):
                message["reasoning_content"] = raw["reasoning_content"]
            return ModelStep(
                message=message,
                calls=calls,
                text=content,
                model=envelope.get("model") or self.deepseek.model,
                total_tokens=(envelope.get("usage") or {}).get("total_tokens", 0),
            )
        except (ValueError, KeyError, TypeError, IndexError, AttributeError):
            raise MainLLMError("main_llm_invalid_output") from None
