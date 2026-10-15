"""Ephemeral lyric resolution scoped to the live shared-listening session."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
import unicodedata
from collections import OrderedDict
from copy import deepcopy
from threading import RLock
from typing import TYPE_CHECKING, Any

from pydantic import Field

from companion_agent.automation.mcp_client import MCPFailure
from companion_agent.integrations.netease_catalog import NetEaseCatalog, song_id
from companion_agent.integrations.netease_lyrics import fetch_lyrics
from companion_agent.persona.models import PersonaModel

if TYPE_CHECKING:
    from companion_agent.music import MusicCompanion


class MusicLyricsInput(PersonaModel):
    conversation_id: str = Field(min_length=1, max_length=128)
    session_id: str = Field(min_length=1, max_length=128)
    track_key: str = Field(min_length=1, max_length=64)
    song_id: str = Field(default="", max_length=18)


def track_key(media: dict[str, Any]) -> str:
    identity = [
        media.get(key) for key in ("source", "title", "artist", "album", "duration_ms", "song_id")
    ]
    return hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()[:24]


def normalized(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def exact_version(media: dict[str, Any], song: dict[str, Any]) -> bool:
    identifier = media.get("song_id")
    if identifier is not None and identifier != song.get("id"):
        return False
    artist = str(media.get("artist", ""))
    artists = {normalized(a) for a in re.split(r"\s*[/、,，]\s*", artist) if a.strip()}
    expected = {normalized(a) for a in song.get("artists", [])}
    duration, candidate_duration = media.get("duration_ms"), song.get("duration_ms")
    return bool(
        normalized(str(media.get("title", ""))) == normalized(song.get("name", ""))
        and artists
        and artists == expected
        and (
            (identifier == song.get("id") and identifier is not None)
            or (
                media.get("album")
                and normalized(str(media["album"])) == normalized(song.get("album", ""))
            )
        )
        and (
            duration is None
            or (
                type(duration) is int
                and type(candidate_duration) is int
                and abs(duration - candidate_duration) <= 2000
            )
        )
    )


class ListeningLyrics:
    def __init__(self, music: MusicCompanion) -> None:
        self.music = music
        self.catalog = NetEaseCatalog()
        self.lock = RLock()
        self.choices: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
        self.cache: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()

    def _current(self, item: MusicLyricsInput) -> dict[str, Any]:
        music = self.music
        session = music.session
        if (
            not music.active(item.conversation_id)
            or not music._authorized()
            or session is None
            or session["id"] != item.session_id
            or session["media"].get("available") is not True
            or track_key(session["media"]) != item.track_key
        ):
            raise ValueError("歌曲或连接已变化，请等待播放状态更新。")
        return dict(session["media"])

    def read(self, item: MusicLyricsInput) -> dict[str, Any]:
        self.music.host.scope(item.conversation_id)
        with self.music.lock:
            media = self._current(item)
        # Network work must not hold the music lock: pause, end and quiet stay responsive.
        with self.lock:
            key = item.session_id + ":" + item.track_key
            choices = self.choices.get(key)
            if choices is None:
                query = " ".join(str(media.get(k, "")).strip() for k in ("title", "artist")).strip()
                if not query:
                    return {"status": "unavailable", "message": "等待网易云提供歌名。"}
                args = {"query": query[:120], "limit": 8}
                with self.music.host.tools.lock:
                    server, tool = self.music._binding("netease_search_songs", args)
                    try:
                        found = self.music.host.tools.client.call(server, tool["name"], args, tool)
                    except MCPFailure:
                        raise ValueError("网易云歌曲查询暂时不可用，请稍后重试。") from None
                data = found.get("data")
                if not isinstance(data, dict) or data.get("status") != "succeeded":
                    raise ValueError("暂时无法匹配歌词，请稍后重试。")
                choices = data.get("songs", [])
                if not isinstance(choices, list):
                    raise ValueError("歌曲列表暂时无法读取。")
                self.choices[key] = choices
                while len(self.choices) > 24:
                    self.choices.popitem(last=False)
            selected = next((s for s in choices if s["id"] == item.song_id), None)
            if item.song_id:
                song_id(item.song_id)
                if selected is None:
                    raise ValueError("请从当前歌曲的匹配结果中选择版本。")
            else:
                matches = [s for s in choices if exact_version(media, s)]
                selected = matches[0] if len(matches) == 1 else None
            if selected is None:
                result: dict[str, Any] = {
                    "status": "choose" if choices else "unavailable",
                    "candidates": choices,
                    "message": "选一下正在听的版本" if choices else "暂未找到这首歌的歌词。",
                }
            else:
                identifier = selected["id"]
                cached = self.cache.get(identifier)
                if cached is None or time.monotonic() - cached[0] > 1800:
                    value = asyncio.run(fetch_lyrics(self.catalog, identifier))
                    self.cache[identifier] = (time.monotonic(), value)
                    while len(self.cache) > 24:
                        self.cache.popitem(last=False)
                result = {
                    **deepcopy(self.cache[identifier][1]),
                    "song": selected,
                    "candidates": choices,
                    "match": "selected" if item.song_id else "exact",
                }
        with self.music.lock:
            self._current(item)
        return {**result, "track_key": item.track_key}
