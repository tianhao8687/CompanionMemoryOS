"""Synthetic lyric data only. Tests never use accounts, live music or a real LLM."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from companion_agent.integrations.netease_catalog import NetEaseCatalog
from companion_agent.integrations.netease_lyrics import cover_url, fetch_lyrics, parse_lrc
from companion_agent.integrations.netease_windows import timeline_snapshot
from companion_agent.music_lyrics import exact_version
from tests.test_music import listening as listening_fixture
from tests.test_music import poll

listening = listening_fixture


def test_lrc_timestamps_offset_duets_metadata_and_plain_text() -> None:
    parsed = parse_lrc(
        "[ar:synthetic]\n[offset:250]\n[00:01.5][00:03.125]第一行\n"
        "[00:01.500]合唱\n[00:01.500]第一行\n[00:05.00]第二行"
    )
    assert parsed == {
        "timed": True,
        "truncated": False,
        "lines": [
            {"time_ms": 1250, "text": "第一行"},
            {"time_ms": 1250, "text": "合唱"},
            {"time_ms": 2875, "text": "第一行"},
            {"time_ms": 4750, "text": "第二行"},
        ],
    }
    assert parse_lrc("[ti:synthetic]\n没有时间戳") == {
        "timed": False,
        "truncated": False,
        "lines": [{"time_ms": None, "text": "没有时间戳"}],
    }
    assert parse_lrc(None)["lines"] == []
    assert parse_lrc("[offset:500]\n[00:00.10]开场")["lines"][0]["time_ms"] == 0
    with pytest.raises(ValueError):
        parse_lrc("[00:00.00]" + "x" * 501)
    assert parse_lrc("\n".join(f"[00:00.00]{i}" for i in range(501)))["truncated"]


@pytest.mark.parametrize(
    "url",
    [
        "file:///private",
        "https://127.0.0.1/private",
        "https://p1.music.126.net.evil.invalid/a",
        "https://user@p1.music.126.net/a",
        "https://p1.music.126.net:123/a",
        "https://p1.music.126.net:not-a-port/a",
    ],
)
def test_album_art_accepts_only_known_provider_hosts(url: str) -> None:
    assert cover_url(url) is None


def test_cover_upgrades_https_and_discards_query_credentials() -> None:
    assert cover_url("http://p2.music.126.net/a.jpg?untrusted=1#fragment") == (
        "https://p2.music.126.net/a.jpg?param=600y600"
    )


def test_matching_keeps_live_versions_artist_album_and_duration_distinct() -> None:
    media = {"title": "合成歌", "artist": "甲 / 乙", "album": "合成专辑", "duration_ms": 180000}
    song = {"name": "合成歌", "artists": ["甲", "乙"], "album": "合成专辑", "duration_ms": 181000}
    assert exact_version(media, song)
    for changes in [
        {"name": "合成歌 (Live)"},
        {"artists": ["丙"]},
        {"album": "其他专辑"},
        {"duration_ms": 240000},
    ]:
        assert not exact_version(media, {**song, **changes})
    assert not exact_version({**media, "album": ""}, song)


def test_windows_uses_provider_timeline_and_keeps_absent_progress_unknown() -> None:
    timeline = SimpleNamespace(
        start_time=timedelta(0),
        end_time=timedelta(seconds=180),
        position=timedelta(seconds=30),
        last_updated_time=datetime.now(UTC) - timedelta(seconds=2),
    )
    session = SimpleNamespace(get_timeline_properties=lambda: timeline)
    info = SimpleNamespace(playback_rate=1.0, playback_status=4)
    assert 32000 <= timeline_snapshot(session, info)["position_ms"] < 32500
    info.playback_status = 5
    assert timeline_snapshot(session, info)["position_ms"] == 30000
    timeline.last_updated_time = datetime(1601, 1, 1, tzinfo=UTC)
    assert timeline_snapshot(session, info) == {"duration_ms": 180000}
    timeline.end_time = timedelta(0)
    assert timeline_snapshot(session, info) == {}
    assert timeline_snapshot(SimpleNamespace(), info) == {}


def test_verified_song_id_resolves_same_named_versions_without_guessing(listening: Any) -> None:
    f = listening
    setup_catalog(f, ambiguous=True)
    f.bridge.state.update(song_id="456", album="", timeline_source="netease_local_clock")
    f.now[0] += 2
    poll(f)
    result = request_lyrics(f).json()
    assert result["song_id"] == "456" and result["match"] == "exact"
    assert f.host.music.public()["media"]["timeline_source"] == "netease_local_clock"
    # An absent search result or conflicting song ID never chooses a nearby version.
    f.bridge.state["song_id"] = "999"
    f.now[0] += 2
    poll(f)
    assert request_lyrics(f).json()["status"] == "choose"
    assert not f.model.inputs


def setup_catalog(f: Any, *, ambiguous: bool = False, callback: Any = None) -> list[str]:
    calls: list[str] = []
    f.bridge.state.update(album="合成专辑", duration_ms=180000)
    f.now[0] += 5
    poll(f)

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "music.163.com"
        calls.append(request.url.path)
        if request.url.path.endswith("get/web"):
            return httpx.Response(
                200,
                json={
                    "code": 200,
                    "result": {
                        "songs": [
                            {
                                "id": i,
                                "name": "合成歌曲",
                                "artists": [{"name": "测试歌手"}],
                                "album": {"name": "合成专辑"},
                                "duration": 180000,
                            }
                            for i in ([123, 456] if ambiguous else [123])
                        ]
                    },
                },
            )
        if request.url.path.endswith("lyric"):
            if callback:
                callback()
            return httpx.Response(
                200, json={"code": 200, "lrc": {"lyric": "[00:00.00]合成测试歌词"}}
            )
        if request.url.path.endswith("detail/"):
            return httpx.Response(
                200,
                json={
                    "code": 200,
                    "songs": [
                        {"id": 123, "album": {"picUrl": "http://p1.music.126.net/synthetic.jpg"}}
                    ],
                },
            )
        pytest.fail("unexpected provider request")

    catalog = NetEaseCatalog(httpx.MockTransport(respond))
    f.host.tools.client.catalog = catalog
    f.host.music.lyrics.catalog = catalog
    return calls


def request_lyrics(f: Any, **changes: Any) -> Any:
    return f.client.post(
        "/api/music/lyrics",
        json={**f.item, "track_key": f.host.music.public()["media"]["track_key"], **changes},
    )


def test_ui_lyrics_match_cache_and_do_not_enter_chat_or_model(listening: Any) -> None:
    f = listening
    calls = setup_catalog(f)
    first = request_lyrics(f)
    assert first.status_code == 200, first.text
    result = first.json()
    assert result["status"] == "ready" and result["match"] == "exact"
    assert result["lines"][0]["text"] == "合成测试歌词"
    assert result["cover_url"].startswith("https://p1.music.126.net/")
    assert request_lyrics(f).json() == result
    assert len(calls) == 3
    assert "合成测试歌词" not in f.host.music.context(f.item["conversation_id"])
    assert "lines" not in f.host.music.public() and f.model.inputs == []


def test_ambiguous_versions_require_choice_and_reject_arbitrary_id(listening: Any) -> None:
    f = listening
    calls = setup_catalog(f, ambiguous=True)
    assert request_lyrics(f).json()["status"] == "choose"
    assert len(calls) == 1
    assert request_lyrics(f, song_id="999").status_code == 422
    assert len(calls) == 1
    assert request_lyrics(f, song_id="123").json()["match"] == "selected"
    assert len(calls) == 3


@pytest.mark.parametrize("change", ["track", "end", "permission"])
def test_changed_song_ended_session_or_revoked_connection_discard_inflight_lyrics(
    listening: Any,
    change: str,
) -> None:
    f = listening

    def changed() -> None:
        if change == "track":
            f.host.music.session["media"]["title"] = "另一首合成歌"
        elif change == "end":
            f.host.music.session = None
        else:
            f.host.tools.config.servers[0].enabled = False

    setup_catalog(f, callback=changed)
    response = request_lyrics(f)
    assert response.status_code == 422
    assert "合成测试歌词" not in response.text


@pytest.mark.parametrize(
    "payload,status", [({"nolyric": True}, "instrumental"), ({}, "unavailable")]
)
def test_empty_or_instrumental_lyrics_are_honest_states(payload: dict, status: str) -> None:
    catalog = NetEaseCatalog(
        httpx.MockTransport(lambda _: httpx.Response(200, json={"code": 200, **payload}))
    )
    result = asyncio.run(fetch_lyrics(catalog, "123"))
    assert result["status"] == status and result["lines"] == []


def test_lyrics_provider_failure_returns_no_invented_content() -> None:
    catalog = NetEaseCatalog(httpx.MockTransport(lambda _: httpx.Response(503)))
    with pytest.raises(ValueError, match="没取到"):
        asyncio.run(fetch_lyrics(catalog, "123"))
