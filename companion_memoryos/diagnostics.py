"""Opt-in diagnostics at the adapter boundary; disabled in ordinary operation.

The host owns authorization, retention and budgets. Never record private reasoning,
transport headers or credentials. Context variables keep concurrent requests separate.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from time import monotonic
from typing import Any, Protocol


class DiagnosticSink(Protocol):
    def begin_call(self, source: str, payload: dict[str, Any], live: bool) -> dict[str, Any]: ...

    def finish_call(self, call: dict[str, Any]) -> None: ...

    def event(self, name: str, value: Any) -> None: ...


sink: ContextVar[DiagnosticSink | None] = ContextVar("model_diagnostics", default=None)


def record(name: str, value: Any) -> None:
    active = sink.get()
    if active is not None:
        active.event(name, value)


@contextmanager
def model_call(
    source: str, payload: dict[str, Any], *, live: bool = True
) -> Iterator[dict[str, Any]]:
    active = sink.get()
    if active is None:
        yield {}
        return
    call = active.begin_call(source, payload, live)
    started = monotonic()
    try:
        yield call
        call["status"] = "returned"
    except Exception as error:
        # Exception strings can include untrusted remote bodies or secrets.
        call["status"] = "failed"
        call["error_type"] = type(error).__name__
        raise
    finally:
        call["elapsed_seconds"] = monotonic() - started
        active.finish_call(call)
