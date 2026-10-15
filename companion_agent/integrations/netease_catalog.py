"""Bounded public song metadata. No account, cookie, audio, or configurable URL."""

from __future__ import annotations

import asyncio
import json
import re
import unicodedata
from html import unescape
from typing import Any, Literal

import httpx

SEARCH_URL = "https://music.163.com/api/search/get/web"
MAX_RESPONSE_BYTES = 1_000_000
SearchType = Literal["song", "lyrics"]


def lyric_text(value: str) -> str:
    """Compare text, not search-engine highlighting or punctuation."""
    value = unicodedata.normalize("NFKC", unescape(re.sub(r"<[^>]*>", "", value)))
    return "".join(c for c in value.casefold() if c.isalnum())


def matches_lyric(query: str, value: Any) -> bool:
    needle = lyric_text(query)
    if len(needle) < 4 or not isinstance(value, list):
        return False
    # Do not expose full returned lyrics to the model or to the action ledger.
    return any(
        needle in lyric_text(line)
        for line in value[:100]
        if isinstance(line, str) and len(line) <= 2000
    )


def song_id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,17}", value):
        raise ValueError("歌曲 ID 必须是 1 到 18 位正整数。请使用搜索结果中的 ID。")
    return value


class NetEaseCatalog:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.transport = transport

    async def search(
        self, query: str, limit: int = 5, search_type: SearchType = "song"
    ) -> dict[str, Any]:
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 120:
            raise ValueError("请输入 1 到 120 字的歌名、歌手或一句歌词。")
        if any(ord(char) < 32 for char in query):
            raise ValueError("搜索词不能包含控制字符。")
        if type(limit) is not int or not 1 <= limit <= 10:
            raise ValueError("每次可以返回 1 到 10 首歌曲。")
        if search_type not in {"song", "lyrics"}:
            raise ValueError("请选择歌曲搜索或歌词搜索。")
        if search_type == "lyrics" and len(lyric_text(query)) < 4:
            raise ValueError("这句歌词太短，请再提供几个字。")
        payload = await self.read_json(
            SEARCH_URL,
            {
                "s": query.strip(),
                "type": 1006 if search_type == "lyrics" else 1,
                "offset": 0,
                "total": "true",
                "limit": limit,
            },
        )
        result = payload.get("result")
        if not isinstance(result, dict) or not isinstance(result.get("songs", []), list):
            raise ValueError("网易云搜索接口格式已变化，当前连接无法解析。")
        songs: list[dict[str, Any]] = []
        for item in result.get("songs", [])[:limit]:
            if not isinstance(item, dict) or type(item.get("id")) is not int:
                continue
            try:
                identifier = song_id(str(item["id"]))
            except ValueError:
                continue
            if not isinstance(item.get("name"), str):
                continue
            artists = item.get("artists", [])
            album = item.get("album", {})
            song = {
                "id": identifier,
                "name": item["name"][:200],
                "artists": [
                    a["name"][:100]
                    for a in artists[:10]
                    if isinstance(a, dict) and isinstance(a.get("name"), str)
                ]
                if isinstance(artists, list)
                else [],
                "album": str(album.get("name", ""))[:200] if isinstance(album, dict) else "",
                "url": f"https://music.163.com/song?id={identifier}",
            }
            duration = item.get("duration")
            if type(duration) is int and 0 < duration <= 86_400_000:
                song["duration_ms"] = duration
            if search_type == "lyrics":
                song["lyric_match"] = matches_lyric(query, item.get("lyrics"))
            from companion_agent.integrations.netease_lyrics import cover_url

            cover = cover_url(album.get("picUrl")) if isinstance(album, dict) else None
            if cover:
                song["cover_url"] = cover
            if not any(previous["id"] == identifier for previous in songs):
                songs.append(song)
        if search_type == "lyrics":
            songs.sort(key=lambda s: not s["lyric_match"])
            await self._covers(songs[:3])
        return {
            "status": "succeeded",
            "query": query.strip(),
            "search_type": search_type,
            "songs": songs,
            "message": (
                "lyric_match=true 表示返回歌词中包含用户给出的片段（忽略标点），不是原唱证明。"
                "false 只代表搜索候选，不能当作已核实。无匹配时请用户补一句歌词或歌手，勿猜歌播放。"
                if search_type == "lyrics"
                else ""
            )
            + "请核对歌名、歌手和版本；搜索排名不代表原唱或可播放权限。",
        }

    async def _covers(self, songs: list[dict[str, Any]]) -> None:
        from companion_agent.integrations.netease_lyrics import cover_url

        missing = {s["id"]: s for s in songs if not s.get("cover_url")}
        if not missing:
            return
        try:
            async with asyncio.timeout(2):
                detail = await self.read_json(
                    "https://music.163.com/api/song/detail/",
                    {"ids": json.dumps([int(i) for i in missing])},
                )
            items = detail.get("songs", [])
            if not isinstance(items, list):
                return
            for item in items[:10]:
                if not isinstance(item, dict):
                    continue
                target = missing.get(str(item.get("id")))
                album = item.get("album", {})
                cover = cover_url(album.get("picUrl")) if isinstance(album, dict) else None
                if target is not None and cover:
                    target["cover_url"] = cover
        except (ValueError, TimeoutError):
            pass  # Artwork is optional; a failed image lookup must not lose song matches.

    async def read_json(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        # Only fixed provider endpoints; never accept a URL from media metadata.
        if url not in {
            SEARCH_URL,
            "https://music.163.com/api/song/detail/",
            "https://music.163.com/api/song/lyric",
        }:
            raise ValueError("不支持的网易云接口。")
        async with httpx.AsyncClient(
            transport=self.transport,
            timeout=8,
            follow_redirects=False,
            trust_env=False,
            headers={"User-Agent": "XinYu-Music/1.0", "Referer": "https://music.163.com/"},
        ) as client:
            try:
                async with (
                    asyncio.timeout(10),
                    client.stream(
                        "GET",
                        url,
                        params=params,
                    ) as response,
                ):
                    response.raise_for_status()
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > MAX_RESPONSE_BYTES:
                            raise ValueError("网易云返回内容过大，暂时无法读取。")
                payload = json.loads(body)
            except (httpx.HTTPError, json.JSONDecodeError, UnicodeDecodeError, TimeoutError):
                raise ValueError("网易云内容暂时不可用，请稍后重试。") from None
        if not isinstance(payload, dict) or payload.get("code") != 200:
            raise ValueError("网易云未返回可用内容。")
        return payload
