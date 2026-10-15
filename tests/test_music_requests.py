"""Lyrics-to-player contracts use invented lyrics and isolated model/player fixtures."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from companion_agent.app import create_app
from companion_agent.automation.bundled_music import refresh_lyrics_catalog
from companion_agent.automation.loop import ModelStep, ToolCall
from companion_agent.automation.models import AutomationConfig, ToolRule
from companion_agent.integrations.netease import build_server
from companion_agent.integrations.netease_android import AndroidMusicClient
from companion_agent.integrations.netease_catalog import NetEaseCatalog
from companion_agent.music_requests import OPEN, SEARCH, STATE, playback_receipt
from tests.test_agent_automation import ScriptModel
from tests.test_music import server
from tests.test_romance_app import HEADERS, configure

QUERY = "合成月光落进小小纸船"
SONG = {
    "id": 123,
    "name": "纸船",
    "artists": [{"name": "合成歌手"}],
    "album": {"name": "合成专辑"},
    "duration": 180000,
    "lyrics": ["合成月光<em>落进</em>小小纸船", "另一个不应进入模型的歌词行"],
}


def transport(request: httpx.Request) -> httpx.Response:
    assert request.url.host == "music.163.com"
    if request.url.path.endswith("detail/"):
        return httpx.Response(
            200,
            json={
                "code": 200,
                "songs": [{"id": 123, "album": {"picUrl": "http://p1.music.126.net/cover.jpg"}}],
            },
        )
    assert request.url.params["type"] == "1006"
    return httpx.Response(
        200,
        json={
            "code": 200,
            "result": {
                "songs": [
                    {**SONG, "id": 124, "name": "纸船 (Live)", "lyrics": ["只有部分匹配"]},
                    SONG,
                ]
            },
        },
    )


def test_lyrics_search_matches_evidence_not_rank_and_limits_external_data() -> None:
    result = asyncio.run(NetEaseCatalog(httpx.MockTransport(transport)).search(QUERY, 3, "lyrics"))
    assert [s["id"] for s in result["songs"]] == ["123", "124"]
    assert result["songs"][0]["lyric_match"] is True
    assert result["songs"][1]["lyric_match"] is False
    assert result["songs"][0]["cover_url"].startswith("https://p1.music.126.net/")
    assert "另一个不应进入模型" not in json.dumps(result, ensure_ascii=False)


@pytest.mark.parametrize("query,kind", [("哈哈", "lyrics"), (QUERY, "bad"), ("\n歌词行", "lyrics")])
def test_bad_lyric_requests_do_not_reach_network(query: str, kind: Any) -> None:
    def forbidden(_: httpx.Request) -> httpx.Response:
        pytest.fail("invalid request reached network")

    with pytest.raises(ValueError):
        asyncio.run(NetEaseCatalog(httpx.MockTransport(forbidden)).search(query, 3, kind))


def test_optional_artwork_failure_preserves_matches() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("detail/"):
            return httpx.Response(503)
        return transport(request)

    result = asyncio.run(NetEaseCatalog(httpx.MockTransport(respond)).search(QUERY, 3, "lyrics"))
    assert result["songs"][0]["lyric_match"]
    assert "cover_url" not in result["songs"][0]


def test_windows_and_android_search_accept_same_lyric_contract() -> None:
    catalog = NetEaseCatalog(httpx.MockTransport(transport))
    mcp = build_server(catalog=catalog)
    arguments = {"query": QUERY, "search_type": "lyrics", "limit": 3}

    async def windows() -> dict[str, Any]:
        _, result = await mcp.call_tool("netease_search_songs", arguments)
        return result

    native = AndroidMusicClient(lambda *_: pytest.fail("search must not touch the player"), catalog)
    definition = next(t for t in native.discover(server()) if t["name"] == "netease_search_songs")
    android = native.call(server(), definition["name"], arguments, definition)
    assert android["data"] == asyncio.run(windows())


class Player:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.current = "999"
        self.accept = True

    def __call__(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((name, args))
        if name == "netease_open_song":
            if not self.accept:
                return {"status": "uncertain"}
            self.current = args["song_id"]
            return {"status": "succeeded", "delivery": "requested", "playback_verified": False}
        return {
            "status": "succeeded",
            "available": True,
            "song_id": self.current,
            "title": "纸船",
            "artist": "合成歌手",
            "album": "合成专辑",
            "playback": "playing",
        }


class SongModel(ScriptModel):
    def __init__(self, play: bool = False) -> None:
        super().__init__()
        self.plan = [(SEARCH, {"query": QUERY, "search_type": "lyrics", "limit": 3})]
        if play:
            self.plan.extend([(OPEN, {"song_id": "123"}), (STATE, {})])

    def generate_step(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], timeout: float
    ) -> ModelStep:
        self.histories.append(list(messages))
        if self.plan:
            name, args = self.plan.pop(0)
            call = ToolCall(id=str(len(self.histories)), name=name, arguments=json.dumps(args))
            return ModelStep(
                model="synthetic",
                total_tokens=200,
                calls=[call],
                message={
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {"name": name, "arguments": call.arguments},
                        }
                    ],
                },
            )
        return ModelStep(
            model="synthetic",
            text="找到这首歌了。",
            message={"role": "assistant", "content": "找到这首歌了。"},
            total_tokens=50,
        )


@pytest.fixture
def requests_app(tmp_path: Path):
    player, model = Player(), SongModel()
    app = create_app(
        tmp_path,
        llm=model,
        background_services=False,
        interactive_tools=True,
        native_music=AndroidMusicClient(player, NetEaseCatalog(httpx.MockTransport(transport))),
    )
    with TestClient(app, base_url="http://127.0.0.1", headers=HEADERS) as client:
        client.get("/")
        configure(client)
        host = app.state.host
        host.tools.configure(
            AutomationConfig(
                servers=[
                    server(
                        tools={
                            "netease_search_songs": ToolRule(mode="allow"),
                            "netease_open_song": ToolRule(mode="ask"),
                            "netease_playback_state": ToolRule(mode="ask"),
                        }
                    )
                ]
            )
        )
        host.tools.discover("netease")
        conversation = host.conversations()[0]["id"]
        yield client, host, player, model, conversation


def search_chat(fixture: Any, *, play: bool = False) -> dict[str, Any]:
    client, _, _, _, conversation = fixture
    result = client.post(
        "/api/chat",
        json={
            "conversation_id": conversation,
            "request_id": "find-1",
            "content": f"帮我{'播放' if play else '找'}唱‘{QUERY}’的歌",
        },
    )
    assert result.status_code == 200, result.text
    return result.json()


def pick_body(result: dict[str, Any], conversation: str) -> dict[str, str]:
    card = result["assistant"]["music_cards"][0]
    return {
        "conversation_id": conversation,
        "search_action_id": card["search_action_id"],
        "song_id": "123",
        "request_id": "selected-1",
    }


def test_chat_returns_verified_candidates_and_click_uses_existing_permissions(
    requests_app: Any,
) -> None:
    client, host, player, model, conversation = requests_app
    result = search_chat(requests_app)
    cards = result["assistant"]["music_cards"]
    assert cards[0]["id"] == "123" and cards[0]["state"] == "candidate"
    assert cards[1]["name"] == "纸船 (Live)"
    assert not player.calls  # Finding alone has no playback effect.
    rules = "\n".join(m["content"] for m in model.histories[0] if m["role"] == "system")
    assert "仅分享/赞叹/分析歌词" in rules and "search_type=lyrics" in rules
    body = pick_body(result, conversation)
    picked = client.post("/api/music/pick", json=body)
    assert picked.status_code == 200, picked.text
    assert picked.json()["state"] == "verified"
    assert client.post("/api/music/pick", json=body).json()["operation"]["reused"]
    assert [name for name, _ in player.calls] == ["netease_open_song", "netease_playback_state"]
    assert host.tools.config.servers[0].tools["netease_open_song"].mode == "ask"
    turn = host.memory.store.get_turn(result["assistant"]["id"], host.key.user_id)
    assert host.public_turn(turn)["music_cards"][0]["state"] == "verified"


def test_automatic_lyric_search_open_and_verify_chain(requests_app: Any) -> None:
    _, host, player, model, _ = requests_app
    model.plan.extend([(OPEN, {"song_id": "123"}), (STATE, {})])
    for rule in host.tools.config.servers[0].tools.values():
        rule.mode = "allow"
    result = search_chat(requests_app, play=True)
    assert result["execution"]["tool_calls"] == 3
    assert result["assistant"]["music_cards"][0]["state"] == "verified"
    assert len(player.calls) == 2


def test_pick_rejects_cross_conversation_forged_id_and_disabled_tool(requests_app: Any) -> None:
    client, host, player, _, conversation = requests_app
    body = pick_body(search_chat(requests_app), conversation)
    other = client.post("/api/conversations").json()["id"]
    for invalid in (body | {"song_id": "999"}, body | {"conversation_id": other}):
        assert client.post("/api/music/pick", json=invalid).status_code == 422
    host.tools.config.servers[0].tools["netease_open_song"].mode = "off"
    assert client.post("/api/music/pick", json=body).status_code == 422
    assert not player.calls


def test_forgotten_source_hides_cards_and_cannot_play(requests_app: Any) -> None:
    client, host, player, _, conversation = requests_app
    result = search_chat(requests_app)
    body = pick_body(result, conversation)
    with host.database.connection() as db:
        db.execute(
            "UPDATE conversation_turns SET metadata_json=? WHERE id=?",
            (json.dumps({"content_redacted_at": "synthetic"}), result["user"]["id"]),
        )
    turn = host.memory.store.get_turn(result["assistant"]["id"], host.key.user_id)
    assert host.public_turn(turn)["music_cards"] == []
    assert client.post("/api/music/pick", json=body).status_code == 422
    assert not player.calls


def test_uncertain_open_never_replays_or_claims_playback(requests_app: Any) -> None:
    client, _, player, _, conversation = requests_app
    body = pick_body(search_chat(requests_app), conversation)
    player.accept = False
    assert client.post("/api/music/pick", json=body).json()["state"] == "uncertain"
    assert client.post("/api/music/pick", json=body).json()["state"] == "uncertain"
    assert len(player.calls) == 1


def test_playback_title_alone_or_wrong_id_is_not_confirmation() -> None:
    song = {"id": "123", "name": "歌", "artists": ["歌手"], "album": "专辑"}
    media = {"available": True, "playback": "playing", "title": "歌"}
    assert playback_receipt(song, media) == "requested"
    media.update(artist="歌手", album="专辑")
    assert playback_receipt(song, media) == "metadata_matched"
    assert playback_receipt(song, media | {"song_id": "999"}) == "requested"
    assert playback_receipt(song, media | {"song_id": "123", "playback": "paused"}) == "requested"


def test_ai_cannot_play_an_unmatched_lyric_candidate(requests_app: Any) -> None:
    _, host, player, model, conversation = requests_app
    model.plan.append((OPEN, {"song_id": "124"}))
    host.tools.config.servers[0].tools["netease_open_song"].mode = "allow"
    search_chat(requests_app, play=True)
    assert not player.calls
    assert host.tools.invoke(OPEN, {"song_id": "999"}, conversation, "find-1")["status"] == "denied"
    # A later title-only search is not proof that an unmatched lyric was verified.
    host.tools.invoke(SEARCH, {"query": "纸船", "limit": 3}, conversation, "find-1")
    assert host.tools.invoke(OPEN, {"song_id": "124"}, conversation, "find-1")["status"] == "denied"
    assert not player.calls


def test_plain_lyric_sharing_keeps_music_rules_but_has_no_implicit_search(
    requests_app: Any,
) -> None:
    client, _, player, model, conversation = requests_app
    model.plan.clear()
    result = client.post(
        "/api/chat",
        json={
            "conversation_id": conversation,
            "request_id": "share-only",
            "content": f"‘{QUERY}’，这句写得真好，别切歌。",
        },
    )
    assert result.status_code == 200
    assert result.json()["execution"]["tool_calls"] == 0
    assert result.json()["assistant"]["music_cards"] == [] and not player.calls


def test_old_bundled_catalog_refresh_retains_permission_and_allowlists(requests_app: Any) -> None:
    _, host, player, _, _ = requests_app
    search = next(t for t in host.tools.catalog["netease"] if t["name"] == "netease_search_songs")
    search["inputSchema"]["properties"].pop("search_type")
    rule = host.tools.config.servers[0].tools["netease_search_songs"]
    rule.arguments = {"limit": [3]}
    refresh_lyrics_catalog(host.tools, "unused")
    updated = next(t for t in host.tools.catalog["netease"] if t["name"] == "netease_search_songs")
    assert "search_type" in updated["inputSchema"]["properties"]
    assert rule.mode == "allow" and rule.arguments == {"limit": [3]}
    assert not player.calls
