"""Quiet Windows player launch, with a bounded guard against client activation."""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from ctypes import wintypes
from pathlib import Path
from typing import Any

_guard_lock = threading.Lock()
_active_guard: threading.Event | None = None


class _Desktop:
    """Only foreground metadata and exact-executable window operations; no input hooks."""

    user: Any
    kernel: Any

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise OSError("Windows desktop APIs are unavailable on this platform")
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.user.GetForegroundWindow.restype = wintypes.HWND
        self.user.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self.user.GetWindowThreadProcessId.restype = wintypes.DWORD
        self.user.IsWindow.argtypes = [wintypes.HWND]
        self.user.IsWindow.restype = wintypes.BOOL
        self.user.ShowWindowAsync.argtypes = [wintypes.HWND, ctypes.c_int]
        self.user.ShowWindowAsync.restype = wintypes.BOOL
        self.user.SetForegroundWindow.argtypes = [wintypes.HWND]
        self.user.SetForegroundWindow.restype = wintypes.BOOL
        self.user.GetAsyncKeyState.argtypes = [ctypes.c_int]
        self.user.GetAsyncKeyState.restype = ctypes.c_short
        self.user.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
        self.user.GetCursorPos.restype = wintypes.BOOL
        self.user.WindowFromPoint.argtypes = [wintypes.POINT]
        self.user.WindowFromPoint.restype = wintypes.HWND
        self.user.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        self.user.GetAncestor.restype = wintypes.HWND
        self.user.SetWindowPos.argtypes = [
            wintypes.HWND,
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ]
        self.user.IsWindowVisible.argtypes = [wintypes.HWND]
        self.user.IsWindowVisible.restype = wintypes.BOOL
        self.kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self.kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL

    def foreground(self) -> int:
        return int(self.user.GetForegroundWindow() or 0)

    def pid(self, window: int) -> int:
        pid = wintypes.DWORD()
        self.user.GetWindowThreadProcessId(window, ctypes.byref(pid))
        return int(pid.value)

    def valid(self, window: int, pid: int) -> bool:
        return bool(self.user.IsWindow(window)) and self.pid(window) == pid

    def input_tick(self) -> int:
        class LastInput(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

        value = LastInput()
        value.cbSize = ctypes.sizeof(value)
        if not self.user.GetLastInputInfo(ctypes.byref(value)):
            raise OSError("last-input metadata unavailable")
        return int(value.dwTime)

    def mouse_buttons(self) -> int:
        # Only physical button state, never typed text or an input hook.
        return sum(
            1 << index
            for index, key in enumerate((1, 2, 4, 5, 6))
            if self.user.GetAsyncKeyState(key) & 0x8000
        )

    def switching_keys(self) -> bool:
        return any(self.user.GetAsyncKeyState(key) & 0x8000 for key in (0x12, 0x5B, 0x5C))

    def pointer_window(self) -> int:
        point = wintypes.POINT()
        if not self.user.GetCursorPos(ctypes.byref(point)):
            return 0
        child = self.user.WindowFromPoint(point)
        return int(self.user.GetAncestor(child, 2) or child or 0)  # GA_ROOT

    def is_player(self, window: int, executable: Path) -> bool:
        handle = self.kernel.OpenProcess(0x1000, False, self.pid(window))
        if not handle:
            return False
        try:
            size = wintypes.DWORD(32768)
            name = ctypes.create_unicode_buffer(size.value)
            return bool(
                self.kernel.QueryFullProcessImageNameW(handle, 0, name, ctypes.byref(size))
            ) and (os.path.normcase(name.value) == os.path.normcase(str(executable)))
        finally:
            self.kernel.CloseHandle(handle)

    def visible_players(self, executable: Path, *, include_hidden: bool = False) -> set[int]:
        if sys.platform != "win32":
            raise OSError("Windows desktop APIs are unavailable on this platform")
        windows: set[int] = set()
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def visit(window: int, _: int) -> bool:
            if (include_hidden or self.user.IsWindowVisible(window)) and self.is_player(
                window, executable
            ):
                windows.add(window)
            return True

        self.user.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
        self.user.EnumWindows(callback_type(visit), 0)
        return windows

    def _xinyu_message(self, window: int, message: int, ticket: int = 0, other: int = 0) -> int:
        # Only XinYu's own runner handles this bounded request. The foreground
        # process must acquire its own lock; a background engine cannot do it.
        frontend = Path(sys.executable).parent.parent / "xinyu_flutter.exe"
        if not self.is_player(window, frontend):
            return 0
        self.user.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        name = ctypes.create_unicode_buffer(128)
        self.user.GetClassNameW(window, name, len(name))
        if name.value != "FLUTTER_RUNNER_WIN32_WINDOW":
            return 0
        self.user.SendMessageTimeoutW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
            wintypes.UINT,
            wintypes.UINT,
            ctypes.POINTER(ctypes.c_size_t),
        ]
        result = ctypes.c_size_t()
        sent = self.user.SendMessageTimeoutW(
            window, message, ticket, other, 2, 500, ctypes.byref(result)
        )
        return int(result.value) if sent else 0

    def protect_xinyu(self, window: int) -> int:
        return self._xinyu_message(window, 0x8059)

    def release_xinyu(self, window: int, ticket: int) -> None:
        if ticket:
            self._xinyu_message(window, 0x805B, ticket)

    def hide(self, player: int) -> None:
        self.user.ShowWindowAsync(player, 0)  # SW_HIDE, never a minimized/mini window.

    def background(self, player: int, original: int, *, ticket: int = 0) -> bool:
        # The frontend owns the last user input; the background engine may lack
        # foreground permission. Ask the verified frontend to restore itself first.
        self.user.SetWindowPos(player, 1, 0, 0, 0, 0, 0x13)  # BOTTOM, NOMOVE|NOSIZE|NOACTIVATE
        if not self._xinyu_message(original, 0x805A, ticket, player):
            self.user.SetForegroundWindow(original)
        return self.foreground() == original


def player_is_open(executable: Path) -> bool:
    """An existing official-client window, including its hidden tray window, is enough."""
    if os.name == "nt":
        with suppress(OSError):
            return bool(_Desktop().visible_players(executable, include_hidden=True))
    return False


class _FocusGuard:
    def __init__(self, desktop: _Desktop, executable: Path) -> None:
        self.desktop = desktop
        self.executable = executable
        self.original = desktop.foreground()
        self.owner = desktop.pid(self.original)
        self.last_input = desktop.input_tick()
        self.buttons = desktop.mouse_buttons()
        self.ticket = 0
        self.enabled = bool(self.original and self.owner) and not desktop.is_player(
            self.original, executable
        )

    def tick(self) -> bool:
        if not self.enabled or not self.desktop.valid(self.original, self.owner):
            return False
        current = self.desktop.foreground()
        latest_input = self.desktop.input_tick()
        buttons = self.desktop.mouse_buttons()
        pressed = buttons & ~self.buttons
        self.buttons = buttons
        if self.desktop.switching_keys() or (
            pressed and self.desktop.pointer_window() != self.original
        ):
            return False
        if current == self.original:
            self.last_input = latest_input
        player_active = bool(current and self.desktop.is_player(current, self.executable))
        # GetLastInputInfo also changes on ordinary mouse movement. It cannot
        # distinguish the player's automatic activation from a deliberate click.
        if (
            current
            and current != self.original
            and not player_active
            and latest_input != self.last_input
        ):
            return False
        # A warm song request can raise an existing window without changing focus.
        # Keep every official-player window hidden during this bounded handoff.
        for window in self.desktop.visible_players(self.executable):
            self.desktop.hide(window)
        if player_active:
            self.desktop.background(current, self.original, ticket=self.ticket)
        return True

    def run(self, stop: threading.Event) -> None:
        deadline = time.monotonic() + 12
        try:
            with suppress(OSError):
                while not stop.is_set() and time.monotonic() < deadline and self.tick():
                    stop.wait(0.02)
        finally:
            with suppress(OSError):
                self.desktop.release_xinyu(self.original, self.ticket)


@contextmanager
def quiet_launch(executable: Path) -> Iterator[Any]:
    """Arm before Popen so a fast handoff cannot activate before protection starts."""
    global _active_guard
    startup = None
    guard = None
    if sys.platform == "win32":
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW | 0x80  # FORCEOFFFEEDBACK
        startup.wShowWindow = 0  # SW_HIDE; silent launch must not create a mini window.
        with suppress(OSError):
            guard = _FocusGuard(_Desktop(), executable)
    stop = None
    if guard is not None and guard.enabled:
        with _guard_lock:
            if _active_guard is not None:
                _active_guard.set()
            _active_guard = threading.Event()
            stop = _active_guard
            # Keep native tickets and the active worker in the same order when
            # two requests arrive together. An old worker cannot unpin the new one.
            guard.ticket = guard.desktop.protect_xinyu(guard.original)
            try:
                threading.Thread(
                    target=guard.run, args=(stop,), name="netease-quiet-launch", daemon=True
                ).start()
            except BaseException:
                stop.set()
                guard.desktop.release_xinyu(guard.original, guard.ticket)
                raise
    try:
        yield startup
    except BaseException:
        if stop is not None:
            stop.set()
        raise
