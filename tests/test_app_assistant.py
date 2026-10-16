from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from companion_agent.app import create_app
from companion_agent.automation.loop import ModelStep, ToolCall
from companion_agent.automation.models import MCPServerConfig
from companion_agent.integrations.netease_android import AndroidMusicClient
from companion_agent.llm import MainLLMError
from companion_agent.offline import OfflineModel
from companion_agent.romance import SettingsUpdate
from tests.test_agent_automation import HEADERS, FakeMCP


class ScriptedSettingsModel(OfflineModel):
    """Deterministic protocol fixture, no real model or external actions."""

    def __init__(self, name: str, arguments: dict[str, Any]) -> None:
        self.name, self.arguments = name, arguments
        self.calls = 0

    def generate_step(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], timeout: float
    ) -> ModelStep:
        self.calls += 1
        if messages[-1]["role"] == "tool":
            return ModelStep(
                message={"role": "assistant", "content": "已处理。"},
                text="已处理。",
                model="scripted",
                total_tokens=10,
            )
        assert self.name in {t["function"]["name"] for t in tools}
        call = ToolCall(id="config", name=self.name, arguments=json.dumps(self.arguments))
        return ModelStep(
            message={
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {"name": call.name, "arguments": call.arguments},
                    }
                ],
            },
            calls=[call],
            model="scripted",
            total_tokens=10,
        )


def setup_host(host: Any) -> str:
    host.save_settings(
        SettingsUpdate(
            settings=host.settings.model_copy(
                update={
                    "storage_consent": True,
                    "model_consent": True,
                }
            )
        )
    )
    return str(host.conversations()[0]["id"])


def test_chat_tools_save_refresh_reuse_and_restart(tmp_path: Path) -> None:
    model = ScriptedSettingsModel(
        "app_configure",
        {
            "changes": {
                "companion_name": "小岚",
                "style": "custom",
                "custom_style": "喜欢散步的虚构朋友。",
                "font_size": "large",
            }
        },
    )
    app = create_app(tmp_path, llm=model, background_services=False)
    host = app.state.host
    with TestClient(app, base_url="http://127.0.0.1", headers=HEADERS) as client:
        client.get("/")
        conversation = setup_host(host)
        # External tool switch does not block internal app configuration.
        host.tools.config.loop.enabled = False
        assert all(t["function"]["name"].startswith("app_") for t in host.tools.definitions())
        body = {
            "conversation_id": conversation,
            "request_id": "persona-fixture",
            "content": "改成小岚，喜欢散步的虚构朋友，字体调大。",
        }
        response = client.post("/api/chat", json=body)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["configuration"]["settings"]["companion_name"] == "小岚"
        assert result["configuration"]["settings"]["font_size"] == "large"
        assert result["execution"]["tool_calls"] == 1
        assert model.calls == 2
        assert client.post("/api/chat", json=body).json()["reused"]
        assert model.calls == 2
        assert len(host.tools.store.actions(conversation)) == 1
    restarted = create_app(tmp_path, background_services=False)
    with TestClient(restarted):
        assert restarted.state.host.settings.custom_style == "喜欢散步的虚构朋友。"
        assert restarted.state.host.settings.font_size == "large"


def test_experience_undo_scope_and_manual_conflict(tmp_path: Path) -> None:
    app = create_app(tmp_path, background_services=False)
    with TestClient(app):
        host = app.state.host
        conversation = setup_host(host)
        before = host.settings.model_dump()
        result = host.tools.invoke("app_experience", {}, conversation, "enable")
        assert result["status"] == "succeeded"
        assert result["page"] == "experience" and result["requires_setup"]
        assert host.settings.proactive_enabled and host.settings.nook_enabled
        assert host.settings.quiet_start == before["quiet_start"]
        assert host.settings.romance_consent == before["romance_consent"]
        assert not host.tools.config.servers
        other = host.new_conversation()["id"]
        assert not host.tools.invoke("app_undo_settings", {}, other, "undo-other")[
            "settings_changed"
        ]
        undo = host.tools.invoke("app_undo_settings", {}, conversation, "undo")
        assert undo["status"] == "succeeded"
        assert host.settings.model_dump() == before
        host.tools.invoke(
            "app_configure", {"changes": {"font_size": "large"}}, conversation, "bigger"
        )
        host.save_settings(
            SettingsUpdate(settings=host.settings.model_copy(update={"font_size": "extra_large"}))
        )
        assert (
            host.tools.invoke("app_undo_settings", {}, conversation, "conflict")["status"]
            == "failed"
        )
        assert host.settings.font_size == "extra_large"


def test_tool_boundaries_and_import_page_receipt(tmp_path: Path) -> None:
    model = ScriptedSettingsModel("app_open", {"page": "persona_import"})
    app = create_app(tmp_path, llm=model, background_services=False)
    with TestClient(app, base_url="http://127.0.0.1", headers=HEADERS) as client:
        client.get("/")
        host = app.state.host
        conversation = setup_host(host)
        original = host.settings.model_dump()
        for change in [
            {"model_consent": False},
            {"deepseek": {"base_url": "https://evil.invalid"}},
            {"romance_consent": True},
            {"custom_style": "x" * 6001},
            {"font_size": "huge"},
        ]:
            result = host.tools.invoke("app_configure", {"changes": change}, conversation, "bad")
            assert result["status"] == "denied"
        invalid = host.tools.invoke(
            "app_configure", {"changes": {"style": "custom"}}, conversation, "incomplete"
        )
        assert invalid["status"] == "failed"
        assert host.settings.model_dump() == original
        body = {
            "conversation_id": conversation,
            "request_id": "import",
            "content": "我想导入人设卡",
        }
        reply = client.post("/api/chat", json=body).json()
        assert reply["app_actions"] == [{"page": "persona_import"}]
        assert reply["configuration"] is None
        assert client.post("/api/chat", json=body).json()["app_actions"] == []
        assert host.settings.model_dump() == original
        assert (
            host.tools.invoke("app_open", {"page": "https://evil.invalid"}, conversation, "url")[
                "status"
            ]
            == "denied"
        )


def test_configured_music_connects_without_playback_or_permission_escalation(
    tmp_path: Path,
) -> None:
    fake = FakeMCP()
    app = create_app(tmp_path, background_services=False, interactive_tools=True, native_music=fake)
    with TestClient(app):
        host = app.state.host
        conversation = setup_host(host)
        result = host.tools.invoke("app_connect_music", {}, conversation, "connect")
        assert result["status"] == "succeeded"
        assert host.tools.config.servers[0].transport == "native"
        assert host.tools.config.servers[0].enabled
        assert not fake.calls
        assert all(rule.mode == "ask" for _, _, rule in host.tools.bindings().values())
        host.tools.config.servers[0] = MCPServerConfig(
            id="netease", label="custom", command="custom-command"
        )
        assert (
            host.tools.invoke("app_connect_music", {}, conversation, "custom")["status"] == "denied"
        )


def test_model_failure_after_saved_change_can_be_reconciled_without_repeating_it(
    tmp_path: Path,
) -> None:
    class FailAfterTool(ScriptedSettingsModel):
        def generate_step(
            self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], timeout: float
        ) -> ModelStep:
            if messages[-1]["role"] == "tool":
                raise MainLLMError("main_llm_timeout")
            return super().generate_step(messages, tools, timeout)

    model = FailAfterTool("app_configure", {"changes": {"font_size": "large"}})
    app = create_app(tmp_path, llm=model, background_services=False)
    with TestClient(app, base_url="http://127.0.0.1", headers=HEADERS) as client:
        client.get("/")
        host = app.state.host
        conversation = setup_host(host)
        response = client.post(
            "/api/chat",
            json={
                "conversation_id": conversation,
                "request_id": "failed-model",
                "content": "字体调大",
            },
        )
        assert response.status_code == 502
        saved = client.get(
            "/api/app-outcome",
            params={"conversation_id": conversation, "request_id": "failed-model"},
        ).json()
        assert saved["configuration"]["settings"]["font_size"] == "large"
        assert len(host.tools.store.actions(conversation)) == 1
        assert (
            client.get(
                "/api/app-outcome",
                params={
                    "conversation_id": host.new_conversation()["id"],
                    "request_id": "failed-model",
                },
            ).json()["configuration"]
            is None
        )


def test_stop_reaches_active_reply_after_settings_rebuild(tmp_path: Path) -> None:
    app = create_app(tmp_path, background_services=False)
    with TestClient(app, base_url="http://127.0.0.1", headers=HEADERS) as client:
        client.get("/")
        host = app.state.host
        conversation = setup_host(host)
        original = host.loop
        with original.run(conversation, "active-reply") as run:
            result = host.tools.invoke(
                "app_configure", {"changes": {"font_size": "large"}}, conversation, "active-reply"
            )
            assert result["status"] == "succeeded"
            assert host.loop is not original
            response = client.post("/api/automation/cancel/active-reply", json={})
            assert response.status_code == 200
            assert response.json()["cancelled"] and run.cancelled.is_set()
        assert not host.loop.cancel("active-reply")


def test_chat_opens_native_player_without_setup_grants_or_replaying_request(tmp_path: Path) -> None:
    calls = []

    def bridge(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        calls.append((name, arguments))
        assert name == "netease_open_app" and not arguments
        return {"status": "succeeded", "delivery": "requested", "playback_verified": False}

    model = ScriptedSettingsModel("app_open_music", {})
    app = create_app(
        tmp_path,
        llm=model,
        background_services=False,
        interactive_tools=True,
        native_music=AndroidMusicClient(bridge),
    )
    with TestClient(app, base_url="http://127.0.0.1", headers=HEADERS) as client:
        client.get("/")
        host = app.state.host
        conversation = setup_host(host)
        host.tools.config.loop.enabled = False
        before = host.tools.config.model_dump()
        body = {"conversation_id": conversation, "request_id": "listen", "content": "我想听歌"}
        reply = client.post("/api/chat", json=body)
        assert reply.status_code == 200, reply.text
        assert reply.json()["execution"]["tool_calls"] == 1
        assert client.post("/api/chat", json=body).json()["reused"]
        assert calls == [("netease_open_app", {})]
        assert host.tools.config.model_dump() == before
        # File names and URL commands cannot enter the fixed app shortcut.
        assert (
            host.tools.invoke("app_open_music", {"url": "bad://"}, conversation, "arbitrary")[
                "status"
            ]
            == "denied"
        )
        assert len(calls) == 1
        clicked = {"conversation_id": conversation, "request_id": "button"}
        assert client.post("/api/music/open", json=clicked).json()["status"] == "succeeded"
        assert client.post("/api/music/open", json=clicked).json()["status"] == "succeeded"
        assert len(calls) == 2


def test_open_player_disabled_environment_does_not_call_launcher(tmp_path: Path) -> None:
    app = create_app(tmp_path, background_services=False, interactive_tools=False)
    with TestClient(app, base_url="http://127.0.0.1", headers=HEADERS) as client:
        client.get("/")
        host = app.state.host
        conversation = setup_host(host)
        called = []
        host.app_assistant.music_launcher = lambda: called.append(True) or {"status": "succeeded"}
        assert (
            host.tools.invoke("app_open_music", {}, conversation, "disabled")["status"] == "denied"
        )
        assert (
            client.post(
                "/api/music/open",
                json={
                    "conversation_id": conversation,
                    "request_id": "disabled-ui",
                },
            ).status_code
            == 403
        )
        assert not called
