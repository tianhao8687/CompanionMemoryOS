"""Read-only fallback for a verified NetEase Windows player build.

Only the playback clock and current song token are read. No scanning, injection,
process writes, user databases, audio capture, or elevation. An unknown DLL is
unsupported until its layout has been verified; see docs/NETEASE_AUTO_SYNC.md.
"""

from __future__ import annotations

import ctypes
import hashlib
import math
import re
import struct
import sys
import time
from collections.abc import Callable
from ctypes import wintypes as w
from functools import lru_cache
from pathlib import Path
from typing import Any

from companion_agent.integrations.netease_identity import window_matches

# NetEase 3.1.41 (205529), Patch c6406e5, x64; verified locally, not a version guess.
DLL_SHA256 = "7f667f876caf94bc3dac3b0070d3e495117005fafdcf18b6aaa51eb004edac8c"
DLL_IMAGE_SIZE = 41054208
POSITION = 0x21A74D8
DURATION = 0x2214778
SONG_ROOT = 0x2213A70
ReadBytes = Callable[[int, int], bytes]


def read_song_id(read: ReadBytes, base: int) -> str:
    address = struct.unpack("<Q", read(base + SONG_ROOT, 8))[0]
    for offset in (0x10, 0, 0x10):
        address = struct.unpack("<Q", read(address + offset, 8))[0]
    value = read(address + 0x68, 32)
    length, capacity = struct.unpack_from("<QQ", value, 16)
    if not 0 < length <= 64 or not length <= capacity <= 4096:
        raise ValueError("invalid song slot")
    if capacity == 15 and length <= 15:
        token = value[: length + 1]
    elif capacity >= 16:
        token = read(struct.unpack_from("<Q", value)[0], length + 1)
    else:
        raise ValueError("invalid song storage")
    match = re.fullmatch(rb"([1-9][0-9]{0,17})(?:_[A-Za-z0-9]{1,32})?\x00", token)
    if match is None:
        raise ValueError("invalid song token")
    return match[1].decode("ascii")


def read_clock(read: ReadBytes, base: int) -> dict[str, Any]:
    """Sandwich a bounded clock read with identity reads to reject track races."""
    identifier = read_song_id(read, base)
    duration = struct.unpack("<d", read(base + DURATION, 8))[0]
    position = struct.unpack("<d", read(base + POSITION, 8))[0]
    after_duration = struct.unpack("<d", read(base + DURATION, 8))[0]
    if (
        read_song_id(read, base) != identifier
        or duration != after_duration
        or not math.isfinite(position)
        or not math.isfinite(duration)
        or not 1 <= duration <= 86400
        or not 0 <= position <= duration
    ):
        raise ValueError("invalid or changing playback clock")
    return {
        "song_id": identifier,
        "position_ms": round(position * 1000),
        "duration_ms": round(duration * 1000),
        "sampled_at_ms": time.time_ns() // 1_000_000,
        "playback_rate": 1.0,
        "timeline_source": "netease_local_clock",
    }


@lru_cache(maxsize=4)
def _verified_dll(path: str, size: int, modified_ns: int) -> bool:
    # Size and mtime form the cache key; the actual content must match, too.
    if size != 37747192:
        return False
    with Path(path).open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest() == DLL_SHA256


class _ModuleInfo(ctypes.Structure):
    _fields_ = [("base", ctypes.c_void_p), ("size", w.DWORD), ("entry", ctypes.c_void_p)]


class _WindowsReader:
    kernel: ctypes.CDLL
    user: ctypes.CDLL
    psapi: ctypes.CDLL
    callback_type: Any

    def __init__(self) -> None:
        if sys.platform == "win32":
            self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            self.user = ctypes.WinDLL("user32", use_last_error=True)
            self.psapi = ctypes.WinDLL("psapi", use_last_error=True)
            self.callback_type = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
        else:
            raise OSError("The native playback clock requires Windows.")
        signatures: tuple[tuple[Any, list[Any], Any], ...] = (
            (self.user.EnumWindows, [self.callback_type, w.LPARAM], w.BOOL),
            (self.user.GetWindowTextW, [w.HWND, w.LPWSTR, ctypes.c_int], ctypes.c_int),
            (self.user.GetWindowThreadProcessId, [w.HWND, ctypes.POINTER(w.DWORD)], w.DWORD),
            (self.kernel.OpenProcess, [w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
            (self.kernel.CloseHandle, [w.HANDLE], w.BOOL),
            (
                self.kernel.QueryFullProcessImageNameW,
                [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)],
                w.BOOL,
            ),
            (
                self.kernel.ReadProcessMemory,
                [
                    w.HANDLE,
                    ctypes.c_void_p,
                    ctypes.c_void_p,
                    ctypes.c_size_t,
                    ctypes.POINTER(ctypes.c_size_t),
                ],
                w.BOOL,
            ),
            (
                self.psapi.EnumProcessModules,
                [w.HANDLE, ctypes.POINTER(w.HMODULE), w.DWORD, ctypes.POINTER(w.DWORD)],
                w.BOOL,
            ),
            (
                self.psapi.GetModuleFileNameExW,
                [w.HANDLE, w.HMODULE, w.LPWSTR, w.DWORD],
                w.DWORD,
            ),
            (
                self.psapi.GetModuleInformation,
                [w.HANDLE, w.HMODULE, ctypes.POINTER(_ModuleInfo), w.DWORD],
                w.BOOL,
            ),
        )
        for function, arguments, result in signatures:
            function.argtypes, function.restype = arguments, result

    def _title(self, window: int) -> str:
        title = ctypes.create_unicode_buffer(512)
        self.user.GetWindowTextW(window, title, len(title))
        return title.value

    def _targets(self, title: str, artist: str) -> list[tuple[int, int]]:
        matches: list[tuple[int, int]] = []

        def visit(window: int, _: int) -> bool:
            if window_matches(self._title(window), title, artist):
                pid = w.DWORD()
                self.user.GetWindowThreadProcessId(window, ctypes.byref(pid))
                matches.append((window, pid.value))
            return True

        callback = self.callback_type(visit)
        if not self.user.EnumWindows(callback, 0):
            return []
        return matches

    def _module(self, handle: Any, executable: Path) -> int | None:
        modules = (w.HMODULE * 512)()
        needed = w.DWORD()
        if not self.psapi.EnumProcessModules(
            handle, modules, ctypes.sizeof(modules), ctypes.byref(needed)
        ) or needed.value > ctypes.sizeof(modules):
            return None
        for module in modules[: needed.value // ctypes.sizeof(w.HMODULE)]:
            name = ctypes.create_unicode_buffer(32768)
            if not self.psapi.GetModuleFileNameExW(handle, module, name, len(name)):
                continue
            path = Path(name.value)
            if path.name.casefold() != "cloudmusic.dll" or path.parent != executable.parent:
                continue
            info = _ModuleInfo()
            if (
                not self.psapi.GetModuleInformation(
                    handle, module, ctypes.byref(info), ctypes.sizeof(info)
                )
                or info.size != DLL_IMAGE_SIZE
            ):
                return None
            stat = path.stat()
            if _verified_dll(str(path), stat.st_size, stat.st_mtime_ns):
                return int(info.base)
        return None

    def read(self, title: str, artist: str, executable: Path) -> dict[str, Any]:
        targets = self._targets(title, artist)
        if not targets or len({pid for _, pid in targets}) != 1:
            return {}
        window, pid = targets[0]
        window_title = self._title(window)
        if not window_matches(window_title, title, artist):
            return {}
        # Query + VM_READ only. Never request write, debug, or injection permissions.
        handle = self.kernel.OpenProcess(0x410, False, pid)
        if not handle:
            return {}
        try:
            name = ctypes.create_unicode_buffer(32768)
            size = w.DWORD(len(name))
            if not self.kernel.QueryFullProcessImageNameW(handle, 0, name, ctypes.byref(size)):
                return {}
            if Path(name.value) != executable or executable.name.casefold() != "cloudmusic.exe":
                return {}
            base = self._module(handle, executable)
            if base is None:
                return {}
            budget = 0

            def read(address: int, length: int) -> bytes:
                nonlocal budget
                budget += length
                if (
                    not 0x10000 <= address < 0x800000000000 - length
                    or not 1 <= length <= 65
                    or budget > 512
                ):
                    raise ValueError("read outside playback fields")
                data = ctypes.create_string_buffer(length)
                count = ctypes.c_size_t()
                if (
                    not self.kernel.ReadProcessMemory(
                        handle, address, data, length, ctypes.byref(count)
                    )
                    or count.value != length
                ):
                    raise OSError("playback fields unavailable")
                return data.raw

            result = read_clock(read, base)
            return result if self._title(window) == window_title else {}
        finally:
            self.kernel.CloseHandle(handle)


def local_progress(media: dict[str, Any], executable: Path | None) -> dict[str, Any]:
    if sys.platform != "win32" or executable is None or ctypes.sizeof(ctypes.c_void_p) != 8:
        return {}
    if not media.get("title") or not media.get("artist"):
        return {}
    try:
        return _WindowsReader().read(str(media["title"]), str(media["artist"]), executable)
    except (OSError, ValueError, TypeError, struct.error):
        return {}
