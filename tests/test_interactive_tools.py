"""Interactive native MCP uses isolated fixtures, never real accounts or players."""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from companion_agent import app as app_module
from companion_agent import local_runtime
from companion_agent.app import create_app
from companion_agent.automation.models import AutomationConfig, MCPServerConfig
from companion_agent.testing.control import TestControl as SyntheticControl
from companion_agent.testing.driver import ManagedInstance
from tests.test_agent_automation import HEADERS, TOOL, FakeMCP, hub_at


def configuration() -> AutomationConfig:
    return AutomationConfig.model_validate(
        {
            "servers": [
                {
                    "id": "fixture",
                    "label": "Local synthetic tools",
                    "command": sys.executable,
                    "enabled": True,
                }
            ]
        }
    )


def test_interactive_mcp_configure_discover_approve_without_background_services(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = create_app(tmp_path, background_services=False, interactive_tools=True)
    host = app.state.host
    fake = FakeMCP()
    host.tools.client = fake

    def unwanted_background_start() -> None:
        pytest.fail("interactive tools must not start a scheduler or channel")

    monkeypatch.setattr(host.tools.scheduler, "start", unwanted_background_start)
    monkeypatch.setattr(host.channels, "start", unwanted_background_start)
    with TestClient(app, base_url="http://127.0.0.1", headers=HEADERS) as client:
        client.get("/")
        boot = client.get("/api/bootstrap").json()
        settings = boot["settings"] | {"storage_consent": True, "model_consent": True}
        assert client.put("/api/settings", json={"settings": settings}).status_code == 200
        capabilities = client.get("/api/automation").json()["capabilities"]
        assert capabilities == {
            "interactive_tools": True,
            "scheduling": False,
            "netease": sys.platform == "win32",
        }
        response = client.put(
            "/api/automation/config", json=configuration().model_dump(mode="json")
        )
        assert response.status_code == 200
        assert client.post("/api/automation/servers/fixture/connect", json={}).json() == {
            "tools": [TOOL]
        }
        name = next(iter(host.tools.bindings()))
        pending = host.tools.invoke(
            name, {"contact": "synthetic", "text": "hello"}, boot["conversations"][0]["id"], "one"
        )
        assert pending["status"] == "pending" and not fake.calls
        action = pending["action_id"]
        result = client.post(f"/api/automation/actions/{action}/approve", json={}).json()
        assert result["status"] == "succeeded" and len(fake.calls) == 1
        assert client.post(f"/api/automation/actions/{action}/approve", json={}).status_code == 409
        assert len(fake.calls) == 1
        assert client.post("/api/automation/schedules", json={}).status_code == 403
        assert client.put("/api/channels", json={}).status_code == 403
        assert client.post("/api/connection", json={}).status_code == 403
        assert host.tools.invoke("schedule_list", {}, "conversation", "schedule")["status"] == (
            "denied"
        )
        calculation = host.tools.invoke(
            "calculate", {"calculations": [{"name": "sum", "expression": "1 + 2"}]}, "c", "sum"
        )
        assert calculation["status"] == "succeeded"


def test_disabled_native_tools_hide_restored_catalog_and_block_management(tmp_path: Path) -> None:
    app = create_app(tmp_path, background_services=False)
    host = app.state.host
    fake = FakeMCP()
    host.tools.client = fake
    host.settings.storage_consent = True
    host.tools.configure(configuration())
    host.tools.catalog = {"fixture": [TOOL]}
    with TestClient(app, base_url="http://127.0.0.1", headers=HEADERS) as client:
        client.get("/")
        assert client.get("/api/automation").json()["capabilities"] == {
            "interactive_tools": False,
            "scheduling": False,
            "netease": False,
        }
        assert {item["function"]["name"] for item in host.tools.definitions()} == {
            "calculate",
            "local_time",
            # In-app configuration remains available without external tools.
            "app_settings",
            "app_configure",
            "app_experience",
            "app_open",
            "app_undo_settings",
            "app_connect_music",
            "app_open_music",
        }
        assert (
            host.tools.invoke(
                "app_connect_music", {}, host.conversations()[0]["id"], "unavailable"
            )["status"]
            == "denied"
        )
        assert not fake.calls
        assert not host.tools.bindings()
        with pytest.raises(ValueError, match="外部工具"):
            host.tools.discover("fixture")
        assert client.put("/api/automation/config", json={}).status_code == 403
        assert client.post("/api/automation/servers/fixture/connect", json={}).status_code == 403
        assert client.post("/api/automation/actions/old/approve", json={}).status_code == 403
        assert client.post("/api/automation/cancel/none", json={}).status_code == 200
        assert client.get("/api/automation/netease-template").status_code == 403
        assert not fake.calls


def test_runtime_gate_revokes_pending_mcp_without_disabling_calculation(tmp_path: Path) -> None:
    hub, fake, name = hub_at(tmp_path)
    pending = hub.invoke(name, {"contact": "小雨", "text": "test"}, "c", "pending")
    assert pending["status"] == "pending"
    hub.external_available = lambda: False
    with pytest.raises(ValueError):
        hub.approve(pending["action_id"], True)
    assert hub.invoke(name, {"contact": "小雨", "text": "test"}, "c", "new")["status"] == ("denied")
    assert hub.approve(pending["action_id"], False)["status"] == "denied"
    assert hub.invoke("local_time", {}, "c", "time")["status"] == "succeeded"
    assert not fake.calls


def test_scheduling_can_remain_available_when_interactive_mcp_is_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = create_app(tmp_path, background_services=True, interactive_tools=False)
    host = app.state.host
    monkeypatch.setattr(host.tools.scheduler, "start", lambda: None)
    monkeypatch.setattr(host.channels, "start", lambda: None)
    with TestClient(app, base_url="http://127.0.0.1", headers=HEADERS) as client:
        client.get("/")
        boot = client.get("/api/bootstrap").json()
        host.settings.storage_consent = True
        capabilities = client.get("/api/automation").json()["capabilities"]
        assert capabilities["scheduling"] is True
        assert capabilities["interactive_tools"] is False
        assert client.put("/api/automation/config", json={}).status_code == 403
        response = client.post(
            "/api/automation/schedules",
            json={
                "title": "Synthetic reminder",
                "message": "Only an isolated local reminder",
                "at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
                "conversation_id": boot["conversations"][0]["id"],
            },
        )
        assert response.status_code == 200
        assert len(host.tools.store.jobs()) == 1


def test_testing_mode_cannot_enable_interactive_mcp(tmp_path: Path) -> None:
    instance = ManagedInstance(tmp_path / "synthetic")
    control = SyntheticControl(instance.directory, instance.token)
    app = create_app(instance.directory / "data", testing=control, interactive_tools=True)
    with TestClient(app, base_url="http://127.0.0.1", headers=HEADERS) as client:
        client.get("/")
        assert client.get("/api/automation").json()["capabilities"] == {
            "interactive_tools": False,
            "scheduling": False,
            "netease": False,
        }
        assert client.put("/api/automation/config", json={}).status_code == 403
        assert not app.state.host.tools.external_available()


@pytest.mark.parametrize("frozen", [False, True])
def test_netease_template_is_valid_and_uses_the_correct_entrypoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, frozen: bool
) -> None:
    app = create_app(tmp_path, background_services=False, interactive_tools=True)
    with TestClient(app, base_url="http://127.0.0.1", headers=HEADERS) as client:
        client.get("/")
        monkeypatch.setattr(app_module.sys, "platform", "win32")
        monkeypatch.setattr(app_module.sys, "frozen", frozen, raising=False)
        response = client.get("/api/automation/netease-template")
        assert response.status_code == 200
        config = MCPServerConfig.model_validate(response.json())
        assert config.id == "netease" and config.label == "网易云音乐"
        assert config.enabled is False and config.transport == "stdio"
        assert config.command == sys.executable
        assert config.args == (
            ["--mcp-server", "netease"]
            if frozen
            else ["-m", "companion_agent.integrations.netease"]
        )
        assert set(config.tools) == {
            "netease_status",
            "netease_open_app",
            "netease_search_songs",
            "netease_open_song",
            "netease_playback_state",
            "netease_control",
            "netease_seek",
            "netease_account",
            "netease_user_playlists",
            "netease_playlist_songs",
        }
        assert all(rule.mode == "allow" and not rule.arguments for rule in config.tools.values())
        assert config.env == {} and not config.bearer_env


def test_netease_template_is_unavailable_on_other_platforms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = create_app(tmp_path, background_services=False, interactive_tools=True)
    with TestClient(app, base_url="http://127.0.0.1", headers=HEADERS) as client:
        client.get("/")
        monkeypatch.setattr(app_module.sys, "platform", "linux")
        assert client.get("/api/automation").json()["capabilities"]["netease"] is False
        assert client.get("/api/automation/netease-template").status_code == 403


def test_native_mcp_dispatch_needs_no_app_database_and_does_not_forward_parent_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str] | None] = []
    module = ModuleType("companion_agent.integrations.netease")
    module.__dict__["main"] = lambda argv=None: calls.append(argv)
    monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setattr(local_runtime.sys, "platform", "win32")
    monkeypatch.setattr(sys, "argv", ["xinyu-engine.exe", "--mcp-server", "netease"])

    def no_application_runtime(*args: Any, **kwargs: Any) -> None:
        pytest.fail("MCP dispatch must not open the chat database or start the app")

    monkeypatch.setattr(local_runtime, "LocalRuntime", no_application_runtime)
    local_runtime.main()
    assert calls == [[]]


@pytest.mark.parametrize("platform,expected", [("win32", True), ("linux", False)])
def test_local_runtime_enables_only_supported_interactive_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, platform: str, expected: bool
) -> None:
    class Lease:
        def __init__(self, directory: Path) -> None:
            pass

        def close(self) -> None:
            pass

    # Keep the simulated platform local to this module. Mutating the shared sys
    # module would also make the credential store load Windows DLLs on Linux.
    monkeypatch.setattr(local_runtime, "InstanceLease", Lease)
    monkeypatch.setattr(local_runtime, "sys", SimpleNamespace(platform=platform))
    runtime = local_runtime.LocalRuntime(tmp_path)
    try:
        assert runtime.app.state.host.tools.external_available() is expected
        assert runtime.app.state.host.tools.scheduling_available() is False
    finally:
        runtime.stop()
