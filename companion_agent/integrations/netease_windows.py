"""Windows-only NetEase app handoff and precisely targeted media sessions."""

from __future__ import annotations

import asyncio
import base64
import importlib
import json
import math
import os
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from companion_agent.integrations.netease_catalog import song_id

SOURCE_ID = "cloudmusic.exe"
MediaAction = Literal["play", "pause", "next", "previous"]
MEDIA_ACTIONS = {
    "play": ("is_play_enabled", "try_play_async"),
    "pause": ("is_pause_enabled", "try_pause_async"),
    "next": ("is_next_enabled", "try_skip_next_async"),
    "previous": ("is_previous_enabled", "try_skip_previous_async"),
}


def timeline_snapshot(session: Any, info: Any) -> dict[str, Any]:
    """Project only a real provider timestamp; zero/absent timelines stay unknown."""
    try:
        timeline = session.get_timeline_properties()
        duration = int((timeline.end_time - timeline.start_time).total_seconds() * 1000)
        if not 0 < duration <= 86_400_000:
            return {}
        result: dict[str, Any] = {"duration_ms": duration}
        updated = timeline.last_updated_time
        if not isinstance(updated, datetime) or updated.year < 2000 or updated.tzinfo is None:
            return result
        now = datetime.now(UTC)
        rate = float(info.playback_rate) if info.playback_rate is not None else 1.0
        if not math.isfinite(rate) or not 0 <= rate <= 4:
            return result
        position = (timeline.position - timeline.start_time).total_seconds() * 1000
        if position < 0:
            return result
        if int(info.playback_status) == 4:
            position += max(0, (now - updated).total_seconds()) * 1000 * rate
        result.update(
            position_ms=int(min(duration, position)),
            playback_rate=rate,
            sampled_at_ms=int(now.timestamp() * 1000),
        )
        return result
    except (AttributeError, TypeError, ValueError, OverflowError, OSError):
        return {}


def _candidate_path(value: str) -> Path | None:
    value = value.strip().removesuffix(",0").strip('"')
    path = Path(value)
    # Registry display icons are data, never executable command lines.
    if path.is_absolute() and path.name.lower() == SOURCE_ID and path.is_file():
        return path.resolve()
    return None


def find_executable(explicit: Path | None = None) -> Path | None:
    if explicit is not None:
        return _candidate_path(str(explicit))
    if sys.platform != "win32":
        return None
    import winreg

    uninstall = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(hive, uninstall, 0, winreg.KEY_READ | view) as root:
                    for index in range(winreg.QueryInfoKey(root)[0]):
                        try:
                            with winreg.OpenKey(root, winreg.EnumKey(root, index)) as key:
                                label = str(winreg.QueryValueEx(key, "DisplayName")[0])
                                if label not in {"网易云音乐", "NetEase Cloud Music"}:
                                    continue
                                path = _candidate_path(
                                    str(winreg.QueryValueEx(key, "DisplayIcon")[0])
                                )
                                if path is not None:
                                    return path
                        except OSError:
                            continue
            except OSError:
                continue
    for variable in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        base = os.environ.get(variable)
        if base:
            path = _candidate_path(str(Path(base) / "NetEase" / "CloudMusic" / SOURCE_ID))
            if path is not None:
                return path
    return None


def open_song(identifier: str, executable: Path | None = None) -> dict[str, Any]:
    identifier = song_id(identifier)
    if sys.platform != "win32":
        raise ValueError("当前歌曲打开功能支持 Windows；安卓本机适配尚未接入。")
    target = find_executable(executable)
    if target is None:
        raise ValueError("未找到网易云音乐 Windows 客户端，请先安装并打开一次。")
    payload = json.dumps({"type": "song", "id": identifier, "cmd": "play"}, separators=(",", ":"))
    uri = "orpheus://" + base64.b64encode(payload.encode("utf-8")).decode("ascii")
    try:
        subprocess.Popen(
            [str(target), f"--webcmd={uri}"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError:
        raise ValueError("无法启动网易云音乐，请检查客户端安装。") from None
    return {
        "status": "succeeded",
        "song_id": identifier,
        "url": f"https://music.163.com/song?id={identifier}",
        "delivery": "requested",
        "playback_verified": False,
        "message": "已向网易云提交歌曲打开请求，尚未确认实际播放。账号和歌曲权限由网易云处理。",
    }


class NetEaseMedia:
    def __init__(
        self, *, progress_reader: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    ) -> None:
        self.progress_reader = progress_reader or self._local_progress

    @staticmethod
    def _local_progress(media: dict[str, Any]) -> dict[str, Any]:
        from companion_agent.integrations.netease_progress import local_progress

        return local_progress(media, find_executable())

    async def _manager(self) -> Any:
        if sys.platform != "win32":
            raise ValueError("当前播放控制仅支持 Windows，安卓本机适配尚未接入。")
        try:
            # Lazy imports keep the shared Android engine independent of WinRT.
            importlib.import_module("winrt.windows.foundation.collections")
            importlib.import_module("winrt.windows.media")
            control = importlib.import_module("winrt.windows.media.control")
        except ImportError:
            raise ValueError(
                "此引擎缺少 Windows 媒体组件，请更新心隅或安装 Windows 依赖。"
            ) from None
        return await control.GlobalSystemMediaTransportControlsSessionManager.request_async()

    async def _session(self) -> Any:
        manager = await self._manager()
        matches = [
            s for s in manager.get_sessions() if s.source_app_user_model_id.casefold() == SOURCE_ID
        ]
        if not matches:
            raise ValueError("网易云媒体会话尚未出现。请在网易云播放一首歌并启用系统媒体控制。")
        if len(matches) != 1:
            raise ValueError("检测到多个网易云媒体会话，请关闭多余的网易云窗口后重试。")
        return matches[0]

    async def _snapshot(self, session: Any) -> dict[str, Any]:
        media = await session.try_get_media_properties_async()
        info = session.get_playback_info()
        # Documented GSMTC enum values: Closed, Opened, Changing, Stopped, Playing, Paused.
        states = {0: "closed", 1: "opened", 2: "changing", 3: "stopped", 4: "playing", 5: "paused"}
        return {
            "source": SOURCE_ID,
            "title": str(media.title)[:200],
            "artist": str(media.artist)[:200],
            "album": str(media.album_title)[:200],
            "playback": states.get(int(info.playback_status), "unknown"),
            "controls": {
                **{
                    name: bool(getattr(info.controls, attr, False))
                    for name, (attr, _) in MEDIA_ACTIONS.items()
                },
                "seek": bool(getattr(info.controls, "is_playback_position_enabled", False)),
            },
            **timeline_snapshot(session, info),
        }

    async def state(self) -> dict[str, Any]:
        try:
            async with asyncio.timeout(5):
                session = await self._session()
                state = await self._snapshot(session)
                if "position_ms" not in state and state["playback"] in {"playing", "paused"}:
                    extra = await asyncio.to_thread(self.progress_reader, state)
                    if extra:
                        after = await self._snapshot(session)
                        fields = ("title", "artist", "album", "playback")
                        if all(state[k] == after[k] for k in fields):
                            state.update(extra)
                        else:
                            state = after
            return {"status": "succeeded", "available": True, **state}
        except ValueError as error:
            return {"status": "failed", "available": False, "message": str(error)}
        except Exception:
            return {
                "status": "failed",
                "available": False,
                "message": "无法读取网易云媒体状态，请在网易云中核对系统媒体控制设置。",
            }

    async def seek(self, position_ms: int, title: str, artist: str, album: str) -> dict[str, Any]:
        """Seek the named track once; an accepted command still needs a timeline echo."""
        dispatched = False
        try:
            async with asyncio.timeout(6):
                session = await self._session()
                before = await self._snapshot(session)
                identity = (title, artist, album)
                if tuple(before[k] for k in ("title", "artist", "album")) != identity:
                    raise ValueError("歌曲已变化，请在当前歌曲上重新调整进度。")
                duration = before.get("duration_ms")
                if not before["controls"]["seek"] or not isinstance(duration, int):
                    raise ValueError("网易云未开放进度跳转，请在网易云内调整播放位置。")
                if type(position_ms) is not int or not 0 <= position_ms <= duration:
                    raise ValueError("播放位置超出当前歌曲范围。")
                timeline = session.get_timeline_properties()
                absolute_ms = position_ms + int(timeline.start_time.total_seconds() * 1000)
                low = int(timeline.min_seek_time.total_seconds() * 1000)
                high = int(timeline.max_seek_time.total_seconds() * 1000)
                if high > low and not low <= absolute_ms <= high:
                    raise ValueError("网易云当前不允许跳转到这段位置。")
                dispatched = True
                accepted = await session.try_change_playback_position_async(absolute_ms * 10000)
                if not accepted:
                    return {"status": "failed", "message": "网易云未接受此次进度跳转。"}
                for _ in range(6):
                    await asyncio.sleep(0.15)
                    after = await self._snapshot(session)
                    if tuple(after[k] for k in ("title", "artist", "album")) != identity:
                        break
                    actual = after.get("position_ms")
                    if isinstance(actual, int) and abs(actual - position_ms) <= 2000:
                        return {"status": "succeeded", "verified": True, "state": after}
                return {
                    "status": "uncertain",
                    "verified": False,
                    "message": "跳转请求已提交，但未收到位置确认，请查看网易云，勿连续重试。",
                }
        except Exception as error:
            return {
                "status": "uncertain" if dispatched else "failed",
                "message": str(error)
                if isinstance(error, ValueError)
                else "无法确认进度跳转结果，请查看网易云。",
            }

    async def control(self, action: MediaAction) -> dict[str, Any]:
        if action not in MEDIA_ACTIONS:
            raise ValueError("仅支持 play、pause、next、previous。")
        dispatched = False
        try:
            async with asyncio.timeout(6):
                session = await self._session()
                before = await self._snapshot(session)
                wanted = {"play": "playing", "pause": "paused"}.get(action)
                if wanted and before["playback"] == wanted:
                    return {
                        "status": "succeeded",
                        "changed": False,
                        "state": before,
                        "message": "网易云已经处于所需状态。",
                    }
                if not before["controls"][action]:
                    raise ValueError("网易云当前未提供此操作，请先在客户端检查播放队列。")
                dispatched = True
                accepted = await getattr(session, MEDIA_ACTIONS[action][1])()
                if not accepted:
                    return {
                        "status": "failed",
                        "accepted": False,
                        "message": "网易云未接受此次操作。",
                    }
                for attempt in range(4):
                    if attempt:
                        await asyncio.sleep(0.15)
                    after = await self._snapshot(session)
                    confirmed = (
                        after["playback"] == wanted
                        if wanted
                        else (after["title"], after["artist"], after["album"])
                        != (before["title"], before["artist"], before["album"])
                    )
                    if confirmed:
                        return {
                            "status": "succeeded",
                            "accepted": True,
                            "state": after,
                            "message": "已核对网易云的播放状态变化。",
                        }
                return {
                    "status": "uncertain",
                    "accepted": True,
                    "state": after,
                    "message": "网易云已接受请求，但状态变化尚未确认，请查看客户端，勿自动重试。",
                }
        except ValueError as error:
            return {"status": "uncertain" if dispatched else "failed", "message": str(error)}
        except Exception:
            return {
                "status": "uncertain" if dispatched else "failed",
                "message": "无法确认网易云操作结果，请查看客户端，勿自动重试。",
            }
