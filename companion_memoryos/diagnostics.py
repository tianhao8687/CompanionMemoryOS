"""Opt-in diagnostics at the adapter boundary; disabled in ordinary operation.

The host owns authorization, retention and budgets. Never record private reasoning,
transport headers or credentials. Context variables keep concurrent requests separate.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import Context, ContextVar, copy_context
from time import monotonic
from typing import Any, Protocol, runtime_checkable


class DiagnosticSink(Protocol):
    """Callbacks can run on worker threads; guards must enforce their original budget."""

    def begin_call(self, source: str, payload: dict[str, Any], live: bool) -> dict[str, Any]: ...

    def finish_call(self, call: dict[str, Any]) -> None: ...

    def event(self, name: str, value: Any) -> None: ...


@runtime_checkable
class ForkableDiagnosticSink(DiagnosticSink, Protocol):
    """Optional snapshot for sinks whose attribution depends on a mutable request."""

    def fork_background(self) -> DiagnosticSink: ...


sink: ContextVar[DiagnosticSink | None] = ContextVar("model_diagnostics", default=None)


def background_context() -> Context:
    context = copy_context()
    active = sink.get()
    if isinstance(active, ForkableDiagnosticSink):
        context.run(sink.set, active.fork_background())
    # A plain observer/guard is retained, never dropped or treated as authorization.
    return context


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
