"""Launch lifetime, fixed-provider boundary, and non-intrusive focus restoration."""

from __future__ import annotations

import asyncio
import os
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from companion_agent.automation import mcp_client
from companion_agent.automation.mcp_client import MCPClient, MCPFailure
from companion_agent.automation.models import MCPServerConfig
from companion_agent.integrations import netease
from companion_agent.integrations import netease_windows as windows
from companion_agent.integrations.netease_launch import _Desktop, _FocusGuard, quiet_launch


def bundled(**changes: Any) -> MCPServerConfig:
    return MCPServerConfig.model_validate(
        {
            "id": "netease",
            "label": "music",
            "enabled": True,
            "command": sys.executable,
            "args": ["-m", "companion_agent.integrations.netease"],
            **changes,
        }
    )


def definition(name: str) -> dict[str, Any]:
    tool = next(t for t in asyncio.run(netease.build_server().list_tools()) if t.name == name)
    return {"name": tool.name, "description": tool.description, "inputSchema": tool.inputSchema}


@pytest.mark.parametrize(
    "name,args", [("netease_open_app", {}), ("netease_open_song", {"song_id": "123"})]
)
def test_launch_is_owned_by_host_and_never_short_lived_mcp(
    monkeypatch: pytest.MonkeyPatch, name: str, args: dict[str, Any]
) -> None:
    calls = []

    def launch(*args: Any) -> dict[str, Any]:
        calls.append((os.getpid(), args))
        return {"status": "succeeded", "delivery": "requested", "playback_verified": False}

    async def forbidden(*args: Any) -> None:
        pytest.fail("launch must not enter the SDK's short-lived process Job")

    monkeypatch.setattr(netease, "open_song", launch)
    monkeypatch.setattr(netease, "open_app", launch)
    monkeypatch.setattr(MCPClient, "_session", forbidden)
    monkeypatch.setattr(
        mcp_client, "sys", SimpleNamespace(platform="win32", executable=sys.executable)
    )
    result = MCPClient().call(bundled(), name, args, definition(name))
    assert calls == [(os.getpid(), ("123", None) if args else (None,))]
    assert result["status"] == "succeeded"
    assert not result["data"]["playback_verified"]


def test_host_launch_revalidates_definition_and_arguments_before_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []
    monkeypatch.setattr(netease, "open_song", lambda *args: calls.append(args))
    monkeypatch.setattr(
        mcp_client, "sys", SimpleNamespace(platform="win32", executable=sys.executable)
    )
    client = MCPClient()
    tool = definition("netease_open_song")
    with pytest.raises(MCPFailure):
        client.call(bundled(), tool["name"], {"song_id": "123"}, tool | {"description": "changed"})
    with pytest.raises(MCPFailure):
        client.call(bundled(), tool["name"], {}, tool)
    with pytest.raises(MCPFailure):
        client.call(bundled(), tool["name"], {"song_id": ["123"]}, tool)
    assert calls == []


@pytest.mark.parametrize(
    "changes,name,platform",
    [
        ({"id": "custom"}, "netease_open_song", "win32"),
        ({"args": ["-m", "different_server"]}, "netease_open_song", "win32"),
        ({"command": "custom-python.exe"}, "netease_open_song", "win32"),
        ({"env": {"CUSTOM": "CUSTOM_ENV"}}, "netease_open_song", "win32"),
        (
            {"transport": "sse", "command": "", "args": [], "url": "http://127.0.0.1:8000"},
            "netease_open_song",
            "win32",
        ),
        ({}, "netease_playback_state", "win32"),
        ({}, "netease_search_songs", "win32"),
        ({}, "netease_open_song", "linux"),
    ],
)
def test_host_route_is_limited_to_exact_bundled_windows_launch_tools(
    monkeypatch: pytest.MonkeyPatch, changes: dict[str, Any], name: str, platform: str
) -> None:
    calls = []

    async def remote(*args: Any) -> dict[str, Any]:
        calls.append(args)
        return {"status": "remote"}

    monkeypatch.setattr(MCPClient, "_session", remote)
    monkeypatch.setattr(
        mcp_client, "sys", SimpleNamespace(platform=platform, executable=sys.executable)
    )
    assert MCPClient().call(bundled(**changes), name, {}, {}) == {"status": "remote"}
    assert len(calls) == 1


class Desktop(_Desktop):
    def __init__(self) -> None:
        self.current = 10
        self.input = 100
        self.exists = True
        self.calls: list[tuple[int, int]] = []
        self.hidden: list[int] = []
        self.released: list[tuple[int, int]] = []
        self.buttons = 0
        self.switching = False
        self.pointer = 10

    def foreground(self) -> int:
        return self.current

    def pid(self, window: int) -> int:
        return window + 1000

    def valid(self, window: int, pid: int) -> bool:
        return self.exists and pid == self.pid(window)

    def input_tick(self) -> int:
        return self.input

    def mouse_buttons(self) -> int:
        return self.buttons

    def switching_keys(self) -> bool:
        return self.switching

    def pointer_window(self) -> int:
        return self.pointer

    def is_player(self, window: int, executable: Path) -> bool:
        return window == 20 and executable.name == "cloudmusic.exe"

    def background(self, player: int, original: int, *, ticket: int = 0) -> bool:
        self.calls.append((player, original))
        self.current = original
        return True

    def visible_players(self, executable: Path) -> set[int]:
        return {20} if self.current == 20 else set()

    def protect_xinyu(self, window: int) -> int:
        return 1

    def release_xinyu(self, window: int, ticket: int) -> None:
        self.released.append((window, ticket))

    def hide(self, player: int) -> None:
        self.hidden.append(player)


def test_automatic_player_activation_restores_original_window() -> None:
    desktop = Desktop()
    guard = _FocusGuard(desktop, Path("cloudmusic.exe"))
    desktop.input += 1  # Typing in XinYu does not disable the launch protection.
    assert guard.tick()
    desktop.current = 20
    assert guard.tick()
    assert desktop.calls == [(20, 10)] and desktop.current == 10
    assert desktop.hidden == [20]


@pytest.mark.parametrize(
    "current,input_changed,exists",
    [(20, True, True), (30, True, True), (20, False, False)],
)
def test_user_switch_other_app_or_closed_window_is_never_pulled_back(
    current: int, input_changed: bool, exists: bool
) -> None:
    desktop = Desktop()
    guard = _FocusGuard(desktop, Path("cloudmusic.exe"))
    desktop.current, desktop.exists = current, exists
    desktop.input += int(input_changed)
    if input_changed:
        desktop.buttons, desktop.pointer = 1, current
    assert not guard.tick()
    assert desktop.calls == []


def test_transient_system_window_does_not_cancel_silent_startup() -> None:
    desktop = Desktop()
    guard = _FocusGuard(desktop, Path("cloudmusic.exe"))
    desktop.current = 30
    assert guard.tick() and desktop.calls == []
    desktop.current = 20
    assert guard.tick() and desktop.hidden == [20]


def test_song_activation_of_an_existing_window_is_suppressed_too() -> None:
    class VisiblePlayer(Desktop):
        def visible_players(self, executable: Path) -> set[int]:
            return {20}

    desktop = VisiblePlayer()
    guard = _FocusGuard(desktop, Path("cloudmusic.exe"))
    assert guard.tick() and desktop.hidden == [20]  # Hide even without a focus change.
    desktop.current = 20
    assert guard.tick() and desktop.calls == [(20, 10)]
    assert desktop.hidden == [20, 20]


@pytest.mark.parametrize("held_button", [0, 1])
def test_pointer_motion_during_song_activation_is_not_a_user_app_switch(held_button: int) -> None:
    desktop = Desktop()
    desktop.buttons = held_button  # The point-song click can still be held down.
    guard = _FocusGuard(desktop, Path("cloudmusic.exe"))
    desktop.input += 1
    desktop.current = desktop.pointer = 20
    assert guard.tick()
    assert desktop.calls == [(20, 10)] and desktop.hidden == [20]


def test_a_fresh_click_outside_xinyu_yields_before_the_other_app_activates() -> None:
    desktop = Desktop()
    guard = _FocusGuard(desktop, Path("cloudmusic.exe"))
    desktop.buttons, desktop.pointer = 1, 20
    assert not guard.tick() and desktop.hidden == [] and desktop.calls == []


def test_alt_or_windows_key_yields_to_user_app_switching() -> None:
    desktop = Desktop()
    guard = _FocusGuard(desktop, Path("cloudmusic.exe"))
    desktop.switching = True
    assert not guard.tick() and desktop.hidden == [] and desktop.calls == []


def test_existing_player_foreground_is_not_minimized() -> None:
    desktop = Desktop()
    desktop.current = 20
    assert not _FocusGuard(desktop, Path("cloudmusic.exe")).tick()
    assert desktop.calls == []


@pytest.mark.parametrize("reason", ["cancelled", "user_switch", "window_closed", "os_error"])
def test_native_protection_is_released_on_every_guard_exit(reason: str) -> None:
    desktop = Desktop()
    guard = _FocusGuard(desktop, Path("cloudmusic.exe"))
    guard.ticket = 7
    stop = threading.Event()
    if reason == "cancelled":
        stop.set()
    elif reason == "user_switch":
        desktop.switching = True
    elif reason == "window_closed":
        desktop.exists = False
    else:

        def unavailable() -> int:
            raise OSError("synthetic desktop unavailable")

        desktop.foreground = unavailable  # type: ignore[method-assign]
    guard.run(stop)
    assert desktop.released == [(10, 7)]


@pytest.mark.skipif(os.name != "nt", reason="Windows GUI startup flags")
def test_gui_launch_requests_hidden_without_minimizing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("companion_agent.integrations.netease_launch._Desktop", Desktop)
    with pytest.raises(OSError), quiet_launch(Path("cloudmusic.exe")) as startup:
        assert startup.dwFlags & 1 and startup.dwFlags & 0x80
        assert startup.wShowWindow == 0
        raise OSError("synthetic failed launch; no guard should be started")


def test_open_existing_player_does_not_spawn_or_activate_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    executable = tmp_path / "cloudmusic.exe"
    executable.touch()
    checked = []

    def existing(target: Path) -> bool:
        checked.append(target)
        return True

    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("an already running player must not be relaunched or activated")

    monkeypatch.setattr(windows, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(windows, "player_is_open", existing)
    monkeypatch.setattr(windows.subprocess, "Popen", forbidden)
    monkeypatch.setattr(windows, "quiet_launch", forbidden)
    result = windows.open_app(executable)
    assert checked == [executable.resolve()]
    assert result["status"] == "succeeded" and result["delivery"] == "already_running"
    assert not result["playback_verified"] and "song_id" not in result


@pytest.mark.skipif(os.name != "nt", reason="Windows player window detection")
def test_existing_player_detection_includes_hidden_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from companion_agent.integrations import netease_launch

    class HiddenPlayer:
        def visible_players(self, executable: Path, *, include_hidden: bool = False) -> set[int]:
            assert executable == Path("cloudmusic.exe")
            return {20} if include_hidden else set()

    monkeypatch.setattr(netease_launch, "_Desktop", HiddenPlayer)
    assert netease_launch.player_is_open(Path("cloudmusic.exe"))


@pytest.mark.skipif(os.name != "nt", reason="Windows launch ordering")
@pytest.mark.parametrize("fails", [False, True])
def test_guard_is_armed_before_handoff_and_cancelled_on_launch_failure(
    monkeypatch: pytest.MonkeyPatch, fails: bool
) -> None:
    from companion_agent.integrations import netease_launch

    calls = []
    stops = []

    class Thread:
        def __init__(self, *, target: Any, args: tuple[Any, ...], **kwargs: Any) -> None:
            stops.append(args[0])

        def start(self) -> None:
            calls.append("guard")

    monkeypatch.setattr(netease_launch, "_Desktop", Desktop)
    monkeypatch.setattr(netease_launch.threading, "Thread", Thread)
    try:
        with quiet_launch(Path("cloudmusic.exe")):
            calls.append("handoff")
            if fails:
                raise OSError("synthetic launch failure")
    except OSError:
        assert fails
    assert calls == ["guard", "handoff"]
    assert stops[0].is_set() is fails


@pytest.mark.skipif(os.name != "nt", reason="Windows launch ordering")
def test_worker_start_failure_releases_native_protection(monkeypatch: pytest.MonkeyPatch) -> None:
    from companion_agent.integrations import netease_launch

    desktop = Desktop()

    class Thread:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def start(self) -> None:
            raise RuntimeError("synthetic thread start failure")

    monkeypatch.setattr(netease_launch, "_Desktop", lambda: desktop)
    monkeypatch.setattr(netease_launch.threading, "Thread", Thread)
    with (
        pytest.raises(RuntimeError, match="thread start failure"),
        quiet_launch(Path("cloudmusic.exe")),
    ):
        pytest.fail("handoff must not run without the guard")
    assert desktop.released == [(10, 1)]
