"""Short-lived, instance-bound diagnostics for synthetic test instances only."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import RLock
from time import sleep, time
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from fastapi import Depends, HTTPException, Request

from companion_memoryos.diagnostics import sink
from companion_memoryos.schemas import MemoryStatus

if TYPE_CHECKING:
    from fastapi import FastAPI

    from companion_agent.app import ChatInput, RomanceHost

LEASE_SECONDS = 3600
TRACE_SECONDS = 900
MAX_TRACES = 64
SCHEMA = "companion-test-v1"


def is_local_embedding_url(value: str) -> bool:
    try:
        parts = urlsplit(value)
        return bool(
            parts.scheme == "http"
            and parts.hostname == "127.0.0.1"
            and parts.port is not None
            and 1 <= parts.port <= 65535
            and parts.path == "/v1"
            and not (parts.username or parts.password or parts.query or parts.fragment)
        )
    except ValueError:
        return False


def fingerprint() -> dict[str, str]:
    root = Path(__file__).resolve().parents[2]
    digest = hashlib.sha256()
    for folder in (root / "companion_agent", root / "companion_memoryos"):
        for path in sorted(folder.rglob("*")):
            if path.is_file() and path.suffix in {".py", ".yaml", ".toml", ".js", ".html", ".css"}:
                digest.update(path.relative_to(root).as_posix().encode())
                digest.update(path.read_bytes())
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, stderr=subprocess.DEVNULL, text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        commit = "unknown"
    return {"commit": commit, "source_sha256": digest.hexdigest()}


def read_marker(run_dir: Path) -> dict[str, Any]:
    raw = run_dir.absolute()
    for part in (raw, *raw.parents):
        if part.is_symlink() or part.is_junction():
            raise ValueError("test path cannot contain links")
    marker: dict[str, Any] = json.loads((raw / "run.json").read_text(encoding="utf-8"))
    if (
        marker.get("protocol") != SCHEMA
        or raw.name != marker.get("run_id")
        or str(raw.parent.resolve()) != marker.get("root")
        or str(UUID(marker["run_id"])) != marker["run_id"]
    ):
        raise ValueError("not an owned synthetic test run")
    return marker


class TestControl:
    def __init__(self, run_dir: Path, token: str) -> None:
        self.directory = run_dir.resolve()
        self.marker = read_marker(run_dir)
        if len(token) < 32:
            raise ValueError("a separate test credential is required")
        self.token = token
        self.instance_id = str(uuid4())
        self.code = fingerprint()  # Capture once, never relabel an old running process.
        self.allowed: set[str] = set()
        self.traces: dict[str, dict[str, Any]] = {}
        self.current: dict[str, Any] | None = None
        self.lock = RLock()
        self.secrets = [token]
        self.offset_seconds = 0.0
        self.accounting_path = self.directory / "accounting.json"
        self.accounting: dict[str, Any] = (
            json.loads(self.accounting_path.read_text(encoding="utf-8"))
            if self.accounting_path.exists()
            else {"calls": 0, "turns": 0, "live_calls": 0}
        )

    def clock(self) -> datetime:
        return datetime.now(UTC) + timedelta(seconds=self.offset_seconds)

    def valid(self) -> bool:
        return bool(time() < self.marker["expires_at"])

    def allows_local_embedding(self, base_url: str) -> bool:
        return bool(
            is_local_embedding_url(base_url) and self.marker.get("local_embedding_url") == base_url
        )

    def save_accounting(self) -> None:
        temporary = self.accounting_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.accounting), encoding="utf-8")
        for attempt in range(5):
            try:
                temporary.replace(self.accounting_path)
                return
            except PermissionError:
                # Windows file scanners may briefly hold the destination. Retry only
                # this local atomic write, never the model request or its call charge.
                if os.name != "nt" or attempt == 4:
                    raise
                sleep(0.025 * (attempt + 1))

    def clean(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                str(k): self.clean(v)
                for k, v in value.items()
                if str(k).lower()
                not in {
                    "authorization",
                    "api_key",
                    "token",
                    "cookie",
                    "reasoning_content",
                    "reasoning",
                    "password",
                    "headers",
                }
            }
        if isinstance(value, (tuple, list)):
            return [self.clean(v) for v in value]
        if isinstance(value, str):
            for secret in self.secrets:
                if secret:
                    value = value.replace(secret, "[redacted]")
        return value

    def prune(self) -> None:
        for identifier, trace in list(self.traces.items()):
            if time() - trace["started_at"] > TRACE_SECONDS:
                del self.traces[identifier]
        while len(self.traces) >= MAX_TRACES:
            del self.traces[next(iter(self.traces))]

    def invalidate(self) -> None:
        # Forget/correct cannot leave older prompt copies accessible in diagnostics.
        self.traces.clear()
        if self.current is not None:
            self.current["calls"] = []
            self.current.pop("prepared", None)
            self.traces[self.current["trace_id"]] = self.current

    def discover(self, host: RomanceHost) -> dict[str, Any]:
        return {
            "protocol": SCHEMA,
            "instance_id": self.instance_id,
            "run_id": self.marker["run_id"],
            "pid": os.getpid(),
            "code": self.code,
            "synthetic_data": True,
            "model_mode": host.settings.model_mode,
            "variant": self.marker.get("variant", "full"),
            "model": host.settings.deepseek.model
            if host.settings.model_mode == "api"
            else "offline-demo-v1",
            "config_sha256": hashlib.sha256(host.settings.model_dump_json().encode()).hexdigest(),
            "management": True,
            "process_management": False,
            "expires_at": self.marker["expires_at"],
            "budget": self.marker["budget"],
            "accounting": self.accounting,
            "capabilities": [
                "chat",
                "stream",
                "history",
                "state",
                "trace",
                "correction",
                "forget",
                "event_clock",
            ],
            "clock": {
                "now": self.clock().isoformat(),
                "virtual": bool(self.offset_seconds),
                "coverage": ["event_due_selection", "quiet_hours"],
                "uncovered": [
                    "memory_expiry",
                    "relative_dates",
                    "authentication",
                    "network_timeouts",
                    "safety_cooldowns",
                ],
            },
            "trace_retention_seconds": TRACE_SECONDS,
        }

    @contextmanager
    def turn(self, item: ChatInput) -> Iterator[dict[str, Any]]:
        if not self.lock.acquire(blocking=False):
            raise HTTPException(409, "test instance is replying to another request")
        try:
            with self.capture(item.conversation_id, item.request_id, item.content) as trace:
                yield trace
        finally:
            self.lock.release()

    @contextmanager
    def capture(
        self, conversation_id: str, request_id: str, content: str
    ) -> Iterator[dict[str, Any]]:
        with self.lock:
            if not self.valid() or conversation_id not in self.allowed:
                raise HTTPException(403, "test scope expired or conversation not authorized")
            if self.accounting["turns"] >= self.marker["budget"]["max_turns"]:
                raise HTTPException(429, "test turn budget exhausted")
            self.accounting["turns"] += 1
            self.save_accounting()
            self.prune()
            trace: dict[str, Any] = {
                "trace_id": str(uuid4()),
                "request_id": request_id,
                "conversation_id": conversation_id,
                "input": self.clean(content),
                "instance_id": self.instance_id,
                "code": self.code,
                "started_at": time(),
                "calls": [],
                "status": "running",
            }
            self.current = trace
            self.traces[trace["trace_id"]] = trace
            token = sink.set(self)
            try:
                yield trace
                trace["status"] = "completed"
            except Exception as error:
                trace["status"] = "failed"
                trace["error_type"] = type(error).__name__
                if re.fullmatch(r"[a-z][a-z0-9_]+", str(error)):
                    trace["error_code"] = str(error)
                raise
            finally:
                trace["finished_at"] = time()
                sink.reset(token)
                self.current = None

    def begin_call(self, source: str, payload: dict[str, Any], live: bool) -> dict[str, Any]:
        from companion_agent.llm import MainLLMError

        budget = self.marker["budget"]
        if (
            not self.valid()
            or self.accounting["calls"] >= budget["max_calls"]
            or (live and not self.marker["allow_live"])
            or (live and payload.get("max_tokens", 0) > budget["max_output_tokens"])
        ):
            raise MainLLMError("test_model_budget_or_authorization_exhausted")
        self.accounting["calls"] += 1
        self.accounting["live_calls"] += int(live)
        self.save_accounting()  # A crash/unknown outcome still consumes a call.
        return {
            "source": source,
            "live": live,
            "request": self.clean(payload),
            "call_number": self.accounting["calls"],
            "remaining_seconds": max(0.001, self.marker["expires_at"] - time()),
        }

    def finish_call(self, call: dict[str, Any]) -> None:
        if self.current is not None:
            self.current["calls"].append(self.clean(call))

    def event(self, name: str, value: Any) -> None:
        if self.current is not None:
            self.current[name] = self.clean(value)


def install_routes(app: FastAPI, host: RomanceHost, control: TestControl, authorized: Any) -> None:
    def test_access(request: Request) -> None:
        authorized(request)
        if not control.valid() or not secrets.compare_digest(
            request.headers.get("x-companion-test-token", ""), control.token
        ):
            raise HTTPException(403, "test authorization required")
        control.prune()

    @app.get("/api/testing/discover", dependencies=[Depends(test_access)])
    def discover() -> dict[str, Any]:
        return control.discover(host)

    @app.get("/api/testing/traces/{trace_id}", dependencies=[Depends(test_access)])
    def trace(trace_id: str) -> dict[str, Any]:
        if trace_id not in control.traces:
            raise HTTPException(404, "trace expired, invalidated or unknown")
        return control.traces[trace_id]

    @app.get("/api/testing/traces", dependencies=[Depends(test_access)])
    def find_traces(conversation_id: str, request_id: str) -> list[dict[str, Any]]:
        if conversation_id not in control.allowed:
            raise HTTPException(403, "conversation outside test scope")
        return [
            trace
            for trace in control.traces.values()
            if trace["conversation_id"] == conversation_id and trace["request_id"] == request_id
        ]

    @app.get("/api/testing/state/{conversation}", dependencies=[Depends(test_access)])
    def state(conversation: str) -> dict[str, Any]:
        if conversation not in control.allowed:
            raise HTTPException(403, "conversation outside test scope")
        with host.lock:
            scope = host.scope(conversation)
            # Do not call host.memories(): evaluate_stage can mutate relationship state.
            records = host.memory.store.list_memories(
                host.key.user_id, set(MemoryStatus), scope=scope
            )
            return {
                "memories": [r.model_dump(mode="json") for r in records],
                "states": [
                    r.model_dump(mode="json")
                    for r in host.agent.current_states.snapshot(
                        host.key, conversation, include_inactive=True
                    )
                ]
                if host.agent.current_states
                else [],
                "events": host.continuity.events(conversation),
            }

    @app.post("/api/testing/advance-time", dependencies=[Depends(test_access)])
    def advance_time(seconds: int) -> dict[str, Any]:
        if not 0 < seconds <= 604800 or control.offset_seconds + seconds > 2592000:
            raise HTTPException(422, "bounded business clock only")
        with host.exclusive():
            control.offset_seconds += seconds
            # tick retains wall-clock safety cooldowns; only event due/quiet selection shifts.
            with control.capture(next(iter(control.allowed)), str(uuid4()), "event_tick"):
                host.continuity.tick(control.clock())
            result: dict[str, Any] = control.discover(host)["clock"]
            return result
