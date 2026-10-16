"""Synthetic clock memory and player sessions; no real process is opened."""

from __future__ import annotations

import asyncio
import struct
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from companion_agent.integrations import netease_progress as progress
from companion_agent.integrations.netease_identity import window_matches
from companion_agent.integrations.netease_windows import NetEaseMedia
from tests.test_netease import SyntheticSeekSession, SyntheticSession


def clock_memory(*, token: bytes = b"123_R6G0YG", position: float = 30, duration: float = 180):
    memory = {
        progress.SONG_ROOT: struct.pack("<Q", 0x10000),
        0x10010: struct.pack("<Q", 0x20000),
        0x20000: struct.pack("<Q", 0x30000),
        0x30010: struct.pack("<Q", 0x40000),
        progress.POSITION: struct.pack("<d", position),
        progress.DURATION: struct.pack("<d", duration),
    }
    if len(token) <= 15:
        memory[0x40068] = token.ljust(16, b"\x00") + struct.pack("<QQ", len(token), 15)
    else:
        memory[0x40068] = struct.pack("<QQQQ", 0x50000, 0, len(token), 63)
        memory[0x50000] = token + b"\x00"

    def read(address: int, length: int) -> bytes:
        result = memory[address]
        assert len(result) == length
        return result

    return memory, read


@pytest.mark.parametrize("token", [b"123_R6G0YG", b"123456789123456789_ABCDEFG"])
def test_actual_sample_handles_both_song_token_storage_types(token: bytes) -> None:
    _, read = clock_memory(token=token, position=188.486, duration=298.0000907)
    value = progress.read_clock(read, 0)
    assert value["song_id"] == token.split(b"_")[0].decode()
    assert (value["position_ms"], value["duration_ms"]) == (188486, 298000)
    assert value["timeline_source"] == "netease_local_clock"
    assert "seek" not in value  # Reading a clock never enables writes.


@pytest.mark.parametrize(
    "position,duration",
    [(float("nan"), 180), (float("inf"), 180), (-1, 180), (181, 180), (0, 0), (1, 86401)],
)
def test_invalid_clock_never_becomes_a_playback_position(position: float, duration: float) -> None:
    _, read = clock_memory(position=position, duration=duration)
    with pytest.raises(ValueError):
        progress.read_clock(read, 0)


def test_a_track_change_during_read_discards_the_sample() -> None:
    memory, read = clock_memory()

    def race(address: int, length: int) -> bytes:
        if address == progress.POSITION:
            memory[0x40068] = b"456_R6G0YG".ljust(16, b"\0") + struct.pack("<QQ", 10, 15)
        return read(address, length)

    with pytest.raises(ValueError, match="changing"):
        progress.read_clock(race, 0)


def test_unknown_binary_is_rejected_even_with_the_same_size(tmp_path: Path) -> None:
    path = tmp_path / "cloudmusic.dll"
    with path.open("wb") as file:
        file.truncate(37747192)
    assert not progress._verified_dll(str(path), path.stat().st_size, path.stat().st_mtime_ns)
    assert not progress._verified_dll(str(path), 1, 0)


def test_fallback_only_fills_missing_timeline_and_does_not_enable_seek() -> None:
    target = SyntheticSession()
    _, read = clock_memory()
    calls = []

    def fallback(media):
        calls.append(media)
        return progress.read_clock(read, 0)

    media = NetEaseMedia(progress_reader=fallback)
    media._session = AsyncMock(return_value=target)
    value = asyncio.run(media.state())
    assert value["position_ms"] == 30000 and value["song_id"] == "123"
    assert value["controls"]["seek"] is False and len(calls) == 1
    media._session = AsyncMock(return_value=SyntheticSeekSession())
    assert asyncio.run(media.state())["position_ms"] == 12000
    assert len(calls) == 1


def test_metadata_change_while_reading_rejects_previous_tracks_clock() -> None:
    target = SyntheticSession()
    _, read = clock_memory()

    def change(media):
        target.title = "another song"
        return progress.read_clock(read, 0)

    media = NetEaseMedia(progress_reader=change)
    media._session = AsyncMock(return_value=target)
    result = asyncio.run(media.state())
    assert result["title"] == "another song"
    assert "position_ms" not in result and "song_id" not in result


@pytest.mark.parametrize(
    "window,title,artist,expected",
    [
        ("合成歌 - 甲/乙", "合成歌", "甲", True),
        ("合成歌 - 甲/乙", "合成歌", "甲 / 乙", True),
        ("合成歌 - 甲/乙", "合成歌", "丙", False),
        ("合成歌 - 甲/乙", "合成歌", "甲甲", False),
        ("合成歌 (Live) - 甲/乙", "合成歌", "甲", False),
        ("Other - 甲", "合成歌", "甲", False),
        ("合成歌 - 甲/乙", "合成歌", "/", False),
    ],
)
def test_player_window_accepts_primary_artist_without_guessing_song_version(
    window: str, title: str, artist: str, expected: bool
) -> None:
    assert window_matches(window, title, artist) is expected
