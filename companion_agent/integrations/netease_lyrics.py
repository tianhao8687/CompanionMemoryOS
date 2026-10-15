"""Display-only NetEase lyrics and artwork; never added to chat or memory."""

from __future__ import annotations

import asyncio
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from companion_agent.integrations.netease_catalog import NetEaseCatalog, song_id

STAMP = re.compile(r"\[(\d{1,3}):([0-5]\d)(?:[.:](\d{1,3}))?\]")


def parse_lrc(value: Any) -> dict[str, Any]:
    if not isinstance(value, str) or not value.strip():
        return {"lines": [], "timed": False, "truncated": False}
    if len(value) > 200_000:
        raise ValueError("歌词内容过长，暂时无法显示。")
    offsets = re.findall(r"\[offset:([+-]?\d{1,7})\]", value, re.IGNORECASE)
    offset = int(offsets[-1]) if offsets else 0
    timed: list[dict[str, Any]] = []
    plain: list[dict[str, Any]] = []
    for raw in value.splitlines():
        stamps = list(STAMP.finditer(raw))
        text = STAMP.sub("", raw).strip()
        text = re.sub(r"<\d{1,3}:[0-5]\d[.:]\d{1,3}>", "", text).strip()
        if not text or re.fullmatch(r"\[[a-z]+:.*\]", text, re.IGNORECASE):
            continue
        if len(text) > 500:
            raise ValueError("歌词行过长，暂时无法显示。")
        if not stamps:
            plain.append({"time_ms": None, "text": text})
        for stamp in stamps:
            minutes, seconds, fraction = stamp.groups()
            milliseconds = (int(minutes) * 60 + int(seconds)) * 1000
            milliseconds += int((fraction or "0").ljust(3, "0"))
            timed.append({"time_ms": max(0, milliseconds - offset), "text": text})
    # Preserve simultaneous lines (duets); eliminate only exact repetitions.
    unique = {(line["time_ms"], line["text"]): line for line in timed}
    lines = sorted(unique.values(), key=lambda line: line["time_ms"]) if timed else plain
    return {"lines": lines[:500], "timed": bool(timed), "truncated": len(lines) > 500}


def cover_url(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) > 1500:
        return None
    try:
        url = urlsplit(value)
        if (
            url.scheme not in {"http", "https"}
            or not re.fullmatch(r"p[1-9]\.music\.126\.net", url.hostname or "")
            or url.username
            or url.password
            or url.port not in {None, 80, 443}
        ):
            return None
        return urlunsplit(("https", url.hostname or "", url.path, "param=600y600", ""))
    except ValueError:
        return None


async def fetch_lyrics(catalog: NetEaseCatalog, identifier: str) -> dict[str, Any]:
    identifier = song_id(identifier)
    responses: tuple[
        dict[str, Any] | BaseException, dict[str, Any] | BaseException
    ] = await asyncio.gather(
        catalog.read_json(
            "https://music.163.com/api/song/lyric", {"id": identifier, "lv": -1, "tv": -1}
        ),
        catalog.read_json(
            "https://music.163.com/api/song/detail/", {"id": identifier, "ids": f"[{identifier}]"}
        ),
        return_exceptions=True,
    )
    lyrics, detail = responses
    if isinstance(lyrics, BaseException):
        raise ValueError("歌词暂时没取到，可以稍后重试。") from None
    lrc = lyrics.get("lrc", {})
    parsed = parse_lrc(lrc.get("lyric") if isinstance(lrc, dict) else None)
    result: dict[str, Any] = {
        "status": "ready" if parsed["lines"] else "unavailable",
        "song_id": identifier,
        **parsed,
        "source": "网易云音乐",
        "message": "" if parsed["lines"] else "这首歌暂时没有提供歌词。",
    }
    if lyrics.get("nolyric") is True or (
        len(parsed["lines"]) == 1 and "纯音乐，请欣赏" in parsed["lines"][0]["text"]
    ):
        result.update(status="instrumental", lines=[], timed=False, message="纯音乐，静静听就好。")
    if isinstance(detail, dict):
        songs = detail.get("songs", [])
        if isinstance(songs, list):
            for song in songs:
                if not isinstance(song, dict) or str(song.get("id")) != identifier:
                    continue
                album = song.get("album", {})
                if isinstance(album, dict):
                    result["cover_url"] = cover_url(album.get("picUrl"))
    return result
