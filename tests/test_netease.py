"""Synthetic music integration tests never contact or control a real player."""

from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from companion_agent.integrations import netease_windows as windows
from companion_agent.integrations.netease import build_server
from companion_agent.integrations.netease_catalog import NetEaseCatalog, song_id


@pytest.mark.parametrize("identifier", ["0", "-1", "1&cmd=bad", "１２３", "1\n", "1" * 19, ""])
def test_song_ids_reject_command_fragments_and_noncanonical_ids(identifier: str) -> None:
    with pytest.raises(ValueError):
        song_id(identifier)


def test_catalog_preserves_artist_and_version_without_following_external_links() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "music.163.com"
        assert request.url.params["s"] == "合成歌"
        assert request.url.params["limit"] == "2"
        return httpx.Response(
            200,
            json={
                "code": 200,
                "result": {
                    "songs": [
                        {
                            "id": 123,
                            "name": "合成歌 (翻唱)",
                            "artists": [{"name": "合成歌手"}],
                            "album": {"name": "合成专辑"},
                            "url": "https://untrusted.invalid",
                        },
                        {"id": -9, "name": "invalid"},
                    ]
                },
            },
        )

    result = asyncio.run(NetEaseCatalog(httpx.MockTransport(respond)).search(" 合成歌 ", 2))
    assert result["status"] == "succeeded"
    assert result["songs"] == [
        {
            "id": "123",
            "name": "合成歌 (翻唱)",
            "artists": ["合成歌手"],
            "album": "合成专辑",
            "url": "https://music.163.com/song?id=123",
        }
    ]


@pytest.mark.parametrize(
    "query,limit", [(" ", 5), ("a" * 121, 1), ("a\n", 2), ("song", 0), ("song", 11), ("song", True)]
)
def test_search_rejects_invalid_arguments_before_network(query: str, limit: int) -> None:
    def no_network(request: httpx.Request) -> httpx.Response:
        pytest.fail("invalid input must not reach the network")

    with pytest.raises(ValueError):
        asyncio.run(NetEaseCatalog(httpx.MockTransport(no_network)).search(query, limit))


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(302, headers={"Location": "https://untrusted.invalid"}),
        httpx.Response(503, text="unavailable"),
        httpx.Response(200, text="private invalid response"),
        httpx.Response(200, json={"code": 500}),
        httpx.Response(200, json={"code": 200, "result": {"songs": "changed schema"}}),
        httpx.Response(200, content=b"x" * 1_000_001),
    ],
)
def test_search_fails_closed_on_redirects_errors_and_unbounded_responses(
    response: httpx.Response,
) -> None:
    calls = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return response

    with pytest.raises(ValueError) as failure:
        asyncio.run(NetEaseCatalog(httpx.MockTransport(respond)).search("synthetic"))
    assert len(calls) == 1
    assert "private invalid response" not in str(failure.value)


def test_catalog_accepts_empty_results() -> None:
    transport = httpx.MockTransport(
        lambda _: httpx.Response(200, json={"code": 200, "result": {"songCount": 0}})
    )
    assert asyncio.run(NetEaseCatalog(transport).search("synthetic"))["songs"] == []


def test_song_handoff_has_no_shell_and_never_claims_playback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "space and 中文" / "cloudmusic.exe"
    executable.parent.mkdir()
    executable.touch()
    calls = []
    monkeypatch.setattr(windows.sys, "platform", "win32")
    monkeypatch.setattr(windows.subprocess, "Popen", lambda *a, **kw: calls.append((a, kw)))
    result = windows.open_song("123", executable)
    arguments, options = calls[0]
    assert arguments[0][0] == str(executable.resolve())
    uri = arguments[0][1].removeprefix("--webcmd=")
    assert json.loads(base64.b64decode(uri.removeprefix("orpheus://"))) == {
        "type": "song",
        "id": "123",
        "cmd": "play",
    }
    assert not options.get("shell")
    assert result["delivery"] == "requested" and result["playback_verified"] is False
    with pytest.raises(ValueError):
        windows.open_song("123; calc", executable)
    assert len(calls) == 1


def test_invalid_install_path_and_android_cannot_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arbitrary = tmp_path / "other.exe"
    arbitrary.touch()
    assert windows.find_executable(arbitrary) is None
    monkeypatch.setattr(windows.sys, "platform", "linux")
    with pytest.raises(ValueError, match="安卓"):
        windows.open_song("123", arbitrary)


class SyntheticSession:
    def __init__(self, source: str = windows.SOURCE_ID) -> None:
        self.source_app_user_model_id = source
        self.playback = 4
        self.title = "synthetic song"
        self.enabled = True
        self.accept = True
        self.reflect = True
        self.error = False
        self.calls: list[str] = []
        self.reads = 0

    async def try_get_media_properties_async(self) -> SimpleNamespace:
        self.reads += 1
        return SimpleNamespace(title=self.title, artist="synthetic artist", album_title="album")

    def get_playback_info(self) -> SimpleNamespace:
        controls = SimpleNamespace(
            **{value[0]: self.enabled for value in windows.MEDIA_ACTIONS.values()}
        )
        return SimpleNamespace(playback_status=self.playback, controls=controls)

    async def _act(self, action: str) -> bool:
        self.calls.append(action)
        if self.error:
            raise TimeoutError("private diagnostic")
        if self.accept and self.reflect:
            if action == "pause":
                self.playback = 5
            elif action == "play":
                self.playback = 4
            else:
                self.title = "other synthetic song"
        return self.accept

    async def try_pause_async(self) -> bool:
        return await self._act("pause")

    async def try_play_async(self) -> bool:
        return await self._act("play")

    async def try_skip_next_async(self) -> bool:
        return await self._act("next")

    async def try_skip_previous_async(self) -> bool:
        return await self._act("previous")


def media_with(*sessions: SyntheticSession) -> windows.NetEaseMedia:
    media = windows.NetEaseMedia(progress_reader=lambda _: {})
    media._manager = AsyncMock(return_value=SimpleNamespace(get_sessions=lambda: sessions))
    return media


def test_media_does_not_read_or_control_other_players_or_lookalikes() -> None:
    others = [SyntheticSession("msedge.exe"), SyntheticSession("fake-cloudmusic.exe")]
    media = media_with(*others)
    assert asyncio.run(media.state())["available"] is False
    assert asyncio.run(media.control("pause"))["status"] == "failed"
    assert all(not session.calls and not session.reads for session in others)


def test_ambiguous_netease_sessions_are_not_guessed() -> None:
    one, two = SyntheticSession(), SyntheticSession("CloudMusic.EXE")
    result = asyncio.run(media_with(one, two).control("pause"))
    assert result["status"] == "failed"
    assert not one.calls and not two.calls and not one.reads and not two.reads


@pytest.mark.parametrize("action", ["play", "pause", "next", "previous"])
def test_controls_verify_target_state_and_only_touch_netease(action: windows.MediaAction) -> None:
    other, target = SyntheticSession("msedge.exe"), SyntheticSession()
    if action == "play":
        target.playback = 5
    result = asyncio.run(media_with(other, target).control(action))
    assert result["status"] == "succeeded" and result["accepted"] is True
    assert target.calls == [action]
    assert not other.calls and not other.reads


def test_control_handles_noop_capability_rejection_and_uncertain_results() -> None:
    target = SyntheticSession()
    media = media_with(target)
    noop = asyncio.run(media.control("play"))
    assert noop["changed"] is False and not target.calls
    target.enabled = False
    assert asyncio.run(media.control("pause"))["status"] == "failed" and not target.calls
    target.enabled = True
    target.accept = False
    assert asyncio.run(media.control("pause")) == {
        "status": "failed",
        "accepted": False,
        "message": "网易云未接受此次操作。",
    }
    target.accept = True
    target.reflect = False
    assert asyncio.run(media.control("next"))["status"] == "uncertain"
    target.error = True
    result = asyncio.run(media.control("pause"))
    assert result["status"] == "uncertain"
    assert "private diagnostic" not in str(result)
    assert target.calls == ["pause", "next", "pause"]


def test_mcp_tool_contracts_and_invalid_calls_have_no_external_effects() -> None:
    target = SyntheticSession()
    server = build_server(media=media_with(target))

    async def exercise() -> None:
        tools = {tool.name: tool for tool in await server.list_tools()}
        assert set(tools) == {
            "netease_status",
            "netease_search_songs",
            "netease_open_song",
            "netease_playback_state",
            "netease_control",
            "netease_seek",
        }
        assert tools["netease_control"].inputSchema["properties"]["action"]["enum"] == [
            "play",
            "pause",
            "next",
            "previous",
        ]
        _, structured = await server.call_tool("netease_open_song", {"song_id": "bad;cmd"})
        assert structured["status"] == "failed"
        _, structured = await server.call_tool("netease_control", {"action": "pause"})
        assert structured["status"] == "succeeded"
        with pytest.raises(Exception, match="validation"):
            await server.call_tool("netease_control", {"action": "kill"})

    asyncio.run(exercise())
    assert target.calls == ["pause"]


class SyntheticSeekSession(SyntheticSession):
    def __init__(self) -> None:
        super().__init__()
        self.position = 12000
        self.seek_enabled = True
        self.playback = 5
        self.seek_calls: list[int] = []

    def get_playback_info(self) -> SimpleNamespace:
        value = super().get_playback_info()
        value.controls.is_playback_position_enabled = self.seek_enabled
        value.playback_rate = 1
        return value

    def get_timeline_properties(self) -> SimpleNamespace:
        from datetime import UTC, datetime, timedelta

        return SimpleNamespace(
            start_time=timedelta(seconds=3),
            end_time=timedelta(seconds=183),
            min_seek_time=timedelta(seconds=3),
            max_seek_time=timedelta(seconds=183),
            position=timedelta(milliseconds=self.position + 3000),
            last_updated_time=datetime.now(UTC),
        )

    async def try_change_playback_position_async(self, ticks: int) -> bool:
        self.seek_calls.append(ticks)
        if self.reflect:
            self.position = ticks // 10000 - 3000
        return self.accept


def test_seek_converts_to_ticks_and_confirms_provider_echo() -> None:
    target = SyntheticSeekSession()
    result = asyncio.run(media_with(target).seek(42000, target.title, "synthetic artist", "album"))
    assert result["status"] == "succeeded"
    assert result["state"]["position_ms"] == 42000
    assert target.seek_calls == [450000000]


def test_seek_rejects_missing_capability_changed_song_and_invalid_position() -> None:
    target = SyntheticSeekSession()
    media = media_with(target)
    for position, title, enabled in [
        (42000, target.title, False),
        (42000, "old song", True),
        (-1, target.title, True),
        (200000, target.title, True),
        (True, target.title, True),
    ]:
        target.seek_enabled = enabled
        result = asyncio.run(media.seek(position, title, "synthetic artist", "album"))
        assert result["status"] == "failed"
    assert target.seek_calls == []


def test_accepted_seek_without_position_change_is_uncertain_and_not_retried() -> None:
    target = SyntheticSeekSession()
    target.reflect = False
    result = asyncio.run(media_with(target).seek(42000, target.title, "synthetic artist", "album"))
    assert result["status"] == "uncertain"
    assert target.seek_calls == [450000000]
