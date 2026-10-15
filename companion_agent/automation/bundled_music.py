"""Keep the packaged music template attached to the current portable installation."""

from __future__ import annotations

from contextlib import suppress
from pathlib import PureWindowsPath
from typing import TYPE_CHECKING

from companion_agent.automation.models import AutomationConfig

if TYPE_CHECKING:
    from companion_agent.automation.hub import ToolHub


def refresh_lyrics_catalog(hub: ToolHub, executable: str) -> None:
    """Refresh only a previously connected bundled catalogue; keep every permission."""
    for server in hub.config.servers:
        bundled = server.transport == "native" or (
            server.transport == "stdio"
            and server.command == executable
            and not server.env
            and server.args
            in (["--mcp-server", "netease"], ["-m", "companion_agent.integrations.netease"])
        )
        if server.id != "netease" or not server.enabled or not bundled:
            continue
        search = next(
            (t for t in hub.catalog.get("netease", []) if t["name"] == "netease_search_songs"), None
        )
        if search and "search_type" not in search["inputSchema"].get("properties", {}):
            # A disconnected client can be reconnected from the existing settings page.
            with suppress(Exception):
                hub.discover("netease")


def relocate_packaged_music(config: AutomationConfig, executable: str) -> bool:
    current = PureWindowsPath(executable)
    if not current.is_absolute() or current.name.casefold() != "xinyu-engine.exe":
        return False
    changed = False
    for server in config.servers:
        previous = PureWindowsPath(server.command)
        if (
            server.id == "netease"
            and server.transport == "stdio"
            and previous.is_absolute()
            and previous.name.casefold() == "xinyu-engine.exe"
            and server.args == ["--mcp-server", "netease"]
            and not server.env
            and previous != current
        ):
            server.command = executable
            changed = True
    return changed
