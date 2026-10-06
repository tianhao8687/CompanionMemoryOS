"""Bounded, coalesced background work with explicitly inherited call authorization."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from contextvars import Context, copy_context
from threading import Event, Lock, Thread


class IndexWorker:
    def __init__(self, *, context_factory: Callable[[], Context] = copy_context) -> None:
        self.context_factory = context_factory
        self.cancelled = Event()
        self.lock = Lock()
        self.pending: OrderedDict[str, tuple[Callable[[Event], bool], Context]] = OrderedDict()
        self.thread: Thread | None = None
        self.status = "not_started"

    def submit(self, key: str, work: Callable[[Event], bool]) -> bool:
        context = self.context_factory()
        with self.lock:
            if self.cancelled.is_set():
                return False
            if key not in self.pending and len(self.pending) >= 8:
                self.status = "queue_full"
                return False
            self.pending[key] = (work, context)
            if self.thread is None:
                self.status = "queued"
                self.thread = Thread(target=self._run, name="memory-index", daemon=True)
                self.thread.start()
        return True

    def _run(self) -> None:
        while True:
            with self.lock:
                if self.cancelled.is_set() or not self.pending:
                    self.pending.clear()
                    self.thread = None
                    return
                _, (work, context) = self.pending.popitem(last=False)
                self.status = "indexing"
            try:
                complete = context.run(work, self.cancelled)
                self.status = "ready" if complete else "partial"
            except Exception:
                # No automatic retry, especially for a charged remote call.
                self.status = "unavailable_using_fts"

    def close(self) -> None:
        self.cancelled.set()
        with self.lock:
            self.pending.clear()
            thread = self.thread
        if thread is not None:
            thread.join(timeout=20)
            if thread.is_alive():
                raise RuntimeError("embedding worker did not stop within its call timeout")
