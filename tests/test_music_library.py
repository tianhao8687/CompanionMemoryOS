"""Synthetic accounts and local stores only; never inspect a real user's music account."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from companion_agent.app import create_app
from companion_agent.integrations.netease import build_server
from companion_agent.integrations.netease_account import current_account
from companion_agent.integrations.netease_android import AndroidMusicClient
from companion_agent.integrations.netease_catalog import NetEaseCatalog
from companion_agent.music_library import TOOL, forget_requested, parse_reference
from companion_agent.music_profile import character_taste, persona_key, taste_context
from companion_agent.romance import RomanceSettings, SettingsUpdate
from tests.test_app_assistant import setup_host
from tests.test_music import server
from tests.test_music_requests import SongModel
from tests.test_romance_app import HEADERS


class Library:
    def __init__(self) -> None:
        self.logged_in = True
        self.fail = False
        self.calls: list[str] = []
        self.account_calls = 0

    def account(self, name: str, arguments: Any) -> dict[str, Any]:
        assert name == "netease_account", "library reading must not play or inspect other apps"
        self.account_calls += 1
        return {
            "status": "succeeded",
            "available": self.logged_in,
            "user_id": "8" if self.logged_in else "",
            "platform": "android",
            "needs_login": not self.logged_in,
        }

    def respond(self, request: httpx.Request) -> httpx.Response:
        assert request.method == "GET" and request.url.host == "music.163.com"
        assert "cookie" not in request.headers
        self.calls.append(request.url.path)
        if self.fail:
            return httpx.Response(200, json={"code": 403})
        if request.url.path == "/api/user/playlist":
            assert request.url.params["uid"] == "8"
            return httpx.Response(
                200,
                json={
                    "code": 200,
                    "more": True,
                    "playlist": [
                        {
                            "id": i,
                            "name": f"合成歌单{i}",
                            "creator": {"userId": 8},
                            "trackCount": 100,
                            "tags": ["合成标签"],
                            "secret": "DO_NOT_FORWARD",
                        }
                        for i in range(10, 17)
                    ],
                },
            )
        if request.url.path == "/api/song/detail/":
            identifiers = json.loads(request.url.params["ids"])
            assert 1 <= len(identifiers) <= 20
            return httpx.Response(
                200,
                json={
                    "code": 200,
                    "songs": [
                        {
                            "id": i,
                            "name": f"合成歌曲{i % 100}",
                            "artists": [{"name": "合成歌手"}],
                            "album": {"name": "测试专辑"},
                            "mp3Url": "DO_NOT_FORWARD",
                        }
                        for i in identifiers
                    ],
                },
            )
        assert request.url.path == "/api/v6/playlist/detail"
        identifier = int(request.url.params["id"])
        return httpx.Response(
            200,
            json={
                "code": 200,
                "result": {
                    "id": identifier,
                    "name": f"合成歌单{identifier}",
                    "trackCount": 100,
                    "trackIds": [{"id": identifier * 100 + i} for i in range(100)],
                    "tracks": [
                        {
                            "id": identifier * 100 + i,
                            "name": f"合成歌曲{i}",
                            "artists": [{"name": "合成歌手"}],
                            "album": {"name": "测试专辑"},
                            "mp3Url": "DO_NOT_FORWARD",
                        }
                        for i in range(6)
                    ],
                },
            },
        )


@pytest.fixture
def library_app(tmp_path: Path):
    library, model = Library(), SongModel()
    app = create_app(
        tmp_path,
        llm=model,
        background_services=False,
        interactive_tools=True,
        native_music=AndroidMusicClient(
            library.account, NetEaseCatalog(httpx.MockTransport(library.respond))
        ),
    )
    host = app.state.host
    with TestClient(app, base_url="http://127.0.0.1", headers=HEADERS) as client:
        client.get("/")
        conversation = setup_host(host)
        yield client, host, library, model, conversation


def send(fixture: Any, key: str, text: str = "直接读取我的网易云歌单", **args: Any):
    client, host, _, model, conversation = fixture
    model.plan = [(TOOL, {"action": "read", **args})]
    response = client.post(
        "/api/chat",
        json={
            "conversation_id": conversation,
            "request_id": key,
            "content": text,
        },
    )
    assert response.status_code == 200, response.text
    receipt = next(
        a for a in host.tools.store.request_actions(conversation, key) if a["tool_name"] == TOOL
    )
    return response.json(), receipt["result"]


def test_direct_account_import_refresh_forget_and_persona_independence(library_app: Any) -> None:
    _, host, library, _, conversation = library_app
    original_taste = character_taste(host.settings)
    _, result = send(library_app, "first")
    assert result["status"] == "succeeded" and "profile" in result
    assert library.account_calls == 1 and len(library.calls) == 7
    profile = result["profile"]
    assert profile["evidence"] == "connected_account_collections"
    assert not profile["listening_frequency_known"]
    assert len(profile["song_samples"]) == 18
    assert len(profile["collections"]) == 3
    assert all(c["sampled"] == 20 and c["partial"] for c in profile["collections"])
    assert "DO_NOT_FORWARD" not in json.dumps(result)
    assert "合成歌手" in host.music_library.context()
    assert character_taste(host.settings) == original_taste
    _, refreshed = send(library_app, "refresh")
    assert refreshed["status"] == "succeeded" and library.account_calls == 2
    assert len(host.settings.music_library_sources) == 1
    _, forgotten = send(library_app, "forget", "忘掉我的歌单参考", action="forget")
    assert forgotten["status"] == "succeeded"
    assert not host.settings.music_library_enabled
    assert "合成歌手" not in host.music_library.context()
    for request in ("first", "refresh"):
        receipts = host.tools.store.request_actions(conversation, request)
        assert "合成歌手" not in json.dumps(receipts, ensure_ascii=False)
    _, stopped = send(library_app, "stopped", "我很累想哭")
    assert stopped["status"] == "denied" and library.account_calls == 2


def test_login_resumes_without_a_second_chat_or_reusing_stale_account(library_app: Any) -> None:
    client, host, library, _, conversation = library_app
    library.logged_in = False
    _, result = send(library_app, "login")
    assert result["page"] == "music_account" and result["needs_login"]
    assert not library.calls and not host.settings.music_library_sources
    library.logged_in = True
    response = client.post(
        "/api/music/library/resume",
        json={
            "conversation_id": conversation,
            "request_id": "login",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json().get("profile"), response.json()
    assert library.account_calls == 2
    assert len(host.settings.music_library_sources) == 1
    again = client.post(
        "/api/music/library/resume",
        json={
            "conversation_id": conversation,
            "request_id": "login",
        },
    )
    assert again.status_code == 200 and library.account_calls == 2
    denied = client.post(
        "/api/music/library/resume",
        json={
            "conversation_id": conversation,
            "request_id": "invented",
        },
    )
    assert denied.status_code == 403


def test_sad_chat_does_not_force_a_login_window(library_app: Any) -> None:
    library_app[2].logged_in = False
    _, result = send(library_app, "sad", "我很累想哭")
    assert result["needs_login"] and "page" not in result


def test_a_private_collection_does_not_block_other_playlists(library_app: Any) -> None:
    _, host, library, _, _ = library_app
    original = library.respond

    def partial(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("playlist/detail") and request.url.params["id"] == "10":
            return httpx.Response(200, json={"code": 403})
        return original(request)

    host.tools.client.catalog = NetEaseCatalog(httpx.MockTransport(partial))
    _, result = send(library_app, "partial")
    assert result["status"] == "succeeded"
    assert result["profile"]["unavailable_collections"] == 1
    assert len(result["profile"]["collections"]) == 2


def test_playlist_failure_does_not_misreport_the_connected_account(library_app: Any) -> None:
    _, host, library, model, _ = library_app
    original = library.respond

    def unavailable(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("playlist/detail"):
            return httpx.Response(200, json={"code": 20001})
        return original(request)

    host.tools.client.catalog = NetEaseCatalog(httpx.MockTransport(unavailable))
    _, result = send(library_app, "detail-failure")
    assert result["status"] == "failed" and result["account_identified"]
    assert result["stage"] == "playlist_contents" and not result["empty"]
    assert "needs_login" not in result and "不是账号未连接" in result["message"]
    assert not host.settings.music_library_sources
    assert "account_identified" in json.dumps(model.histories[-1])


def test_read_playlist_reaches_this_and_subsequent_model_context(library_app: Any) -> None:
    client, _, _, model, conversation = library_app
    send(library_app, "library-context")
    assert "合成歌手" in json.dumps(model.histories[-1], ensure_ascii=False)
    response = client.post(
        "/api/chat",
        json={
            "conversation_id": conversation,
            "request_id": "later-music",
            "content": "以后选歌参考这些歌单",
        },
    )
    assert response.status_code == 200
    system = "\n".join(m["content"] for m in model.histories[-1] if m["role"] == "system")
    assert "用户的音乐参考" in system and "合成歌手" in system
    assert "不是常听次数" in system


def test_deleted_source_is_not_reused_or_silently_reimported(library_app: Any) -> None:
    _, host, library, _, _ = library_app
    send(library_app, "source")
    source = host.settings.music_library_sources[0].source_turn
    with host.database.connection() as db:
        db.execute("UPDATE conversation_turns SET deletion_state='forgotten' WHERE id=?", (source,))
    assert "合成歌手" not in host.music_library.context()
    _, result = send(library_app, "mood", "我很累想哭")
    assert result["status"] == "denied" and library.account_calls == 1


def test_model_cannot_substitute_a_different_shared_account(library_app: Any) -> None:
    _, _, library, _, _ = library_app
    _, result = send(
        library_app,
        "forged",
        "看看这个歌单 https://music.163.com/playlist?id=10",
        reference="https://music.163.com/playlist?id=20",
    )
    assert result["status"] == "failed" and not library.calls


def test_failed_refresh_keeps_reference_and_disabled_connection_makes_no_calls(library_app: Any):
    _, host, library, _, _ = library_app
    send(library_app, "first")
    previous = host.settings.music_library_sources[:]
    library.fail = True
    _, result = send(library_app, "failed")
    assert result["status"] == "failed" and host.settings.music_library_sources == previous
    calls = library.account_calls
    host.tools.config.loop.enabled = False
    _, result = send(library_app, "off")
    assert result["status"] == "denied" and library.account_calls == calls


@pytest.mark.parametrize(
    "url",
    [
        "https://music.163.com/#/playlist?id=10",
        "https://y.music.163.com/m/playlist?id=10&userid=8",
        "https://music.163.com/playlist?id=10",
    ],
)
def test_full_and_mobile_references(url: str) -> None:
    assert parse_reference(url) == ("playlist", "10", "https://music.163.com/playlist?id=10")


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.test/playlist?id=10",
        "file:///playlist?id=10",
        "https://music.163.com@evil.test/playlist?id=10",
        "https://music.163.com:8000/playlist?id=10",
        "https://music.163.com/playlist?id=1&id=2",
        "https://music.163.com/playlist?id=0",
        "https://music.163.com/song?id=10",
    ],
)
def test_reference_cannot_redirect_reads_or_guess_an_id(url: str) -> None:
    with pytest.raises(ValueError):
        parse_reference(url)


@pytest.mark.parametrize("text", ["别删除我的歌单", "她说忘掉我的歌单", "“忘掉我的歌单”是什么意思"])
def test_forget_only_current_direct_request(text: str) -> None:
    assert not forget_requested(text)


def test_presets_and_custom_personas_have_stable_separate_tastes() -> None:
    base = RomanceSettings()
    assert (
        len(
            {
                character_taste(base.model_copy(update={"style": style}))
                for style in ("gentle", "playful", "steady")
            }
        )
        == 3
    )
    changed = base.model_copy(update={"user_name": "测试用户", "font_size": "large"})
    assert persona_key(base) == persona_key(changed)
    custom = base.model_copy(update={"style": "custom", "custom_style": "喜欢摇滚的虚构角色"})
    assert character_taste(custom) is None and "app_music_taste" in taste_context(custom)
    saved = custom.model_copy(
        update={"character_music_tastes": {persona_key(custom): "后摇与重鼓点"}}
    )
    assert character_taste(saved) == "后摇与重鼓点"
    assert character_taste(saved.model_copy(update={"custom_style": "另一位虚构角色"})) is None


def test_custom_taste_is_saved_once_and_survives_restart(library_app: Any, tmp_path: Path):
    client, host, _, model, conversation = library_app
    host.save_settings(
        SettingsUpdate(
            settings=host.settings.model_copy(
                update={
                    "style": "custom",
                    "custom_style": "偏爱摇滚的虚构朋友",
                }
            )
        )
    )
    for i, preferences in enumerate(("后摇、长段器乐与沉稳鼓点", "用户喜欢的所有流行曲")):
        model.plan = [("app_music_taste", {"preferences": preferences})]
        response = client.post(
            "/api/chat",
            json={
                "conversation_id": conversation,
                "request_id": f"taste{i}",
                "content": "你喜欢什么歌",
            },
        )
        assert response.status_code == 200
    assert character_taste(host.settings) == "后摇、长段器乐与沉稳鼓点"
    restarted = create_app(tmp_path, background_services=False)
    with TestClient(restarted):
        assert character_taste(restarted.state.host.settings) == character_taste(host.settings)


def test_windows_only_current_identity_no_cached_users_or_secrets(tmp_path: Path) -> None:
    path = tmp_path / "fixture.dat"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE persistentModel(uniKey TEXT, jsonStr TEXT)")
        db.execute(
            "INSERT INTO persistentModel VALUES ('host', ?)",
            (
                json.dumps(
                    {
                        "data": {
                            "uid": 8,
                            "isAnonymous": False,
                            "nickName": "private",
                            "cookie": "DO_NOT_FORWARD",
                        }
                    }
                ),
            ),
        )
    before = path.read_bytes()
    result = current_account(path)
    assert result["user_id"] == "8"
    assert "private" not in json.dumps(result) and "DO_NOT_FORWARD" not in json.dumps(result)
    assert path.read_bytes() == before
    with sqlite3.connect(path) as db:
        db.execute(
            "UPDATE persistentModel SET jsonStr=?",
            (
                json.dumps(
                    {
                        "data": {
                            "uid": 8,
                            "isAnonymous": True,
                        }
                    }
                ),
            ),
        )
    assert current_account(path)["needs_login"]
    assert current_account(tmp_path / "missing")["needs_login"]


def test_windows_and_android_playlist_contracts_match() -> None:
    library = Library()
    catalog = NetEaseCatalog(httpx.MockTransport(library.respond))
    native = AndroidMusicClient(library.account, catalog)
    mcp = build_server(catalog=catalog)
    for name, args in (
        ("netease_user_playlists", {"user_id": "8", "limit": 2}),
        ("netease_playlist_songs", {"playlist_id": "10", "limit": 20}),
    ):
        definition = next(t for t in native.discover(server()) if t["name"] == name)
        android = native.call(server(), name, args, definition)

        async def windows(tool_name=name, arguments=args):
            _, data = await mcp.call_tool(tool_name, arguments)
            return data

        assert android["data"] == asyncio.run(windows())
    assert library.account_calls == 0
