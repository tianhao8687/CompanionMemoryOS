"""Bounded read-only confirmation after an authorized bundled music handoff."""

from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from companion_agent.automation.bundled_music import is_bundled_music

if TYPE_CHECKING:
    from companion_agent.automation.hub import ToolHub
    from companion_agent.automation.models import MCPServerConfig


def confirm_playback(
    hub: ToolHub,
    server: MCPServerConfig,
    tool: dict[str, Any],
    conversation: str,
    request_id: str,
    result: dict[str, Any],
    remaining: float,
) -> dict[str, Any]:
    # Only extend a playback read which has already passed its own permission
    # check. Never read implicitly from open_song, or repeat a write operation.
    if tool["name"] != "netease_playback_state" or not is_bundled_music(server, sys.executable):
        return result
    from companion_agent.music_requests import OPEN, SEARCH, playback_receipt, songs_from

    with hub.store.database.connection() as db:
        opened = db.execute(
            "SELECT * FROM agent_actions WHERE conversation_id=? AND tool_name=? "
            "ORDER BY rowid DESC LIMIT 1",
            (conversation, OPEN),
        ).fetchone()
        search = db.execute(
            "SELECT result FROM agent_actions WHERE conversation_id=? AND request_id=? "
            "AND tool_name=? AND status='succeeded' ORDER BY rowid DESC LIMIT 1",
            (conversation, request_id, SEARCH),
        ).fetchone()
    if (
        opened is None
        or opened["request_id"] != request_id
        or opened["status"] != "succeeded"
        or not 0
        <= (datetime.now(UTC) - datetime.fromisoformat(opened["updated_at"])).total_seconds()
        <= 30
    ):
        return result
    identifier = json.loads(opened["arguments"]).get("song_id")
    if not isinstance(identifier, str):
        return result
    songs = songs_from(json.loads(search["result"])) if search else []
    selected = next(
        (s for s in songs if s["id"] == identifier),
        {
            "id": identifier,
            "name": "",
            "artists": [],
            "album": "",
        },
    )
    deadline = time.monotonic() + min(10.0, max(0.0, remaining))
    checks = 1
    while checks < 4:
        media = result.get("data", {})
        starting = (
            isinstance(media, dict)
            and media.get("available") is False
            and media.get("reason") in {"player_closed", "media_unavailable"}
        )
        if (
            (
                result.get("status") != "succeeded"
                and not (starting and result.get("status") == "failed")
            )
            or not isinstance(media, dict)
            or (media.get("available") is not True and not starting)
            or playback_receipt(selected, media) != "requested"
        ):
            break
        delay = 1.0 if checks == 1 else 2.0
        # Android's native read reserves four seconds; desktop MCP startup is
        # also included. Stop within the caller's remaining execution budget.
        if deadline - time.monotonic() < delay + 4.0:
            break
        time.sleep(delay)
        try:
            observation = hub.client.call(
                server, tool["name"], {}, tool, deadline - time.monotonic()
            )
        except Exception:
            break
        checks += 1
        result = observation
    media = result.get("data", {})
    if not isinstance(media, dict):
        return result
    state = playback_receipt(selected, media)
    if state == "requested":
        if str(media.get("song_id", "")) == identifier and media.get("playback") == "paused":
            state = "paused"
        elif media.get("available") is True and media.get("song_id"):
            state = "not_started"
        else:
            state = "unverified"
    confirmation = {
        "song_id": identifier,
        "state": state,
        "checks": checks,
        "message": {
            "verified": "已核对到目标歌曲正在播放。",
            "metadata_matched": "已按完整歌曲信息匹配到正在播放的曲目。",
            "paused": "已切到目标歌曲，但播放器处于暂停状态。",
            "not_started": "播放器仍是其他歌曲，未检测到目标歌曲开始播放。",
            "unverified": "播放器信息不足，无法核实目标歌曲是否开始播放。",
        }[state]
        + "不要重复提交播放请求，也不要猜测会员限制或建议重启。",
    }
    data = {**media, "confirmation": confirmation}
    return {**result, "data": data, "text": json.dumps(data, ensure_ascii=False)}
