"""A thin client of the real web application, never an alternate chat implementation."""

from __future__ import annotations

import http.cookiejar
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from companion_agent.testing.control import (
    LEASE_SECONDS,
    SCHEMA,
    fingerprint,
    is_local_embedding_url,
    read_marker,
)


class DriverError(RuntimeError):
    def __init__(self, message: str, evidence: Any = None) -> None:
        super().__init__(message)
        self.evidence = evidence


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


class Client:
    def __init__(
        self, url: str, token: str, *, timeout: float = 180, owns_process: bool = False
    ) -> None:
        parts = urlsplit(url)
        if (
            parts.scheme != "http"
            or parts.hostname != "127.0.0.1"
            or not parts.port
            or parts.username
            or parts.password
            or parts.path not in {"", "/"}
            or parts.query
            or parts.fragment
        ):
            raise ValueError("only an explicit loopback test instance is supported")
        self.url = url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.owns_process = owns_process
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
            NoRedirect(),
        )
        self.identity: dict[str, Any] = {}

    def request(self, method: str, path: str, data: Any = None) -> Any:
        if not path.startswith("/api/") and path != "/":
            raise ValueError("application path required")
        request = urllib.request.Request(
            self.url + path,
            method=method,
            data=None if data is None else json.dumps(data, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Origin": self.url,
                "X-Companion-Client": "local-web",
                "X-Companion-Test-Token": self.token,
            },
        )
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read(8_000_001)
                if len(raw) > 8_000_000:
                    raise DriverError("bounded response exceeded")
        except urllib.error.HTTPError as error:
            raise DriverError(f"HTTP {error.code}: {path}") from None
        if path == "/":
            return None
        if path == "/api/chat/stream":
            events = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line]
            results = [e["result"] for e in events if e.get("type") == "result"]
            if (
                not events
                or events[-1].get("type") != "done"
                or len(results) != 1
                or any(e.get("type") == "error" for e in events)
            ):
                raise DriverError(
                    "stream did not complete and persist a result", {"stream_events": events}
                )
            return {**results[0], "stream_events": events}
        return json.loads(raw)

    def connect(self, expected_run: str | None = None) -> dict[str, Any]:
        self.request("GET", "/")  # Obtain the real HttpOnly cookie, never host.session.
        identity = self.request("GET", "/api/testing/discover")
        if (
            identity.get("protocol") != SCHEMA
            or not identity.get("synthetic_data")
            or (expected_run and identity.get("run_id") != expected_run)
        ):
            raise DriverError("wrong or non-test application instance")
        identity["process_management"] = self.owns_process
        if self.owns_process:
            identity["capabilities"] += ["restart", "stop"]
        self.identity = identity
        return dict(identity)

    def new_session(self) -> str:
        return str(self.request("POST", "/api/conversations", {})["id"])

    def send_message(
        self,
        conversation: str,
        content: str,
        *,
        stream: bool = False,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        request_id = request_id or str(uuid4())
        try:
            result: dict[str, Any] = self.request(
                "POST",
                "/api/chat/stream" if stream else "/api/chat",
                {"conversation_id": conversation, "content": content, "request_id": request_id},
            )
        except DriverError as error:
            evidence = error.evidence or {}
            try:
                evidence["traces"] = self.request(
                    "GET",
                    "/api/testing/traces?conversation_id="
                    + conversation
                    + "&request_id="
                    + request_id,
                )
            except DriverError:
                evidence["trace_status"] = "unavailable_or_expired"
            raise DriverError(str(error), evidence) from None
        result["trace"] = self.inspect_trace(result["trace_id"])
        history = self.read_history(conversation)
        if not any(m["id"] == result["assistant"]["id"] for m in history):
            raise DriverError("response was not found in persisted history")
        if result["assistant"]["reply_to"] != result["user"]["id"]:
            raise DriverError("saved reply refers to a different user turn")
        return result

    def inspect_trace(self, trace_id: str) -> dict[str, Any]:
        result: dict[str, Any] = self.request("GET", "/api/testing/traces/" + trace_id)
        return result

    def read_history(self, conversation: str) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        before = ""
        while True:
            page = self.request(
                "GET", f"/api/conversations/{conversation}/messages?limit=200{before}"
            )
            output = page["messages"] + output
            if not page["has_more"] or not page["messages"]:
                return output
            before = "&before=" + str(page["messages"][0]["sequence"])

    def read_state(self, conversation: str) -> dict[str, Any]:
        result: dict[str, Any] = self.request("GET", "/api/testing/state/" + conversation)
        return result

    def correct_memory(self, conversation: str, memory_id: str, content: str) -> dict[str, Any]:
        result: dict[str, Any] = self.request(
            "PUT",
            "/api/memories/" + memory_id,
            {
                "content": content,
                "conversation_id": conversation,
                "request_id": str(uuid4()),
            },
        )
        return result

    def forget_memory(self, memory_id: str) -> dict[str, Any]:
        result: dict[str, Any] = self.request("POST", f"/api/memories/{memory_id}/forget", {})
        return result

    def update_event(self, event_id: str, status: str, due_at: str | None = None) -> Any:
        return self.request("PUT", "/api/events/" + event_id, {"status": status, "due_at": due_at})

    def advance_time(self, seconds: int) -> Any:
        return self.request("POST", f"/api/testing/advance-time?seconds={seconds}", {})


class ManagedInstance:
    def __init__(
        self,
        root: Path,
        *,
        allow_live: bool = False,
        max_turns: int = 40,
        max_calls: int = 80,
        max_output_tokens: int = 4096,
        timeout: int = 600,
        settings: dict[str, Any] | None = None,
        variant: str = "full",
        local_embedding_url: str | None = None,
    ) -> None:
        if local_embedding_url is not None and not is_local_embedding_url(local_embedding_url):
            raise ValueError("local embedding URL must be http://127.0.0.1:<port>/v1")
        if variant not in {"full", "no_examples", "no_history", "no_old_conditions"}:
            raise ValueError("unknown context experiment")
        if not (
            1 <= max_turns <= 1000
            and 1 <= max_calls <= 2000
            and 128 <= max_output_tokens <= 32768
            and 10 <= timeout <= LEASE_SECONDS
        ):
            raise ValueError("bounded turn/call/output/time quotas are required")
        root = root.absolute()
        if any(p.is_symlink() or p.is_junction() for p in (root, *root.parents)):
            raise ValueError("test root cannot contain links")
        root.mkdir(parents=True, exist_ok=True)
        expire_closed_runs(root)
        self.run_id = str(uuid4())
        self.directory = root / self.run_id
        self.directory.mkdir(mode=0o700)
        self.token = secrets.token_urlsafe(32)
        self.process: subprocess.Popen[bytes] | None = None
        self.client: Client
        self.settings = settings
        self.marker = {
            "protocol": SCHEMA,
            "run_id": self.run_id,
            "root": str(root.resolve()),
            "created_at": time.time(),
            "expires_at": time.time() + timeout,
            "delete_after": time.time() + 86400,
            "allow_live": allow_live,
            "local_embedding_url": local_embedding_url,
            "variant": variant,
            "budget": {
                "max_turns": max_turns,
                "max_calls": max_calls,
                "max_output_tokens": max_output_tokens,
                "max_retries": 0,
                "timeout_seconds": timeout,
            },
        }
        (self.directory / "run.json").write_text(json.dumps(self.marker), encoding="utf-8")
        # Inherit only this user's access on Windows. Credentials remain in process memory.
        if os.name == "nt":
            user = subprocess.check_output(["whoami"], text=True).strip()
            subprocess.run(
                ["icacls", str(self.directory), "/inheritance:r", "/grant:r", f"{user}:(OI)(CI)F"],
                check=True,
                capture_output=True,
            )

    def start(self) -> Client:
        if self.process is not None and self.process.poll() is None:
            raise DriverError("instance already running")
        read_marker(self.directory)
        (self.directory / "closed.json").unlink(missing_ok=True)
        with socket.socket() as available:
            available.bind(("127.0.0.1", 0))
            port = available.getsockname()[1]
        env = {**os.environ, "COMPANION_TEST_TOKEN": self.token, "PYTHONIOENCODING": "utf-8"}
        # Windows venv python.exe is a redirector with a different PID from the server.
        # Launch the real interpreter with this environment's import paths so the retained
        # process handle belongs to the actual service, including for terminate/restart.
        executable = sys.executable
        if os.name == "nt":
            executable = getattr(sys, "_base_executable", sys.executable)
            env["PYTHONPATH"] = os.pathsep.join(sys.path)
        expected_code = fingerprint()
        with (self.directory / "server.log").open("ab") as log:
            self.process = subprocess.Popen(
                [
                    executable,
                    "-m",
                    "companion_agent.testing",
                    "serve",
                    "--run-dir",
                    str(self.directory),
                    "--port",
                    str(port),
                ],
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        self.client = Client(f"http://127.0.0.1:{port}", self.token, timeout=180, owns_process=True)
        deadline = time.monotonic() + 30
        try:
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise DriverError("test server exited; see owned run's server.log")
                try:
                    identity = self.client.connect(self.run_id)
                except (OSError, DriverError):
                    time.sleep(0.1)
                    continue
                if identity["pid"] != self.process.pid or identity["code"] != expected_code:
                    raise DriverError("process or loaded source fingerprint mismatch")
                break
            else:
                raise DriverError("test instance startup timed out")
            if self.settings is not None:
                self.client.request("PUT", "/api/settings", {"settings": self.settings})
                self.settings = None
            elif not (self.directory / "configured").exists():
                settings = self.client.request("GET", "/api/bootstrap")["settings"]
                settings.update(storage_consent=True, model_consent=True)
                self.client.request("PUT", "/api/settings", {"settings": settings})
            (self.directory / "configured").touch()
            self.client.connect(self.run_id)
            return self.client
        except Exception:
            self.stop()
            raise

    def restart(self) -> Client:
        previous = self.client.identity["instance_id"]
        self.stop()
        client = self.start()
        if client.identity["instance_id"] == previous:
            raise DriverError("restart did not create a new application instance")
        return client

    def stop(self) -> None:
        # The retained Popen handle identifies our child. Never kill by port or guessed PID.
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        if self.directory.exists():
            (self.directory / "closed.json").write_text(
                json.dumps({"stopped_at": time.time(), "run_id": self.run_id}), encoding="utf-8"
            )

    def cleanup(self) -> None:
        self.stop()
        cleanup_run(self.directory)


def cleanup_run(directory: Path) -> None:
    marker = read_marker(directory)
    if not (directory / "closed.json").exists():
        raise DriverError("cleanup requires a run closed by its owning driver")
    closed = json.loads((directory / "closed.json").read_text(encoding="utf-8"))
    if closed.get("run_id") != marker["run_id"]:
        raise DriverError("closed run ownership mismatch")
    for folder, directories, filenames in os.walk(directory, followlinks=False):
        for name in [*directories, *filenames]:
            path = Path(folder) / name
            if path.is_symlink() or path.is_junction():
                raise DriverError("cleanup refused a linked path")
    # read_marker checked the canonical root, UUID child and all path components above.
    shutil.rmtree(directory.resolve())


def expire_closed_runs(root: Path) -> None:
    """Apply the advertised export TTL on the next driver invocation, only to closed runs."""
    for directory in root.iterdir():
        if not directory.is_dir() or not (directory / "closed.json").is_file():
            continue
        try:
            marker = read_marker(directory)
            if marker["delete_after"] > time.time():
                continue
            status = "unknown"
            results = directory / "results.json"
            if results.is_file():
                proposed = json.loads(results.read_text(encoding="utf-8")).get("status")
                if proposed in {"passed", "failed", "blocked", "skipped", "not_run"}:
                    status = proposed
            cleanup_run(directory)
            with (root / "retention-receipts.jsonl").open("a", encoding="utf-8") as receipt:
                receipt.write(
                    json.dumps(
                        {"run_id": marker["run_id"], "status": status, "expired_at": time.time()}
                    )
                    + "\n"
                )
        except (OSError, ValueError, KeyError, DriverError):
            # Unknown, active or linked directories are never swept up as test artifacts.
            continue


def report(directory: Path, value: dict[str, Any]) -> None:
    (directory / "results.json").write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# Application test evidence",
        "",
        f"Status: {value['status']}",
        "",
        "This report contains synthetic test data, not agent instructions.",
        "",
        "Offline process results do not assess real language quality.",
        "",
        "```json",
        json.dumps(value["coverage"], ensure_ascii=False, indent=2),
        "```",
        "",
    ]
    for step in value["steps"]:
        lines += [
            f"## Step {step['index']}: {step['operation']} — {step['status']}",
            "",
            "```json",
            json.dumps(step, ensure_ascii=False, indent=2),
            "```",
            "",
        ]
    (directory / "report.md").write_text("\n".join(lines), encoding="utf-8")


def run_scenario(instance: ManagedInstance, scenario: dict[str, Any]) -> dict[str, Any]:
    client = instance.client
    if scenario.get("settings"):
        settings = client.request("GET", "/api/bootstrap")["settings"]
        settings.update(scenario["settings"])
        client.request("PUT", "/api/settings", {"settings": settings})
    conversation = client.new_session()
    steps: list[dict[str, Any]] = []
    for index, step in enumerate(scenario["steps"]):
        operation = step["operation"]
        row: dict[str, Any] = {"index": index, "operation": operation, "input": step}
        try:
            if operation == "new_session":
                conversation = client.new_session()
                result: Any = {"conversation_id": conversation}
            elif operation == "restart":
                client = instance.restart()
                result = client.identity
            elif operation == "send_message":
                result = client.send_message(
                    conversation,
                    step["content"],
                    stream=step.get("stream", False),
                    request_id=step.get("request_id"),
                )
                row["result"] = result
                trace = result["trace"]
                if "expect_goal" in step and (
                    trace.get("prepared", {}).get("final_goal") != step["expect_goal"]
                ):
                    raise DriverError("final response goal mismatch")
                for dimension in step.get("expect_preferences", []):
                    if dimension not in {
                        p["dimension"] for p in trace.get("prepared", {}).get("preferences", [])
                    }:
                        raise DriverError("behavior preference absent from compiled context")
                for dimension in step.get("reject_preferences", []):
                    if dimension in {
                        p["dimension"] for p in trace.get("prepared", {}).get("preferences", [])
                    }:
                        raise DriverError("unexpected preference injected")
                if "expect_reused" in step and result["reused"] != step["expect_reused"]:
                    raise DriverError("request idempotency mismatch")
                for text in step.get("reject_context_text", []):
                    if text in json.dumps(trace.get("calls", []), ensure_ascii=False):
                        raise DriverError("forbidden historical content reached model")
            elif operation in {"correct_memory", "forget_memory"}:
                records = [
                    r
                    for r in client.read_state(conversation)["memories"]
                    if r["status"] == "active" and step["content_match"] in r["content"]
                ]
                if len(records) != 1:
                    raise DriverError("memory edit requires a unique active target")
                identifier = records[0]["id"]
                result = (
                    client.correct_memory(conversation, identifier, step["content"])
                    if operation == "correct_memory"
                    else client.forget_memory(identifier)
                )
            elif operation == "update_event":
                events = client.read_state(conversation)["events"]
                if len(events) != 1:
                    raise DriverError("event update requires a unique target")
                due_at = step.get("due_at")
                if "due_in_seconds" in step:
                    due_at = (
                        datetime.now(UTC) + timedelta(seconds=step["due_in_seconds"])
                    ).isoformat()
                result = client.update_event(events[0]["id"], step["status"], due_at)
            elif operation == "advance_time":
                result = client.advance_time(step["seconds"])
            elif operation in {"read_state", "read_history"}:
                result = getattr(client, operation)(conversation)
                if operation == "read_state":
                    for text in step.get("expect_active", []):
                        if not any(
                            text in r["content"] and r["status"] == "active"
                            for r in result["memories"]
                        ):
                            raise DriverError("expected active memory missing")
                    for text in step.get("reject_active", []):
                        if any(
                            text in r["content"] and r["status"] == "active"
                            for r in result["memories"]
                        ):
                            raise DriverError("retired memory still active")
                    if "expect_event_status" in step and not all(
                        e["status"] == step["expect_event_status"] and not e["delivered_at"]
                        for e in result["events"]
                    ):
                        raise DriverError("cancelled event was delivered or changed status")
            else:
                raise DriverError("unknown scenario operation")
            row.update(status="passed", result=result)
        except Exception as error:
            row.update(
                status="failed",
                reason=str(error) if isinstance(error, DriverError) else type(error).__name__,
            )
            if isinstance(error, DriverError) and error.evidence:
                row["evidence"] = error.evidence
        steps.append(row)
    identity = client.connect(instance.run_id)
    value = {
        "scenario": scenario.get("name", "unnamed"),
        "scenario_version": scenario.get("version", 1),
        "started_at": instance.marker["created_at"],
        "finished_at": time.time(),
        "identity": identity,
        "steps": steps,
        "coverage": {
            "backend": "failed" if any(s["status"] == "failed" for s in steps) else "passed",
            "language_quality": "not_run" if identity["model_mode"] == "api" else "blocked",
            "language_quality_reason": "requires authorized real model and evidence review",
            "web": "not_run",
            "flutter_desktop_mobile": "not_run",
            "cost": "unknown; all adapter calls counted, no automatic retries",
        },
        "status": "failed"
        if any(s["status"] == "failed" for s in steps)
        else "blocked"
        if scenario.get("require_language_quality", True)
        else "passed",
    }
    report(instance.directory, value)
    return value
