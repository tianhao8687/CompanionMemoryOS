"""Per-request public output events. Reasoning and tool arguments are never streamed."""

from __future__ import annotations

import json
from collections.abc import Callable
from contextvars import ContextVar
from threading import Event
from time import monotonic
from typing import Any

listener: ContextVar[Callable[[dict[str, Any]], None] | None] = ContextVar(
    "output_listener", default=None
)
cancelled: ContextVar[Event | None] = ContextVar("output_cancelled", default=None)


def emit(event: dict[str, Any]) -> None:
    callback = listener.get()
    if callback:
        callback(event)


def read_sse(response: Any, max_bytes: int, timeout: float = 120) -> dict[str, Any]:
    from companion_agent.llm import MainLLMError

    message: dict[str, Any] = {"role": "assistant", "content": ""}
    calls: dict[int, dict[str, Any]] = {}
    envelope: dict[str, Any] = {"choices": [{"message": message, "finish_reason": None}]}
    size = 0
    done = False
    started = monotonic()
    emit({"type": "reset"})
    try:
        while True:
            signal = cancelled.get()
            if signal is not None and signal.is_set():
                raise MainLLMError("main_llm_cancelled")
            if monotonic() - started >= timeout:
                raise MainLLMError("main_llm_timeout")
            line = response.readline(min(65537, max_bytes + 1))
            if not line:
                break
            size += len(line)
            if size > max_bytes or len(line) > 65536:
                raise MainLLMError("main_llm_response_too_large")
            if not line.startswith(b"data:"):
                continue
            raw = line[5:].strip()
            if raw == b"[DONE]":
                done = True
                break
            chunk = json.loads(raw)
            if chunk.get("error"):
                raise ValueError("stream error")
            if chunk.get("model"):
                envelope["model"] = chunk["model"]
            if chunk.get("usage"):
                envelope["usage"] = chunk["usage"]
            choices = chunk.get("choices", [])
            if not choices:
                continue
            if len(choices) != 1 or choices[0].get("index", 0) != 0:
                raise ValueError("invalid stream choices")
            choice = choices[0]
            delta = choice.get("delta", {})
            if choice.get("finish_reason"):
                envelope["choices"][0]["finish_reason"] = choice["finish_reason"]
            for field in ("content", "reasoning_content", "refusal"):
                value = delta.get(field)
                if value:
                    if not isinstance(value, str):
                        raise ValueError("invalid stream text")
                    message[field] = message.get(field, "") + value
                    if field == "content" and not calls:
                        emit({"type": "delta", "text": value})
            for fragment in delta.get("tool_calls", []):
                index = fragment["index"]
                if not isinstance(index, int) or not 0 <= index < 24:
                    raise ValueError("invalid tool index")
                call = calls.setdefault(
                    index, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
                )
                call["id"] += fragment.get("id", "")
                for field in ("name", "arguments"):
                    call["function"][field] += fragment.get("function", {}).get(field, "")
        if not done or envelope["choices"][0]["finish_reason"] is None:
            raise MainLLMError("main_llm_incomplete_output")
        if calls:
            message["tool_calls"] = [calls[index] for index in sorted(calls)]
            emit({"type": "reset"})
        return envelope
    except (ValueError, KeyError, TypeError, IndexError, AttributeError):
        raise MainLLMError("main_llm_invalid_output") from None
