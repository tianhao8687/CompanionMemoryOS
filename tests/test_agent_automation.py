from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event
from typing import Any

import pytest
from fastapi.testclient import TestClient

from companion_agent.app import create_app
from companion_agent.automation.hub import ToolHub
from companion_agent.automation.loop import AgentLoop, ModelStep, ToolCall
from companion_agent.automation.mcp_client import MCPClient
from companion_agent.automation.models import (
    AutomationConfig,
    MCPServerConfig,
    ScheduleInput,
)
from companion_agent.context import ChatMessage
from companion_agent.deepseek import DeepSeekConfig, DeepSeekLLM
from companion_agent.llm import ModelResponse
from companion_memoryos.config import load_config
from companion_memoryos.database import Database
from tests.test_deepseek import provider

FIXTURE = Path(__file__).parent / "fixtures" / "mcp_demo.py"
HEADERS = {"X-Companion-Client": "local-web", "Origin": "http://127.0.0.1"}
TOOL = {
    "name": "echo_contact",
    "description": "Send to a selected contact",
    "inputSchema": {
        "type": "object",
        "properties": {"contact": {"type": "string"}, "text": {"type": "string"}},
        "required": ["contact", "text"],
        "additionalProperties": False,
    },
}


class FakeMCP(MCPClient):
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def discover(self, server: MCPServerConfig) -> list[dict[str, Any]]:
        return [TOOL]

    def call(
        self,
        server: MCPServerConfig,
        name: str,
        arguments: dict[str, Any],
        expected: dict[str, Any],
        timeout: float | None = None,
    ) -> dict[str, Any]:
        self.calls.append(arguments)
        return {"status": "succeeded", "data": arguments}


def hub_at(path: Path, *, mode: str = "ask") -> tuple[ToolHub, FakeMCP, str]:
    database = Database(path, load_config())
    database.initialize()
    client = FakeMCP()
    hub = ToolHub(database, client)
    hub.configure(
        AutomationConfig.model_validate(
            {
                "servers": [
                    {
                        "id": "test",
                        "label": "test tools",
                        "transport": "stdio",
                        "command": sys.executable,
                        "enabled": True,
                        "tools": {
                            "echo_contact": {"mode": mode, "arguments": {"contact": ["小雨"]}}
                        },
                    }
                ]
            }
        )
    )
    hub.discover("test")
    return hub, client, next(iter(hub.bindings()))


def test_permissions_approval_and_idempotency(tmp_path: Path) -> None:
    hub, client, name = hub_at(tmp_path)
    args = {"contact": "小雨", "text": "晚安"}
    denied = hub.invoke(name, {**args, "contact": "其他人"}, "conversation", "one")
    assert denied["status"] == "denied" and client.calls == []
    pending = hub.invoke(name, args, "conversation", "one")
    assert pending["status"] == "pending" and client.calls == []
    assert hub.invoke(name, args, "conversation", "one")["action_id"] == pending["action_id"]
    assert hub.approve(pending["action_id"], True)["status"] == "succeeded"
    assert hub.invoke(name, args, "conversation", "one")["reused"]
    with pytest.raises(ValueError):
        hub.approve(pending["action_id"], True)
    assert len(client.calls) == 1


def test_approval_does_not_survive_scope_or_schema_change(tmp_path: Path) -> None:
    hub, client, name = hub_at(tmp_path)
    pending = hub.invoke(name, {"contact": "小雨", "text": "hello"}, "c", "r")
    config = hub.config.model_copy(deep=True)
    config.servers[0].args = ["different.py"]
    hub.configure(config)
    with pytest.raises(ValueError):
        hub.approve(pending["action_id"], True)
    assert not client.calls
    assert hub.approve(pending["action_id"], False)["status"] == "denied"


def test_unknown_tool_schema_external_refs_and_storage_revocation(tmp_path: Path) -> None:
    hub, client, name = hub_at(tmp_path, mode="allow")
    assert hub.invoke("unknown", {}, "c", "r")["status"] == "denied"
    assert hub.invoke(name, {"contact": "小雨", "text": 100}, "c", "r")["status"] == "denied"
    hub.catalog["test"][0] = {**TOOL, "inputSchema": {"$ref": "https://example.invalid/schema"}}
    assert hub.invoke(name, {"contact": "小雨", "text": "hi"}, "c", "r")["status"] == "denied"
    hub.available = lambda: False
    assert hub.invoke("local_time", {}, "c", "r")["status"] == "denied"
    assert not client.calls


def test_crash_recovery_never_replays_unknown_effect(tmp_path: Path) -> None:
    hub, client, name = hub_at(tmp_path)
    result = hub.invoke(name, {"contact": "小雨", "text": "hi"}, "c", "r")
    with hub.store.database.connection() as db:
        db.execute("UPDATE agent_actions SET status='running' WHERE id=?", (result["action_id"],))
    hub.store.recover()
    again = hub.invoke(name, {"contact": "小雨", "text": "hi"}, "c", "r")
    assert again["status"] == "uncertain" and not client.calls


def test_schedules_persist_coalesce_and_retain_local_clock(tmp_path: Path) -> None:
    hub, _, _ = hub_at(tmp_path)
    due = datetime.now(UTC) + timedelta(minutes=5)
    item = ScheduleInput(
        title="喝水", message="喝一杯水", at=due, repeat="daily", conversation_id="c"
    )
    result = hub.scheduler.create(item, "stable-key")
    assert hub.scheduler.create(item, "stable-key")["job_id"] == result["job_id"]
    restarted = ToolHub(hub.store.database)
    later = due + timedelta(days=3, seconds=1)
    restarted.scheduler.tick(later)
    restarted.scheduler.tick(later)
    assert len(restarted.store.notifications()) == 1
    job = restarted.store.jobs()[0]
    assert job["status"] == "active"
    assert datetime.fromisoformat(job["next_run"]) == due + timedelta(days=4)
    restarted.scheduler.change(job["id"], "paused")
    restarted.scheduler.tick(later + timedelta(days=10))
    assert len(restarted.store.notifications()) == 1


def test_scheduled_external_action_waits_for_approval(tmp_path: Path) -> None:
    hub, client, name = hub_at(tmp_path)
    due = datetime.now(UTC) + timedelta(minutes=5)
    item = ScheduleInput(
        title="晚安",
        message="发晚安",
        at=due,
        conversation_id="c",
        tool_name=name,
        arguments={"contact": "小雨", "text": "晚安"},
    )
    hub.scheduler.create(item, "external-job")
    hub.scheduler.tick(due + timedelta(seconds=1))
    assert hub.store.jobs()[0]["status"] == "paused"
    assert hub.store.actions()[0]["status"] == "pending"
    assert not client.calls


class ScriptModel:
    def __init__(
        self, name: str = "local_time", args: dict[str, Any] | None = None, forever: bool = False
    ) -> None:
        self.name = name
        self.args = args or {}
        self.forever = forever
        self.histories: list[list[dict[str, Any]]] = []

    def generate(self, messages: list[ChatMessage]) -> ModelResponse:
        return ModelResponse(text="plain", model="test")

    def generate_step(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], timeout: float
    ) -> ModelStep:
        self.histories.append(list(messages))
        if len(self.histories) == 1 or self.forever:
            call = ToolCall(
                id=f"call-{len(self.histories)}", name=self.name, arguments=json.dumps(self.args)
            )
            return ModelStep(
                message={
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {"name": call.name, "arguments": call.arguments},
                        }
                    ],
                },
                calls=[call],
                model="test",
            )
        return ModelStep(
            message={"role": "assistant", "content": "完成"}, text="完成", model="test"
        )


def test_loop_observes_tool_result_and_stops(tmp_path: Path) -> None:
    hub, _, _ = hub_at(tmp_path)
    model = ScriptModel()
    loop = AgentLoop(model, hub)
    with loop.run("c", "r") as run:
        response = loop.generate([ChatMessage(role="user", content="现在几点")])
    assert response.text == "完成" and run.steps == 2 and run.tool_calls == 1
    assert model.histories[1][-1]["role"] == "tool"
    assert json.loads(model.histories[1][-1]["content"])["status"] == "succeeded"


def test_loop_limits_repeated_calls_and_cancellation(tmp_path: Path) -> None:
    hub, _, _ = hub_at(tmp_path)
    hub.config.loop.max_steps = 2
    loop = AgentLoop(ScriptModel(forever=True), hub)
    with loop.run("c", "r") as run:
        assert "上限" in loop.generate([ChatMessage(role="user", content="hello")]).text
    assert run.steps == 2 and len(hub.store.actions()) == 1
    with loop.run("c", "cancelled") as cancelled:
        assert loop.cancel("cancelled")
        assert "停止" in loop.generate([ChatMessage(role="user", content="hello")]).text
    assert cancelled.steps == 0 and not loop.cancel("unknown")


def test_loop_pending_never_claims_execution(tmp_path: Path) -> None:
    hub, client, name = hub_at(tmp_path)
    loop = AgentLoop(ScriptModel(name, {"contact": "小雨", "text": "晚安"}), hub)
    with loop.run("c", "r") as run:
        response = loop.generate([ChatMessage(role="user", content="发晚安")])
    assert "尚未执行" in response.text and run.status == "pending" and not client.calls


def test_external_timeout_is_not_retried(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    hub, client, name = hub_at(tmp_path, mode="allow")
    attempts: list[str] = []

    def fail(*args: Any, **kwargs: Any) -> dict[str, Any]:
        attempts.append("called")
        raise TimeoutError("private provider data")

    monkeypatch.setattr(client, "call", fail)
    args = {"contact": "小雨", "text": "晚安"}
    assert hub.invoke(name, args, "c", "r")["status"] == "uncertain"
    assert hub.invoke(name, args, "c", "r")["reused"]
    assert attempts == ["called"]
    assert "private provider data" not in json.dumps(hub.store.actions())


def test_denial_still_possible_after_capabilities_disabled(tmp_path: Path) -> None:
    hub, _, name = hub_at(tmp_path)
    pending = hub.invoke(name, {"contact": "小雨", "text": "hi"}, "c", "r")
    hub.config.loop.enabled = False
    assert hub.approve(pending["action_id"], False)["status"] == "denied"
    assert hub.store.actions()[0]["result"]["status"] == "denied"


def test_token_budget_stops_before_external_action(tmp_path: Path) -> None:
    hub, client, name = hub_at(tmp_path, mode="allow")

    class OverBudget(ScriptModel):
        def generate_step(
            self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], timeout: float
        ) -> ModelStep:
            result = super().generate_step(messages, tools, timeout)
            result.total_tokens = 100000
            return result

    loop = AgentLoop(OverBudget(name, {"contact": "小雨", "text": "hello"}), hub)
    with loop.run("c", "r") as run:
        loop.generate([ChatMessage(role="user", content="hello")])
    assert run.status == "limited" and not client.calls


def test_deepseek_tool_and_thinking_wire_contract() -> None:
    body = {
        "model": "deepseek-test",
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "content": None,
                    "reasoning_content": "private reasoning",
                    "tool_calls": [
                        {
                            "id": "one",
                            "type": "function",
                            "function": {"name": "local_time", "arguments": "{}"},
                        }
                    ],
                },
            }
        ],
    }
    with provider(body=body) as (url, requests):
        model = DeepSeekLLM(DeepSeekConfig(base_url=url, thinking="enabled"), api_key="test")
        step = model.generate_step([{"role": "user", "content": "时间"}], [], 5)
    assert step.calls[0].name == "local_time"
    assert step.message["reasoning_content"] == "private reasoning"
    assert requests[0]["body"]["thinking"] == {"type": "enabled"}
    assert requests[0]["body"]["tool_choice"] == "auto"


def test_real_stdio_mcp_discovery_call_and_definition_pin() -> None:
    server = MCPServerConfig(
        id="stdio", label="test", command=sys.executable, args=[str(FIXTURE)], enabled=True
    )
    client = MCPClient()
    catalog = client.discover(server)
    tool = next(t for t in catalog if t["name"] == "echo_contact")
    result = client.call(server, tool["name"], {"contact": "test", "text": "hello"}, tool)
    assert result["status"] == "succeeded" and "hello" in result["text"]
    unknown = next(t for t in catalog if t["name"] == "uncertain")
    assert client.call(server, "uncertain", {}, unknown)["status"] == "uncertain"
    with pytest.raises(Exception, match="MCP"):
        client.call(
            server,
            tool["name"],
            {"contact": "test", "text": "hi"},
            {**tool, "description": "changed"},
        )


@pytest.mark.parametrize("transport,path", [("streamable-http", "/mcp"), ("sse", "/sse")])
def test_real_remote_mcp_transports(transport: str, path: str) -> None:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    process = subprocess.Popen(
        [sys.executable, str(FIXTURE), "--transport", transport, "--port", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    break
            except OSError:
                Event().wait(0.1)
        server = MCPServerConfig(
            id="http",
            label="test",
            transport=("streamable_http" if transport == "streamable-http" else "sse"),
            url=f"http://127.0.0.1:{port}{path}",
            enabled=True,
        )
        client = MCPClient()
        tool = next(t for t in client.discover(server) if t["name"] == "echo_contact")
        assert (
            client.call(server, tool["name"], {"contact": "test", "text": "hello"}, tool)["status"]
            == "succeeded"
        )
    finally:
        process.terminate()
        process.wait(timeout=10)


def test_app_loop_schedule_endpoints_and_authentication(tmp_path: Path) -> None:
    model = ScriptModel(
        "schedule_create",
        {
            "title": "喝水",
            "message": "喝水啦",
            "at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        },
    )
    app = create_app(tmp_path, llm=model)
    with TestClient(app, base_url="http://127.0.0.1", headers=HEADERS) as client:
        assert client.get("/api/automation").status_code == 401
        client.get("/")
        bootstrap = client.get("/api/bootstrap").json()
        config = bootstrap["settings"]
        config.update(storage_consent=True, model_consent=True)
        assert client.put("/api/settings", json={"settings": config}).status_code == 200
        conversation = bootstrap["conversations"][0]["id"]
        response = client.post(
            "/api/chat",
            json={
                "conversation_id": conversation,
                "request_id": "one",
                "content": "一小时后提醒喝水",
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["execution"]["tool_calls"] == 1
        data = client.get("/api/automation").json()
        assert len(data["jobs"]) == 1
        assert data["jobs"][0]["data"]["conversation_id"] == conversation
        assert (
            client.post(
                f"/api/automation/schedules/{data['jobs'][0]['id']}/cancelled", json={}
            ).status_code
            == 200
        )
        assert client.get("/api/automation/phone-template").json()["command"] == sys.executable


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/mcp",
        "https://u:secret@example.com/mcp",
        "https://example.com/mcp?token=secret",
    ],
)
def test_remote_mcp_credentials_and_plaintext_rejected(url: str) -> None:
    with pytest.raises(ValueError):
        MCPServerConfig(id="x", label="x", transport="streamable_http", url=url)
