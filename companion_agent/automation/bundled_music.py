"""Keep the packaged music template attached to the current portable installation."""

from __future__ import annotations

from contextlib import suppress
from pathlib import PureWindowsPath
from typing import TYPE_CHECKING

from companion_agent.automation.models import AutomationConfig, MCPServerConfig, ToolRule

if TYPE_CHECKING:
    from companion_agent.automation.hub import ToolHub


MUSIC_TOOLS = frozenset(
    {
        "netease_status",
        "netease_open_app",
        "netease_search_songs",
        "netease_open_song",
        "netease_playback_state",
        "netease_control",
        "netease_seek",
        "netease_user_playlists",
        "netease_playlist_songs",
        "netease_account",
    }
)


def is_bundled_music(server: MCPServerConfig, executable: str) -> bool:
    return (
        server.id == "netease"
        and not any([server.env, server.url, server.bearer_env])
        and (
            server.transport == "native"
            or (
                server.transport == "stdio"
                and server.command == executable
                and server.args
                in (["--mcp-server", "netease"], ["-m", "companion_agent.integrations.netease"])
            )
        )
    )


def music_rules() -> dict[str, ToolRule]:
    """Connecting the fixed music app enables ordinary requested music operations."""
    return {name: ToolRule(mode="allow") for name in sorted(MUSIC_TOOLS)}


def migrate_music_permissions(config: AutomationConfig, executable: str) -> None:
    """One upgrade of legacy blanket asks; explicit denials and argument scopes survive."""
    for server in config.servers:
        if not is_bundled_music(server, executable):
            continue
        for name in MUSIC_TOOLS:
            rule = server.tools.get(name)
            if rule is None or (rule.mode == "ask" and not rule.arguments):
                server.tools[name] = ToolRule(mode="allow")


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
        has_open = any(t["name"] == "netease_open_app" for t in hub.catalog.get("netease", []))
        has_background = any(
            t["name"] == "netease_open_song"
            and "本机后台通道" in t.get("description", "")
            and "playback_access" in t.get("description", "")
            for t in hub.catalog.get("netease", [])
        )
        if (
            (search and "search_type" not in search["inputSchema"].get("properties", {}))
            or not has_open
            or (server.transport != "native" and not has_background)
            or not {"netease_user_playlists", "netease_playlist_songs", "netease_account"}.issubset(
                {t["name"] for t in hub.catalog.get("netease", [])}
            )
        ):
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
