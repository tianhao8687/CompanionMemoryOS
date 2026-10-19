"""Synthetic phone boundary: no attached phones, real accounts or model calls."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from jsonschema import ValidationError

from companion_agent.app import create_app
from companion_agent.automation.hub import digest
from companion_agent.automation.mcp_client import MCPFailure
from companion_agent.automation.models import AutomationConfig, MCPServerConfig
from companion_agent.automation.native_client import NativeClients
from companion_agent.integrations.droid_android import AndroidPhoneClient
from companion_agent.integrations.netease_android import AndroidMusicClient
from companion_agent.integrations.netease_catalog import NetEaseCatalog
from tests.test_agent_automation import HEADERS


def tool(name: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "name": name,
        "description": "Synthetic SDK tool",
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": required,
        },
    }


class Phone:
    def __init__(self) -> None:
        self.supported = True
        self.calls: list[dict[str, Any]] = []
        self.result: dict[str, Any] = {"status": "succeeded"}
        self.catalog = [
            tool(
                "set_volume",
                {
                    "stream": {"type": "string", "enum": ["media", "alarm"]},
                    "level": {"type": "integer", "minimum": 0},
                },
                ["level"],
            ),
            tool("query_screen", {"max_nodes": {"type": "integer", "maximum": 2000}}, []),
            tool("tap", {"x": {"type": "integer"}, "y": {"type": "integer"}}, ["x", "y"]),
        ]

    def __call__(self, operation: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
        assert 0 < timeout <= 20000
        if operation == "state":
            return {"supported": self.supported, "permissions": {"accessibility": False}}
        if operation == "catalog":
            return {"supported": self.supported, "tools": copy.deepcopy(self.catalog)}
        assert operation == "call"
        self.calls.append(payload)
        return {**self.result, "observed": len(self.calls)}


def test_upstream_subset_is_unchanged_and_has_license() -> None:
    root = Path(__file__).resolve().parents[1] / "clients/xinyu_flutter/android/droid_mcp"
    manifest = json.loads((root / "UPSTREAM.json").read_text(encoding="utf-8"))
    assert manifest["revision"] == "38723823a05852d3b2a655f48d817fc4bd3b406c"
    assert "Apache License" in (root / "LICENSE").read_text(encoding="utf-8")
    assert (root.parents[1] / "assets/licenses/droid-mcp.txt").read_bytes() == (
        root / "LICENSE"
    ).read_bytes()
    for entry in manifest["files"]:
        assert hashlib.sha256((root / entry["path"]).read_bytes()).hexdigest() == entry["sha256"]


def test_native_routing_keeps_phone_and_music_separate(tmp_path: Path) -> None:
    phone = Phone()
    music_calls = []

    def music(name: str, args: dict[str, Any]) -> dict[str, Any]:
        music_calls.append(name)
        return {"status": "succeeded"}

    catalog_calls = []

    def metadata(request: httpx.Request) -> httpx.Response:
        catalog_calls.append(request.url.path)
        assert request.url.host == "music.163.com"
        return httpx.Response(200, json={"code": 200, "playlist": [], "more": False})

    app = create_app(
        tmp_path,
        background_services=False,
        interactive_tools=True,
        native_phone=AndroidPhoneClient(phone),
        native_music=AndroidMusicClient(music, NetEaseCatalog(httpx.MockTransport(metadata))),
    )
    router = app.state.host.tools.client
    assert isinstance(router, NativeClients)
    server = MCPServerConfig(id="netease", label="music", transport="native", enabled=True)
    catalog = router.discover(server)
    status = next(t for t in catalog if t["name"] == "netease_status")
    assert router.call(server, "netease_status", {}, status)["status"] == "succeeded"
    playlists = next(t for t in catalog if t["name"] == "netease_user_playlists")
    result = router.call(server, playlists["name"], {"user_id": "8"}, playlists)
    assert result["data"]["playlists"] == [] and catalog_calls == ["/api/user/playlist"]
    assert music_calls == ["netease_status"] and not phone.calls
    external = MCPServerConfig(id="external", label="external", command="must-not-run")
    with pytest.raises(MCPFailure):
        router.discover(external)


@pytest.mark.parametrize(
    "args", [{"stream": "alarm", "level": 0}, {"level": True}, {"level": 3, "extra": "ignored?"}]
)
def test_phone_rejects_invalid_or_expanded_capabilities_before_jni(args: dict[str, Any]) -> None:
    phone = Phone()
    client = AndroidPhoneClient(phone)
    server = client.template()
    expected = next(t for t in client.discover(server) if t["name"] == "set_volume")
    with pytest.raises(ValidationError):
        client.call(server, "set_volume", args, expected)
    assert not phone.calls


def test_contract_change_target_and_budget_cannot_be_bypassed() -> None:
    phone = Phone()
    client = AndroidPhoneClient(phone)
    server = client.template()
    expected = next(t for t in client.discover(server) if t["name"] == "tap")
    with pytest.raises(ValidationError):
        client.call(server, "tap", {"x": 2, "y": 3}, expected)
    args = {"x": 2, "y": 3, "expected_package": "synthetic.app"}
    with pytest.raises(MCPFailure):
        client.call(server, "tap", args, expected, timeout=0)
    phone.catalog[-1]["description"] = "Changed contract"
    with pytest.raises(MCPFailure):
        client.call(server, "tap", args, expected)
    assert not phone.calls


def test_unknown_result_and_oversized_result_are_not_reported_as_success() -> None:
    phone = Phone()
    client = AndroidPhoneClient(phone)
    server = client.template()
    expected = client.discover(server)[0]
    for result in ({"status": "queued"}, {"status": "succeeded", "text": "x" * 13000}):
        phone.result = result
        assert client.call(server, "set_volume", {"level": 3}, expected)["status"] == "uncertain"
    assert len(phone.calls) == 2  # One call per explicit request, no retries.


def test_phone_disabled_on_unsupported_device() -> None:
    phone = Phone()
    phone.supported = False
    client = AndroidPhoneClient(phone)
    assert client.state()["supported"] is False
    with pytest.raises(MCPFailure):
        client.template()


@pytest.mark.parametrize(
    "arguments",
    [
        {"timings": [0, 80, 200, 80], "repeat": 0},
        {"timings": [0, 10000]},
        {"timings": [0, 80.5, 200, 80]},
        {"timings": [0, "80", 200, 80]},
        {"timings": [0, 80, 200, 80], "extra": True},
    ],
)
def test_haptics_reject_expanded_waveforms_before_jni(arguments: dict[str, Any]) -> None:
    phone = Phone()
    phone.catalog.append(tool("vibrate_pattern", {"timings": {"type": "array"}}, ["timings"]))
    native = AndroidPhoneClient(phone)
    server = native.template()
    expected = next(t for t in native.discover(server) if t["name"] == "vibrate_pattern")
    assert server.tools["vibrate_pattern"].mode == "ask"
    with pytest.raises(ValidationError):
        native.call(server, "vibrate_pattern", arguments, expected)
    assert not phone.calls


def test_haptics_use_existing_toolhub_consent_and_do_not_enable_on_upgrade(tmp_path: Path) -> None:
    phone = Phone()
    phone.catalog.extend(
        [
            tool("vibrate_pattern", {"timings": {"type": "array"}}, ["timings"]),
            tool("cancel_vibration", {}, []),
        ]
    )
    native = AndroidPhoneClient(phone)
    app = create_app(
        tmp_path, background_services=False, interactive_tools=True, native_phone=native
    )
    hub = app.state.host.tools
    server = native.template()
    server.enabled = True
    del server.tools["vibrate_pattern"]
    del server.tools["cancel_vibration"]
    hub.configure(AutomationConfig(servers=[server]))
    hub.discover("droid")
    name = f"mcp_droid_{digest('vibrate_pattern')[:12]}"
    assert name not in hub.bindings()
    config = AutomationConfig(servers=[native.template()])
    config.servers[0].enabled = True
    hub.configure(config)
    hub.discover("droid")
    args = {"timings": [0, 80, 200, 80]}
    assert hub.inspect(name, args)[0] == "ask"
    assert not phone.calls
    expected = next(t for t in native.discover(server) if t["name"] == "vibrate_pattern")
    assert native.call(server, "vibrate_pattern", args, expected)["status"] == "succeeded"
    expected_stop = next(t for t in native.discover(server) if t["name"] == "cancel_vibration")
    assert native.call(server, "cancel_vibration", {}, expected_stop)["status"] == "succeeded"
    assert [call["name"] for call in phone.calls] == ["vibrate_pattern", "cancel_vibration"]


def test_existing_connection_does_not_implicitly_enable_new_ui_tools(tmp_path: Path) -> None:
    phone = Phone()
    phone.catalog.extend(
        [
            tool("gesture", {"points": {"type": "array"}}, ["points"]),
            tool("long_click_node", {"text": {"type": "string"}}, []),
        ]
    )
    native = AndroidPhoneClient(phone)
    app = create_app(
        tmp_path, background_services=False, interactive_tools=True, native_phone=native
    )
    hub = app.state.host.tools
    server = native.template()
    server.enabled = True
    del server.tools["gesture"]
    del server.tools["long_click_node"]
    hub.configure(AutomationConfig(servers=[server]))
    hub.discover("droid")
    assert f"mcp_droid_{digest('gesture')[:12]}" not in hub.bindings()
    assert f"mcp_droid_{digest('long_click_node')[:12]}" not in hub.bindings()


def test_gestures_default_off_require_target_and_reject_malformed_paths() -> None:
    phone = Phone()
    phone.catalog.append(
        tool(
            "gesture",
            {
                "points": {"type": "array"},
                "duration_ms": {"type": "integer", "minimum": 10, "maximum": 3000},
            },
            ["points"],
        )
    )
    phone.catalog.append(tool("long_click_node", {"text": {"type": "string"}}, []))
    client = AndroidPhoneClient(phone)
    server = client.template()
    assert server.tools["gesture"].mode == server.tools["long_click_node"].mode == "off"
    expected = next(t for t in client.discover(server) if t["name"] == "gesture")
    for args in (
        {"points": [[1, 2], [3, 4]]},
        {"points": [[1, 2]], "expected_package": "synthetic.app"},
        {"points": [[1, 2, 3], [4, 5]], "expected_package": "synthetic.app"},
        {"points": [[1, 2]] * 17, "expected_package": "synthetic.app"},
        {"points": [[-1, 2], [3, 4]], "expected_package": "synthetic.app"},
        {"points": [[1, 2], [3, 4]], "expected_package": "synthetic.app", "duration_ms": 5000},
    ):
        with pytest.raises(ValidationError):
            client.call(server, "gesture", args, expected)
    assert not phone.calls
    result = client.call(
        server,
        "gesture",
        {"points": [[1, 2], [3, 4]], "expected_package": "synthetic.app"},
        expected,
    )
    assert result["status"] == "succeeded" and len(phone.calls) == 1


def test_approval_deduplication_revocation_and_screen_reobservation(tmp_path: Path) -> None:
    phone = Phone()
    native = AndroidPhoneClient(phone)
    app = create_app(
        tmp_path, background_services=False, interactive_tools=True, native_phone=native
    )
    with TestClient(app, base_url="http://127.0.0.1", headers=HEADERS) as client:
        client.get("/")
        boot = client.get("/api/bootstrap").json()
        settings = boot["settings"] | {"storage_consent": True, "model_consent": True}
        assert client.put("/api/settings", json={"settings": settings}).status_code == 200
        template = client.get("/api/automation/droid-template").json()
        assert template["tools"]["tap"]["mode"] == "off"
        assert template["tools"]["set_volume"]["mode"] == "ask"
        template["enabled"] = True
        config = {"servers": [template]}
        assert client.put("/api/automation/config", json=config).status_code == 200
        assert client.post("/api/automation/servers/droid/connect", json={}).status_code == 200
        state = client.get("/api/automation").json()
        assert state["phone"]["supported"] and not phone.calls
        hub = app.state.host.tools
        conversation = boot["conversations"][0]["id"]
        volume = f"mcp_droid_{digest('set_volume')[:12]}"
        query = f"mcp_droid_{digest('query_screen')[:12]}"
        tap = f"mcp_droid_{digest('tap')[:12]}"
        pending = hub.invoke(volume, {"level": 3}, conversation, "one")
        assert pending["status"] == "pending" and not phone.calls
        assert hub.approve(pending["action_id"], True)["status"] == "succeeded"
        assert hub.invoke(volume, {"level": 3}, conversation, "one")["reused"]
        assert len(phone.calls) == 1
        # Disabling a connection invalidates pending authorization.
        pending = hub.invoke(volume, {"level": 4}, conversation, "two")
        template["enabled"] = False
        hub.configure(AutomationConfig.model_validate(config))
        with pytest.raises(ValueError):
            hub.approve(pending["action_id"], True)
        assert len(phone.calls) == 1
        template["enabled"] = True
        for name in ("tap", "query_screen"):
            template["tools"][name]["mode"] = "allow"
        hub.configure(AutomationConfig.model_validate(config))
        args = {"expected_package": "synthetic.app"}
        assert hub.invoke(tap, {**args, "x": 1, "y": 1}, conversation, "ui")["status"] == "denied"
        first = hub.invoke(query, args, conversation, "ui")
        assert hub.invoke(query, args, conversation, "ui")["reused"]
        hub.invoke(tap, {**args, "x": 1, "y": 1}, conversation, "ui")
        assert hub.invoke(tap, {**args, "x": 1, "y": 1}, conversation, "ui")["reused"]
        after = hub.invoke(query, args, conversation, "ui")
        assert after["action_id"] != first["action_id"] and not after.get("reused")
        # A fresh observation permits a deliberate next click at the same place,
        # while retries of that next step must still execute only once.
        assert not hub.invoke(tap, {**args, "x": 1, "y": 1}, conversation, "ui").get("reused")
        assert hub.invoke(tap, {**args, "x": 1, "y": 1}, conversation, "ui")["reused"]
        assert len(phone.calls) == 5
        config["loop"] = {"enabled": False}
        hub.configure(AutomationConfig.model_validate(config))
        assert hub.invoke(volume, {"level": 2}, conversation, "off")["status"] == "denied"
        assert len(phone.calls) == 5


def test_desktop_cannot_use_android_native_template(tmp_path: Path) -> None:
    app = create_app(tmp_path, background_services=False, interactive_tools=True)
    with TestClient(app, base_url="http://127.0.0.1", headers=HEADERS) as client:
        client.get("/")
        assert client.get("/api/automation/droid-template").status_code == 403
        assert client.get("/api/automation/phone-template").json()["transport"] == "stdio"
