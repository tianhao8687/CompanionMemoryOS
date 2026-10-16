"""Bounded CDP transport to one verified, loopback-only NetEase process.

No launcher, window/input API, protocol handler, or model-facing eval tool lives
here. Failing to establish this channel must never start a different transport.
"""

from __future__ import annotations

import ctypes
import json
import re
import socket
import struct
import sys
import time
from contextlib import suppress
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from companion_agent.integrations.netease_cdp_profiles import RUNTIME_PROFILES

PORT = 9223
ORIGIN = f"http://127.0.0.1:{PORT}"
MAX_BYTES = 1_000_000


class BackgroundUnavailable(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def client_version(value: Any) -> str:
    agent = value.get("User-Agent") if isinstance(value, dict) else None
    match = (
        re.search(r"(?:^|\s)NeteaseMusicDesktop/(\d+\.\d+\.\d+\.\d+)$", agent)
        if isinstance(agent, str)
        else None
    )
    if match is None or match[1] not in RUNTIME_PROFILES:
        raise BackgroundUnavailable("unsupported_client_version")
    return match[1]


def _listener_rows(family: int) -> list[tuple[str, int, int]]:
    """Read OS TCP ownership, including wildcard/IPv6 listeners on our port."""
    if sys.platform != "win32":
        raise BackgroundUnavailable("unsupported_platform")
    u32 = ctypes.c_uint32

    class Row4(ctypes.Structure):
        _fields_ = [
            (name, u32) for name in ("state", "address", "port", "remote", "remote_port", "pid")
        ]

    class Row6(ctypes.Structure):
        _fields_ = [
            ("address", ctypes.c_ubyte * 16),
            ("scope", u32),
            ("port", u32),
            ("remote", ctypes.c_ubyte * 16),
            ("remote_scope", u32),
            ("remote_port", u32),
            ("state", u32),
            ("pid", u32),
        ]

    get_table = ctypes.WinDLL("iphlpapi", use_last_error=True).GetExtendedTcpTable
    get_table.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(u32),
        ctypes.c_int,
        u32,
        ctypes.c_int,
        u32,
    ]
    get_table.restype = u32
    size = u32()
    code = get_table(None, ctypes.byref(size), False, family, 3, 0)
    if code == 232:
        return []
    if code not in (0, 122) or not 4 <= size.value <= MAX_BYTES:
        raise BackgroundUnavailable("ownership_unavailable")
    for _ in range(3):
        data = ctypes.create_string_buffer(size.value)
        code = get_table(data, ctypes.byref(size), False, family, 3, 0)
        if code == 122 and size.value <= MAX_BYTES:
            continue
        if code != 0:
            raise BackgroundUnavailable("ownership_unavailable")
        row_type = Row4 if family == 2 else Row6
        count = u32.from_buffer(data).value
        if 4 + count * ctypes.sizeof(row_type) > len(data):
            raise BackgroundUnavailable("ownership_unavailable")
        rows = []
        for index in range(count):
            row = row_type.from_buffer_copy(data, 4 + index * ctypes.sizeof(row_type))
            port = socket.ntohs(row.port & 0xFFFF)
            if port != PORT:
                continue
            address = (
                socket.inet_ntoa(struct.pack("<I", row.address))
                if family == 2
                else socket.inet_ntop(socket.AF_INET6, bytes(row.address))
            )
            rows.append((address, port, row.pid))
        return rows
    raise BackgroundUnavailable("ownership_unavailable")


def _process_path(pid: int) -> Path:
    if sys.platform != "win32":
        raise BackgroundUnavailable("unsupported_platform")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel.QueryFullProcessImageNameW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_wchar_p,
        ctypes.POINTER(ctypes.c_uint32),
    ]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        raise BackgroundUnavailable("ownership_unavailable")
    try:
        length = ctypes.c_uint32(32768)
        text = ctypes.create_unicode_buffer(length.value)
        if not kernel.QueryFullProcessImageNameW(handle, 0, text, ctypes.byref(length)):
            raise BackgroundUnavailable("ownership_unavailable")
        return Path(text.value).resolve()
    finally:
        kernel.CloseHandle(handle)


def channel_owner(executable: Path) -> int:
    if sys.platform != "win32":
        raise BackgroundUnavailable("unsupported_platform")
    rows = _listener_rows(2) + _listener_rows(23)
    if not rows:
        raise BackgroundUnavailable("background_not_initialized")
    if any(address not in {"127.0.0.1", "::1"} for address, _, _ in rows):
        raise BackgroundUnavailable("nonlocal_listener")
    owners = {pid for _, _, pid in rows}
    if len(owners) != 1 or not any(address == "127.0.0.1" for address, _, _ in rows):
        raise BackgroundUnavailable("wrong_channel_owner")
    owner = owners.pop()
    if _process_path(owner) != executable.resolve():
        raise BackgroundUnavailable("wrong_channel_owner")
    return owner


def validate_target(targets: Any) -> str:
    if not isinstance(targets, list):
        raise BackgroundUnavailable("unsupported_target")
    selected = [
        target
        for target in targets
        if isinstance(target, dict)
        and target.get("type") == "page"
        and target.get("url") == "orpheus://orpheus/pub/app.html"
    ]
    if len(selected) != 1:
        raise BackgroundUnavailable("unsupported_target")
    value = selected[0].get("webSocketDebuggerUrl")
    if not isinstance(value, str):
        raise BackgroundUnavailable("unsupported_target")
    try:
        url = urlsplit(value)
        safe = (
            url.scheme == "ws"
            and url.hostname == "127.0.0.1"
            and url.port == PORT
            and not url.username
            and not url.password
            and not url.query
            and not url.fragment
            and re.fullmatch(r"/devtools/page/[A-Fa-f0-9]+", url.path)
        )
    except ValueError:
        safe = False
    if not safe:
        raise BackgroundUnavailable("nonlocal_target")
    return value


class LocalChannel:
    """Only the private music adapter calls evaluate with reviewed constants."""

    def __init__(self, executable: Path) -> None:
        # Leave room for the MCP caller's 20-second deadline and connection close.
        self.deadline = time.monotonic() + 16
        self.executable = executable
        self.pid = channel_owner(executable)
        self.sequence = 0
        self.socket: Any = None
        try:
            with httpx.Client(timeout=2, follow_redirects=False, trust_env=False) as client:
                self.version = client_version(self._json(client, "/json/version"))
                target = validate_target(self._json(client, "/json/list"))
            if sys.platform == "win32":
                import websocket

                self.socket = websocket.create_connection(
                    target, timeout=3, suppress_origin=True, http_no_proxy=["127.0.0.1"]
                )
            else:
                raise BackgroundUnavailable("unsupported_platform")
            self.check_owner()
        except BackgroundUnavailable:
            self.close()
            raise
        except ImportError:
            raise BackgroundUnavailable("missing_background_component") from None
        except Exception:
            self.close()
            raise BackgroundUnavailable("background_unavailable") from None

    def remaining(self) -> float:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise BackgroundUnavailable("background_timeout")
        return remaining

    def _json(self, client: httpx.Client, path: str) -> Any:
        with client.stream("GET", ORIGIN + path) as response:
            if response.status_code != 200:
                raise BackgroundUnavailable("background_unavailable")
            data = bytearray()
            for part in response.iter_bytes():
                self.remaining()
                data.extend(part)
                if len(data) > 65536:
                    raise BackgroundUnavailable("invalid_background_response")
            return json.loads(data)

    def check_owner(self) -> None:
        if channel_owner(self.executable) != self.pid:
            raise BackgroundUnavailable("channel_changed")

    def evaluate(self, expression: str, *, await_promise: bool = False) -> Any:
        self.check_owner()
        self.socket.settimeout(min(5, self.remaining()))
        self.sequence += 1
        self.socket.send(
            json.dumps(
                {
                    "id": self.sequence,
                    "method": "Runtime.evaluate",
                    "params": {
                        "expression": expression,
                        "returnByValue": True,
                        "awaitPromise": await_promise,
                    },
                }
            )
        )
        deadline = min(self.deadline, time.monotonic() + 5)
        for _ in range(64):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            self.socket.settimeout(remaining)
            raw = self.socket.recv()
            if len(raw) > MAX_BYTES:
                raise BackgroundUnavailable("invalid_background_response")
            message = json.loads(raw)
            if not isinstance(message, dict) or message.get("id") != self.sequence:
                continue
            result = message.get("result", {})
            if (
                message.get("error")
                or not isinstance(result, dict)
                or result.get("exceptionDetails")
            ):
                raise BackgroundUnavailable("unsupported_client_runtime")
            self.check_owner()
            return result.get("result", {}).get("value")
        raise BackgroundUnavailable("background_timeout")

    def close(self) -> None:
        if self.socket is not None:
            with suppress(Exception):
                self.socket.close(timeout=0.2)
            self.socket = None

    def __enter__(self) -> LocalChannel:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
