"""Isolated chat-to-player contracts. No real model, player, catalog or user database."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from companion_agent import app as app_module
from companion_agent.app import create_app
from companion_agent.automation.models import AutomationConfig, MCPServerConfig
from companion_agent.integrations.netease_android import AndroidMusicClient
from companion_agent.integrations.netease_catalog import NetEaseCatalog
from companion_agent.music_comfort import TOOL, eligible, music_refused
from companion_agent.music_requests import OPEN, SEARCH, STATE
from companion_agent.romance import SettingsUpdate
from tests.test_app_assistant import setup_host
from tests.test_music_requests import SongModel
from tests.test_romance_app import HEADERS

SONG = {"title": "纸船", "artist": "合成歌手"}


class Player:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.state: dict[str, Any] = {
            "status": "succeeded",
            "available": True,
            "playback": "paused",
            "song_id": "999",
        }
        self.accept = True
        self.verify = True
        self.query: list[str] = []
        self.match = True
        self.change_while_searching = False

    def __call__(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((name, args))
        if name == "netease_open_song":
            if not self.accept:
                return {"status": "uncertain"}
            if self.verify:
                self.state.update(playback="playing", song_id=args["song_id"], available=True)
            return {"status": "succeeded", "delivery": "requested", "playback_verified": False}
        return self.state.copy()

    def search(self, request: httpx.Request) -> httpx.Response:
        assert request.url.params["type"] == "1"
        self.query.append(request.url.params["s"])
        if self.change_while_searching:
            self.state["playback"] = "playing"
        return httpx.Response(
            200,
            json={
                "code": 200,
                "result": {
                    "songs": [
                        {
                            "id": 124,
                            "name": "纸船 (Live)",
                            "artists": [{"name": "合成歌手"}],
                            "album": {"name": "现场"},
                        },
                        {
                            "id": 123,
                            "name": "纸船" if self.match else "另一首",
                            "artists": [{"name": "合成歌手"}],
                            "album": {"name": "原专辑"},
                        },
                        {
                            "id": 125,
                            "name": "纸船",
                            "artists": [{"name": "另一个歌手"}],
                            "album": {"name": "翻唱"},
                        },
                    ]
                },
            },
        )


@pytest.fixture(params=["native", "stdio"])
def comfort_app(tmp_path: Path, request: Any, monkeypatch: pytest.MonkeyPatch):
    # Only the app's capability gate is simulated. Other modules must retain the
    # real platform, including credentials, subprocesses and native libraries.
    monkeypatch.setattr(
        app_module,
        "sys",
        SimpleNamespace(
            platform="win32" if request.param == "stdio" else "android",
            executable=sys.executable,
        ),
    )
    player = Player()
    model = SongModel()
    model.plan = [(TOOL, SONG)]
    native = AndroidMusicClient(player, NetEaseCatalog(httpx.MockTransport(player.search)))
    app = create_app(
        tmp_path,
        llm=model,
        background_services=False,
        interactive_tools=True,
        native_music=native if request.param == "native" else None,
    )
    host = app.state.host
    if request.param == "stdio":
        # The Windows host uses identical catalog/state wire contracts, with a fake
        # transport rather than executing the real local player during unit tests.
        target = MCPServerConfig(id="netease", label="fixture", transport="native", enabled=True)

        class WindowsTransport:
            def discover(self, server: Any) -> Any:
                return native.discover(target)

            def call(
                self,
                server: Any,
                name: str,
                arguments: Any,
                expected: Any,
                timeout: float | None = None,
            ) -> Any:
                return native.call(target, name, arguments, expected, timeout)

        host.tools.client = WindowsTransport()
    with TestClient(app, base_url="http://127.0.0.1", headers=HEADERS) as client:
        client.get("/")
        conversation = setup_host(host)
        response = client.get("/api/automation/netease-template")
        assert response.status_code == 200, response.text
        template = response.json()
        template["enabled"] = True
        host.tools.configure(AutomationConfig(servers=[MCPServerConfig.model_validate(template)]))
        host.tools.discover("netease")
        yield client, host, player, model, conversation


def chat(
    fixture: Any, text: str = "今天我很累，有点想哭。", key: str = "comfort"
) -> dict[str, Any]:
    client, _, _, _, conversation = fixture
    fixture[3].plan = [(TOOL, SONG)]
    response = client.post(
        "/api/chat", json={"conversation_id": conversation, "request_id": key, "content": text}
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("text", ["我很累", "我想哭", "今天我好累啊", "我有点难过", "我忍不住哭了"])
def test_current_self_report_is_an_opportunity(text: str) -> None:
    assert eligible(text)


@pytest.mark.parametrize(
    "text",
    [
        "我不累",
        "我不想哭",
        "我不是很累",
        "我很累，但现在不累了",
        "我很高兴，想哭",
        "我很累，想安静一会儿",
        "我想哭，先听我说就好",
        "我很累，别放歌",
        "我很累，帮我改报告",
        "如果我很累，你怎么办",
        "我朋友很累",
        "她说我想哭",
        "我说过我想哭",
        "“我想哭”这句台词",
        "我很累这句话用英语怎么说",
        "昨天我很累",
        "想做一个我很累就放歌的功能",
        "我很累吗？",
        "我很累，播放纸船",
        "我很累，别切歌",
        "我想哭，别放这首歌",
    ],
)
def test_quotes_tasks_negation_and_other_people_are_not_playback(text: str) -> None:
    assert not eligible(text)


def test_one_song_search_handoff_verified_card_and_no_page_jump(comfort_app: Any) -> None:
    _, host, player, _, conversation = comfort_app
    result = chat(comfort_app)
    assert result["execution"]["status"] == "completed"
    assert result["execution"]["tool_calls"] == 1  # One bounded composite, no extra model.
    assert player.query == ["纸船 合成歌手"]  # No emotional content leaves for music search.
    assert [n for n, _ in player.calls] == [
        "netease_playback_state",
        "netease_playback_state",
        "netease_open_song",
        "netease_playback_state",
    ]
    cards = result["assistant"]["music_cards"]
    assert len(cards) == 1 and cards[0]["id"] == "123" and cards[0]["comfort"]
    assert cards[0]["state"] == "verified"
    assert result["app_actions"] == []
    actions = host.tools.store.request_actions(conversation, "comfort")
    assert {a["tool_name"] for a in actions} == {TOOL, SEARCH, OPEN, STATE}
    assert all(a["status"] == "succeeded" for a in actions)
    assert chat(comfort_app)["reused"]  # Retrying HTTP must never replay a song.
    assert [n for n, _ in player.calls].count("netease_open_song") == 1


def test_opt_out_saves_without_model_cooperation_and_survives_restart(comfort_app: Any) -> None:
    _, host, player, _, conversation = comfort_app
    result = chat(comfort_app, "我很累，但别自动放歌。")
    assert not host.settings.comfort_music_enabled
    assert result["configuration"]["settings"]["comfort_music_enabled"] is False
    assert not player.calls and not player.query
    chat(comfort_app, "我好累", "later")
    assert not player.calls
    with host.database.connection() as db:
        saved = json.loads(db.execute("SELECT data_json FROM romance_settings").fetchone()[0])
    from companion_agent.romance import RomanceSettings

    assert not RomanceSettings.model_validate(saved).comfort_music_enabled
    restarted = create_app(host.database.data_dir, background_services=False)
    with TestClient(restarted):
        assert not restarted.state.host.settings.comfort_music_enabled
    # Existing settings tool can re-enable; it does not itself start a song.
    host.tools.invoke(
        "app_configure", {"changes": {"comfort_music_enabled": True}}, conversation, "enable"
    )
    assert host.settings.comfort_music_enabled and not player.calls
    chat(comfort_app, "我好累", "after-enable")
    assert any(n == "netease_open_song" for n, _ in player.calls)


@pytest.mark.parametrize("text", ["我很累，先听我说", "朋友很累", "我不累", "我很累，帮我写邮件"])
def test_ineligible_even_if_model_calls_the_tool(comfort_app: Any, text: str) -> None:
    chat(comfort_app, text)
    assert not comfort_app[2].calls and not comfort_app[2].query


@pytest.mark.parametrize(
    "reason",
    [
        "playing",
        "changing",
        "unknown",
        "permission",
        "off",
        "ask",
        "disabled",
        "no_session",
        "closed",
    ],
)
def test_player_and_permissions_are_enforced_without_confirmations(
    comfort_app: Any, reason: str
) -> None:
    _, host, player, _, _ = comfort_app
    if reason in {"playing", "changing", "unknown"}:
        player.state["playback"] = reason
    elif reason == "permission":
        player.state = {"status": "failed", "available": False, "permission": False}
    elif reason in {"ask", "off"}:
        host.tools.config.servers[0].tools["netease_open_song"].mode = reason
    elif reason == "disabled":
        host.tools.config.loop.enabled = False
    elif reason == "closed":
        player.state = {"status": "succeeded", "available": False, "idle": True}
    else:
        player.state = {"status": "failed", "available": False}
    result = chat(comfort_app)
    assert result["execution"]["status"] == "completed"
    assert all(a["status"] != "pending" for a in host.tools.store.actions())
    assert any(n == "netease_open_song" for n, _ in player.calls) == (reason == "closed")


@pytest.mark.parametrize("failure", ["not_matched", "changed", "uncertain", "unverified"])
def test_failures_do_not_retry_or_claim_playback(comfort_app: Any, failure: str) -> None:
    _, host, player, _, _ = comfort_app
    if failure == "not_matched":
        player.match = False
    elif failure == "changed":
        player.change_while_searching = True
    elif failure == "uncertain":
        player.accept = False
    else:
        player.verify = False
    result = chat(comfort_app)
    receipt = next(a for a in host.tools.store.actions() if a["tool_name"] == TOOL)["result"]
    assert (
        receipt["outcome"]
        == {
            "not_matched": "skipped",
            "changed": "skipped",
            "uncertain": "uncertain",
            "unverified": "requested",
        }[failure]
    )
    assert (
        result["assistant"]["music_cards"] == [] if failure in {"not_matched", "changed"} else True
    )
    before = len(player.calls)
    chat(comfort_app, "我还是很累", "again")
    assert len(player.calls) == before


def test_cooldown_spans_chats_survives_polling_and_expiry_allows_again(comfort_app: Any) -> None:
    client, host, player, model, _ = comfort_app
    chat(comfort_app)
    player.state["playback"] = "paused"
    other = host.new_conversation()["id"]
    second = (client, host, player, model, other)
    for i in range(25):
        host.tools.invoke(STATE, {}, other, f"poll-{i}")
    count = len(player.calls)
    restarted = create_app(host.database.data_dir, background_services=False)
    with TestClient(restarted):
        assert restarted.state.host.music_comfort._cooling("restart-probe")
    chat(second, "我想哭", "other")
    assert len(player.calls) == count
    with host.database.connection() as db:
        db.execute(
            "UPDATE agent_actions SET created_at=? WHERE tool_name=?",
            ((datetime.now(UTC) - timedelta(minutes=31)).isoformat(), TOOL),
        )
    chat(second, "我想哭", "after-cooldown")
    assert [n for n, _ in player.calls].count("netease_open_song") == 2


def test_no_live_turn_or_forged_request_cannot_play(comfort_app: Any) -> None:
    _, host, player, _, conversation = comfort_app
    assert host.tools.invoke(TOOL, SONG, conversation, "no-message")["outcome"] == "skipped"
    assert not player.calls
    host.save_settings(
        SettingsUpdate(settings=host.settings.model_copy(update={"comfort_music_enabled": False}))
    )
    chat(comfort_app)
    host.settings.comfort_music_enabled = True
    assert host.tools.invoke(TOOL, SONG, conversation, "forged-request")["outcome"] == "skipped"
    assert not player.calls


@pytest.mark.parametrize("text", ["不要自动放歌", "关闭音乐陪伴", "我不想听歌", "别放歌"])
def test_music_opt_out_is_direct(text: str) -> None:
    assert music_refused(text)


@pytest.mark.parametrize(
    "text",
    [
        "他说不要放歌",
        "如果我不想听歌",
        "解释不要放歌这句话",
        "不是不要放歌",
        "我朋友不想听歌",
        "不要以为我不想听歌",
        "我没说过不要放歌",
    ],
)
def test_quoted_or_conditional_opt_out_does_not_change_settings(text: str) -> None:
    assert not music_refused(text)
