"""Shared-listening tests use synthetic media and a bounded fake model only."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from companion_agent import music as music_module
from companion_agent.app import ChatInput, create_app
from companion_agent.automation.mcp_client import MCPFailure
from companion_agent.automation.models import AutomationConfig, MCPServerConfig
from companion_agent.integrations.netease_android import (
    VERSION,
    AndroidMusicClient,
    AndroidMusicPeer,
)
from companion_agent.llm import ModelResponse
from companion_agent.music import MusicInput
from companion_memoryos.schemas import ConsentState, ConversationRole, ConversationTurnInput
from tests.test_romance_app import HEADERS, RecordingLLM, configure


class Media:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.state = {
            "status": "succeeded",
            "available": True,
            "title": "合成歌曲",
            "artist": "测试歌手",
            "playback": "playing",
            "permission": True,
            "controls": {"pause": True, "next": True},
        }

    def __call__(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((name, dict(arguments)))
        if name == "netease_control":
            return {"status": "succeeded", "verified": True}
        return dict(self.state)


def server(**changes: Any) -> MCPServerConfig:
    return MCPServerConfig(
        id="netease", label="网易云", transport="native", enabled=True, **changes
    )


def test_native_protocol_requires_handshake_and_detaches_discovery() -> None:
    bridge = Media()
    peer = AndroidMusicPeer(bridge)
    assert "error" in peer.exchange({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    initialized = peer.exchange(
        {"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {"protocolVersion": VERSION}}
    )
    assert initialized["result"]["protocolVersion"] == VERSION
    assert "error" in peer.exchange({"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
    assert peer.exchange({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert (
        len(peer.exchange({"jsonrpc": "2.0", "id": 4, "method": "tools/list"})["result"]["tools"])
        == 10
    )
    client = AndroidMusicClient(bridge)
    found = client.discover(server())
    found[0]["inputSchema"]["properties"]["unwanted"] = {}
    assert "unwanted" not in client.discover(server())[0]["inputSchema"]["properties"]
    with pytest.raises(MCPFailure, match="工具已变化"):
        client.call(server(), found[0]["name"], {}, found[0])
    assert bridge.calls == []


def test_native_rejects_wrong_transport_invalid_args_and_short_timeout() -> None:
    bridge = Media()
    client = AndroidMusicClient(bridge)
    tool = next(t for t in client.discover(server()) if t["name"] == "netease_control")
    with pytest.raises(MCPFailure):
        client.call(server(), tool["name"], {"action": "volume"}, tool)
    with pytest.raises(MCPFailure):
        client.call(server(timeout_seconds=2), tool["name"], {"action": "next"}, tool)
    with pytest.raises(MCPFailure):
        client.discover(MCPServerConfig(id="web", label="web", command="unknown"))
    with pytest.raises(ValidationError):
        server(command="unwanted")
    assert bridge.calls == []


@pytest.fixture
def listening(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    now = [1000.0]
    monkeypatch.setattr(music_module, "time", SimpleNamespace(monotonic=lambda: now[0]))
    bridge = Media()
    model = RecordingLLM()
    app = create_app(
        tmp_path,
        llm=model,
        background_services=False,
        interactive_tools=True,
        native_music=AndroidMusicClient(bridge),
    )
    with TestClient(app, base_url="http://127.0.0.1", headers=HEADERS) as client:
        client.get("/")
        configure(client)
        host = app.state.host
        host.tools.configure(
            AutomationConfig.model_validate(
                {"servers": [server().model_dump()], "loop": {"enabled": True}}
            )
        )
        host.tools.discover("netease")
        conversation = host.conversations()[0]["id"]
        source = host.memory.append_turn(
            ConversationTurnInput(
                user_id=host.key.user_id,
                scope=host.scope(conversation),
                actor_id=host.key.user_id,
                role=ConversationRole.USER,
                content="今天想听会儿歌。",
                consent=ConsentState.GRANTED,
            )
        ).turn
        state = client.post(
            "/api/music", json={"action": "start", "conversation_id": conversation}
        ).json()
        item = {"conversation_id": conversation, "session_id": state["id"]}
        yield SimpleNamespace(
            client=client,
            host=host,
            model=model,
            bridge=bridge,
            now=now,
            item=item,
            source=source,
            state=state,
        )


def poll(f: Any, **extra: Any) -> dict[str, Any]:
    response = f.client.post("/api/music", json={**f.item, "action": "poll", **extra})
    assert response.status_code == 200, response.text
    return response.json()


def test_seek_ui_scopes_track_and_deduplicates_explicit_request(listening: Any) -> None:
    f = listening
    command = {
        **f.item,
        "action": "seek",
        "request_id": "seek-one",
        "track_key": f.state["media"]["track_key"],
        "position_ms": 42000,
    }
    for _ in range(2):
        response = f.client.post("/api/music", json=command)
        assert response.status_code == 200, response.text
    calls = [args for name, args in f.bridge.calls if name == "netease_seek"]
    assert calls == [{"position_ms": 42000, "title": "合成歌曲", "artist": "测试歌手", "album": ""}]
    assert f.client.post("/api/music", json={**command, "track_key": "old"}).status_code == 422
    assert f.client.post("/api/music", json={**command, "position_ms": True}).status_code == 422
    assert len([x for x in f.bridge.calls if x[0] == "netease_seek"]) == 1


def test_listening_no_opening_message_cooldown_and_unanswered_silence(listening: Any) -> None:
    f = listening
    assert f.state["media"]["title"] == "合成歌曲" and not f.model.inputs
    f.now[0] += 599
    poll(f)
    assert not f.model.inputs
    f.now[0] += 1
    reply = poll(f)
    assert len(f.model.inputs) == 1 and reply["reply_id"]
    turn = f.host.memory.store.get_turn(reply["reply_id"], f.host.key.user_id)
    assert turn.metadata["context_turn_ids"] == [f.source.id]
    assert turn.reply_to_turn_id == f.source.id
    f.now[0] += 601
    f.bridge.state["title"] = "另一首合成歌"
    poll(f)
    assert len(f.model.inputs) == 1  # New song alone is not a reason to nag.


@pytest.mark.parametrize(
    "condition", ["quiet", "composing", "paused", "permission", "consent", "suspend"]
)
def test_no_proactive_call_when_not_wanted_or_not_ready(listening: Any, condition: str) -> None:
    f = listening
    f.now[0] += 601
    if condition == "quiet":
        f.client.post("/api/music", json={**f.item, "action": "quiet", "quiet": True})
    elif condition == "paused":
        f.bridge.state["playback"] = "paused"
    elif condition == "permission":
        f.bridge.state = {"status": "failed", "available": False, "permission": False}
    elif condition == "consent":
        f.host.settings.model_consent = False
    elif condition == "suspend":
        f.host.music.apply(MusicInput(**f.item, action="suspend"))
        f.host.music.maybe_speak(MusicInput(**f.item, action="poll"))
        assert not f.model.inputs
        return
    poll(f, composing=condition == "composing")
    assert not f.model.inputs


@pytest.mark.parametrize("change", ["quiet", "activity", "end", "policy", "connection"])
def test_generation_is_discarded_when_presence_or_evidence_changes(
    listening: Any, change: str
) -> None:
    f = listening
    f.now[0] += 601

    def generate(messages: Any) -> ModelResponse:
        f.model.inputs.append(messages)
        if change == "policy":
            f.host.settings.model_consent = False
        elif change == "connection":
            f.host.tools.config.servers[0].enabled = False
        else:
            f.host.music.apply(MusicInput(**f.item, action=change, quiet=True, composing=True))
        return ModelResponse(text="合成测试陪伴消息。", model="fixture")

    f.model.generate = generate
    result = poll(f)
    assert len(f.model.inputs) == 1 and not result.get("reply_id")
    assert len(f.host.outreach._recent(f.item["conversation_id"])) == 1


def test_explicit_controls_exactly_once_and_scope_isolation(listening: Any) -> None:
    f = listening
    command = {**f.item, "action": "next", "request_id": "user-click-one"}
    for _ in range(2):
        result = f.client.post("/api/music", json=command)
        assert result.status_code == 200
        assert result.json()["operation"]["status"] == "succeeded"
    assert len([x for x in f.bridge.calls if x[0] == "netease_control"]) == 1
    assert all(rule.mode != "allow" for rule in f.host.tools.config.servers[0].tools.values())
    assert f.host.music.context("another-conversation") == ""
    stale = f.client.post("/api/music", json={**command, "session_id": "stale"})
    assert stale.status_code == 422
    f.host.tools.configure(
        f.host.tools.config.model_copy(
            update={"loop": f.host.tools.config.loop.model_copy(update={"enabled": False})}
        )
    )
    assert (
        f.client.post("/api/music", json={**command, "request_id": "disabled"}).status_code == 422
    )


def test_quiet_instruction_excludes_quotes_and_background_expires(listening: Any) -> None:
    f = listening
    f.host.music.observe(
        ChatInput(
            conversation_id=f.item["conversation_id"], request_id="quote", content="她说“别说话”"
        )
    )
    assert not f.host.music.public()["quiet"]
    f.host.music.observe(
        ChatInput(conversation_id=f.item["conversation_id"], request_id="quiet", content="安静陪我")
    )
    assert f.host.music.public()["quiet"]
    f.now[0] += 31
    assert f.host.music.context(f.item["conversation_id"]) == ""


def test_android_capabilities_never_accept_remote_servers(listening: Any) -> None:
    f = listening
    assert f.client.get("/api/automation").json()["capabilities"]["netease"]
    assert f.client.get("/api/automation/netease-template").json()["transport"] == "native"
    response = f.client.put(
        "/api/automation/config",
        json={
            "servers": [{"id": "unsafe", "label": "unsafe", "command": "unknown", "enabled": True}]
        },
    )
    assert response.status_code == 422


def test_other_proactive_messages_wait_and_revocation_clears_chat_context(listening: Any) -> None:
    f = listening
    f.host.settings.proactive_enabled = True
    assert not f.host.outreach.enabled()
    assert "合成歌曲" in f.host.music.context(f.item["conversation_id"])
    f.host.tools.config.servers[0].enabled = False
    assert f.host.music.context(f.item["conversation_id"]) == ""
    f.host.music.apply(MusicInput(**f.item, action="end"))
    assert f.host.outreach.enabled()


def test_listening_context_reaches_real_chat_without_rewriting_model_reply(listening: Any) -> None:
    f = listening
    content = "“把月光借给晚归的人”，这句真好。"
    response = f.client.post(
        "/api/chat",
        json={
            "conversation_id": f.item["conversation_id"],
            "request_id": "sharing",
            "content": content,
        },
    )
    assert response.status_code == 200, response.text
    messages = f.model.inputs[-1]
    system = "\n".join(message.content for message in messages if message.role == "system")
    assert "[SHARED LISTENING]" in system
    assert "明确想聊含义、写法或背景时再充分展开" in system
    assert "未接收音频" in system
    assert messages[-1].content == content
    assert "我在，慢慢说。" in response.text  # No canned replacement or output truncation.
    f.host.music.apply(MusicInput(**f.item, action="end"))
    response = f.client.post(
        "/api/chat",
        json={
            "conversation_id": f.item["conversation_id"],
            "request_id": "after",
            "content": "帮我解释这句的写法。",
        },
    )
    assert response.status_code == 200, response.text
    system = "\n".join(m.content for m in f.model.inputs[-1] if m.role == "system")
    assert "[SHARED LISTENING]" not in system
