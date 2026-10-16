"""Silent point-song adapter. Missing background support is an explicit failure."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

import httpx

from companion_agent.integrations.netease_catalog import song_id
from companion_agent.integrations.netease_cdp_channel import (
    MAX_BYTES,
    BackgroundUnavailable,
    LocalChannel,
)
from companion_agent.integrations.netease_cdp_profiles import RUNTIME_PROFILES
from companion_agent.integrations.netease_cdp_scripts import (
    BOOTSTRAP,
    PLAY,
    READ_STATE,
    WATCH_PROGRESS,
)

MESSAGES = {
    "background_not_initialized": "网易云尚未开启本机后台通道，需要单独完成一次初始化。",
    "background_unavailable": "网易云后台通道暂不可用，请检查客户端是否已正常运行。",
    "unsupported_client_version": "这版网易云尚未通过后台点歌适配检查。",
    "unsupported_client_runtime": "网易云内部接口已变化，已停止后台点歌，等待适配更新。",
    "login_required": "请先在网易云完成登录，再使用后台点歌。",
    "nonlocal_listener": "网易云控制端口未限定为本机连接，已拒绝使用。",
    "nonlocal_target": "网易云返回了非预期控制地址，已拒绝连接。",
    "wrong_channel_owner": "本机控制端口不属于已确认的网易云客户端，已拒绝使用。",
    "missing_background_component": "此引擎缺少后台音乐组件，请更新心隅引擎。",
    "background_busy": "上一条后台音乐操作尚未结束，请稍后查看播放状态。",
    "queue_changed": "播放队列在操作期间发生变化，已停止后续操作。",
    "queue_full": "网易云播放队列已满；为保留原队列，本次未添加歌曲。",
    "unsupported_play_mode": "当前电台或特殊播放模式暂不支持静默点歌，未改变原队列。",
    "invalid_song_detail": "未取得这首歌的有效资料，本次未播放。",
    "playback_unverified": "已提交后台播放，但尚未同时确认目标歌曲与进度推进，请勿重复点歌。",
    "channel_changed": "网易云控制进程已变化，未继续发送指令。",
    "background_timeout": "网易云后台通道响应超时，请先查看当前播放状态。",
}


def failure(reason: str, *, dispatched: bool = False) -> dict[str, Any]:
    return {
        "status": "uncertain" if dispatched else "failed",
        "reason": reason,
        "transport": "local_cdp",
        "delivery": "requested" if dispatched else "not_sent",
        "playback_verified": False,
        "message": MESSAGES.get(reason, "后台音乐操作未能确认，未使用窗口唤起或模拟点击。"),
    }


def check_profile(value: Any, version: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not isinstance(value.get("proof"), dict):
        raise BackgroundUnavailable("unsupported_client_runtime")
    proof = value["proof"]
    if not all(isinstance(source, str) for source in proof.values()):
        raise BackgroundUnavailable("unsupported_client_runtime")
    hashes = {key: hashlib.sha256(source.encode()).hexdigest() for key, source in proof.items()}
    matches = [
        name for name, expected in RUNTIME_PROFILES.get(version, {}).items() if hashes == expected
    ]
    if len(matches) != 1:
        raise BackgroundUnavailable("unsupported_client_runtime")
    state = value.get("state")
    if not isinstance(state, dict):
        raise BackgroundUnavailable("unsupported_client_runtime")
    return {**state, "client_version": version, "runtime_profile": matches[0]}


def track_detail(identifier: str, *, deadline: float) -> dict[str, Any]:
    """One bounded public metadata request. No audio URLs, cookies, or redirects."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise BackgroundUnavailable("background_timeout")
    with (
        httpx.Client(timeout=min(4, remaining), follow_redirects=False, trust_env=False) as client,
        client.stream(
            "GET",
            "https://music.163.com/api/song/detail",
            params={"ids": json.dumps([int(identifier)])},
            headers={"Referer": "https://music.163.com/"},
        ) as response,
    ):
        if response.status_code != 200:
            raise BackgroundUnavailable("invalid_song_detail")
        data = bytearray()
        for part in response.iter_bytes():
            if time.monotonic() >= deadline:
                raise BackgroundUnavailable("background_timeout")
            data.extend(part)
            if len(data) > MAX_BYTES:
                raise BackgroundUnavailable("invalid_song_detail")
    value = json.loads(data)
    if not isinstance(value, dict) or value.get("code") != 200:
        raise BackgroundUnavailable("invalid_song_detail")
    songs = value.get("songs")
    if not isinstance(songs, list) or len(songs) != 1 or not isinstance(songs[0], dict):
        raise BackgroundUnavailable("invalid_song_detail")
    track = songs[0]
    if type(track.get("id")) is not int or str(track["id"]) != identifier:
        raise BackgroundUnavailable("invalid_song_detail")
    return dict(track)


def compact_state(state: dict[str, Any]) -> dict[str, Any]:
    """Never expose a queue, fingerprints, native object, or script to the model."""
    result: dict[str, Any] = {
        "status": "succeeded",
        "available": True,
        "source": "cloudmusic.exe",
        "title": str(state.get("title", ""))[:200],
        "artist": str(state.get("artist", ""))[:200],
        "album": str(state.get("album", ""))[:200],
        "playback": state.get("playback", "unknown"),
        "controls": dict.fromkeys(("play", "pause", "next", "previous", "seek"), False),
    }
    identifier = state.get("song_id")
    if isinstance(identifier, str) and identifier:
        result["song_id"] = song_id(identifier)
    for key in ("position_ms", "duration_ms", "sampled_at_ms"):
        if type(state.get(key)) is int and state[key] >= 0:
            result[key] = state[key]
    if "position_ms" in result:
        result["timeline_source"] = "netease_native_cdp"
        result["playback_rate"] = 1.0 if result["playback"] == "playing" else 0.0
    access = state.get("playback_access", "unknown")
    result["playback_access"] = (
        access if access in {"full", "preview", "full_trial", "unknown"} else "unknown"
    )
    if result["playback_access"] == "preview":
        start, end = state.get("preview_start_ms"), state.get("preview_end_ms")
        if type(start) is int and type(end) is int and 0 <= start < end:
            result.update(preview_start_ms=start, preview_end_ms=end)
    return result


class BackgroundPlayer:
    def __init__(self, executable: Path) -> None:
        self.executable = executable

    def state(self) -> dict[str, Any]:
        try:
            with LocalChannel(self.executable) as channel:
                check_profile(channel.evaluate(BOOTSTRAP), channel.version)
                channel.evaluate(WATCH_PROGRESS, await_promise=True)
                state = channel.evaluate(READ_STATE)
                if not isinstance(state, dict):
                    raise BackgroundUnavailable("unsupported_client_runtime")
                return compact_state(state)
        except Exception as error:
            reason = (
                error.reason
                if isinstance(error, BackgroundUnavailable)
                else "background_unavailable"
            )
            return {**failure(reason), "available": False}

    def play(self, identifier: str) -> dict[str, Any]:
        identifier = song_id(identifier)
        if int(identifier) > 2**53 - 1:
            return failure("invalid_song_detail")
        dispatched = False
        try:
            with LocalChannel(self.executable) as channel:
                before = check_profile(channel.evaluate(BOOTSTRAP), channel.version)
                if before.get("anonymous"):
                    return failure("login_required")
                channel.evaluate(WATCH_PROGRESS, await_promise=True)
                track = track_detail(identifier, deadline=channel.deadline)
                request = json.dumps({"song_id": identifier, "track": track}, ensure_ascii=True)
                expression = PLAY.replace("__REQUEST__", json.dumps(request))
                # From this point, a transport timeout may mean a command was accepted.
                # Do not resend, launch the app, restore focus, or invoke any fallback.
                dispatched = True
                receipt = channel.evaluate(expression, await_promise=True)
                if not isinstance(receipt, dict):
                    return failure("playback_unverified", dispatched=True)
                if receipt.get("status") != "requested":
                    return failure(
                        str(receipt.get("reason", "client_operation_failed")),
                        dispatched=bool(receipt.get("dispatched", True)),
                    )
                if receipt.get("queue_preserved") is not True:
                    return failure("queue_changed", dispatched=True)
                return self._confirm(channel, identifier, receipt)
        except Exception as error:
            reason = (
                error.reason
                if isinstance(error, BackgroundUnavailable)
                else "background_unavailable"
            )
            return failure(reason, dispatched=dispatched)

    @staticmethod
    def _confirm(channel: LocalChannel, identifier: str, receipt: dict[str, Any]) -> dict[str, Any]:
        first: dict[str, Any] | None = None
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            state = channel.evaluate(READ_STATE)
            if not isinstance(state, dict):
                break
            if state.get("queue_signature") != receipt.get("queue_signature") or state.get(
                "mode"
            ) != receipt.get("mode"):
                return failure("queue_changed", dispatched=True)
            if (
                state.get("song_id") == identifier
                and state.get("playback") == "playing"
                and type(state.get("position_ms")) is int
                and type(state.get("sampled_at_ms")) is int
                and 0 <= time.time() * 1000 - state["sampled_at_ms"] <= 3000
            ):
                if (
                    first is not None
                    and state["sampled_at_ms"] > first["sampled_at_ms"]
                    and state["position_ms"] > first["position_ms"] + 200
                ):
                    access = state.get("playback_access", "unknown")
                    played = {
                        "full": "已确认目标歌曲正在完整播放",
                        "preview": "已确认目标歌曲正在播放网易云提供的试听片段",
                        "full_trial": "已确认目标歌曲正在进行网易云提供的全曲试听",
                    }.get(access, "已确认目标歌曲正在播放，完整版或试听类型尚不明确")
                    return {
                        "status": "succeeded",
                        "transport": "local_cdp",
                        "song_id": identifier,
                        "url": f"https://music.163.com/song?id={identifier}",
                        "delivery": "verified",
                        "playback_verified": True,
                        "queue_preserved": True,
                        "appended": receipt.get("appended") is True,
                        "state": compact_state(state),
                        "message": f"{played}，进度已推进，原队列及播放模式已保留。",
                    }
                first = first or state
            else:
                first = None
            time.sleep(0.25)
        return failure("playback_unverified", dispatched=True)
