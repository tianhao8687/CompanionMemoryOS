"""Bundled Android MCP peer over an in-process JSON-RPC transport.

The embedded runtime has no subprocess/remote MCP capability. This peer uses
the same discovery, schema fingerprints, approval ledger and tool results.
It intentionally needs neither the desktop MCP SDK nor its native dependencies.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

from jsonschema import Draft202012Validator

from companion_agent.automation.mcp_client import MCPClient, MCPFailure
from companion_agent.automation.models import MCPServerConfig
from companion_agent.integrations.netease_catalog import NetEaseCatalog

VERSION = "2025-06-18"
Bridge = Callable[[str, dict[str, Any]], dict[str, Any]]


def tool(name: str, description: str, properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": properties,
            "required": [key for key in properties if key not in {"limit", "search_type"}],
            "additionalProperties": False,
        },
    }


CATALOG = [
    tool("netease_status", "检查本机网易云安装、媒体会话与授权，不读取通知内容。", {}),
    tool(
        "netease_search_songs",
        "搜索网易云歌曲。歌词找歌用 search_type=lyrics，query 只填用户提供的一句歌词，"
        "不加点歌指令或猜测歌名。lyric_match 是匹配证据，未匹配不能当作确定歌曲。"
        "歌名/歌手用 song。版本有歧义时给2到3个候选，不登录或播放。",
        {
            "query": {"type": "string", "minLength": 1, "maxLength": 120},
            "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
            "search_type": {"type": "string", "enum": ["song", "lyrics"], "default": "song"},
        },
    ),
    tool(
        "netease_open_song",
        "将搜索结果或用户提供的歌曲 ID 交给安卓网易云打开；不猜 ID，不宣称已播放。",
        {"song_id": {"type": "string", "pattern": "^[0-9]{1,18}$"}},
    ),
    tool("netease_playback_state", "读取网易云歌曲、歌手与播放状态，不读取其他播放器。", {}),
    tool(
        "netease_control",
        "仅控制本机网易云的播放、暂停、前后切歌。uncertain 时先核对客户端，不自动重试。",
        {"action": {"type": "string", "enum": ["play", "pause", "next", "previous"]}},
    ),
    tool(
        "netease_seek",
        "跳转当前歌曲的毫秒位置；需读取当前歌名、歌手、专辑及 seek 能力。未确认时不重试。",
        {
            "position_ms": {"type": "integer", "minimum": 0, "maximum": 86400000},
            **{key: {"type": "string", "maxLength": 200} for key in ("title", "artist", "album")},
        },
    ),
]


class AndroidMusicPeer:
    def __init__(self, bridge: Bridge, catalog: NetEaseCatalog | None = None) -> None:
        self.bridge = bridge
        self.catalog = catalog or NetEaseCatalog()
        self.initialized = False
        self.ready = False

    def exchange(self, message: dict[str, Any]) -> dict[str, Any] | None:
        identifier = message.get("id")
        method = message.get("method")
        params = message.get("params", {})
        result: dict[str, Any]
        try:
            if message.get("jsonrpc") != "2.0" or not isinstance(params, dict):
                raise ValueError("invalid request")
            if method == "initialize":
                if self.initialized or params.get("protocolVersion") != VERSION:
                    raise ValueError("unsupported protocol")
                self.initialized = True
                result = {
                    "protocolVersion": VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "xinyu-netease-android", "version": "1.0"},
                }
            elif method == "notifications/initialized" and self.initialized:
                self.ready = True
                return None
            elif not self.ready:
                raise ValueError("initialize first")
            elif method == "tools/list":
                result = {"tools": CATALOG}
            elif method == "tools/call":
                name = params.get("name")
                definition = next((t for t in CATALOG if t["name"] == name), None)
                if definition is None:
                    raise ValueError("unknown tool")
                arguments = params.get("arguments", {})
                Draft202012Validator(definition["inputSchema"]).validate(arguments)
                if name == "netease_search_songs":
                    data = asyncio.run(self.catalog.search(**arguments))
                else:
                    data = self.bridge(str(name), arguments)
                result = {
                    "content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}],
                    "structuredContent": data,
                    "isError": data.get("status") == "failed",
                }
            else:
                return {
                    "jsonrpc": "2.0",
                    "id": identifier,
                    "error": {"code": -32601, "message": "Method not found"},
                }
            return {"jsonrpc": "2.0", "id": identifier, "result": result}
        except Exception:
            # No platform exception bodies, notification payloads or credentials.
            return {
                "jsonrpc": "2.0",
                "id": identifier,
                "error": {"code": -32602, "message": "Music request failed"},
            }


class AndroidMusicClient(MCPClient):
    def __init__(self, bridge: Bridge, catalog: NetEaseCatalog | None = None) -> None:
        self.bridge = bridge
        self.catalog = catalog

    @staticmethod
    def accepts(server: MCPServerConfig) -> bool:
        return server.transport == "native" and server.id == "netease"

    def _run(
        self,
        server: MCPServerConfig,
        name: str | None = None,
        arguments: dict[str, Any] | None = None,
        expected: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        if not self.accepts(server):
            raise MCPFailure("安卓仅支持内置网易云连接。")
        # Search uses at most 10 s plus an optional 2 s artwork lookup.
        budget = min(server.timeout_seconds, timeout or server.timeout_seconds)
        if budget < (12 if name == "netease_search_songs" else 4):
            raise MCPFailure("剩余执行时间不足，请重新发起请求。")
        peer = AndroidMusicPeer(self.bridge, self.catalog)

        def request(identifier: int, method: str, params: dict[str, Any]) -> dict[str, Any]:
            response = peer.exchange(
                {"jsonrpc": "2.0", "id": identifier, "method": method, "params": params}
            )
            if response is None or response.get("id") != identifier or "error" in response:
                raise MCPFailure("网易云连接或执行失败，请检查系统授权与播放器。")
            # A JSON transport owns its messages; callers must not mutate the
            # bundled catalogue by changing a discovered schema in place.
            return dict(json.loads(json.dumps(response["result"])))

        initialized = request(
            1,
            "initialize",
            {
                "protocolVersion": VERSION,
                "capabilities": {},
                "clientInfo": {"name": "xinyu", "version": "1.0"},
            },
        )
        if initialized["protocolVersion"] != VERSION:
            raise MCPFailure("不支持此音乐连接版本。")
        peer.exchange({"jsonrpc": "2.0", "method": "notifications/initialized"})
        catalog = request(2, "tools/list", {})["tools"]
        if name is None:
            return catalog
        if next((t for t in catalog if t["name"] == name), None) != expected:
            raise MCPFailure("音乐工具已变化，请重新连接。")
        result = request(3, "tools/call", {"name": name, "arguments": arguments or {}})
        data = result["structuredContent"]
        return {
            "status": data.get("status", "failed"),
            "text": result["content"][0]["text"][:12000],
            "data": data,
        }


def android_client(context: Any) -> AndroidMusicClient:
    from importlib import import_module

    native = import_module("java").jclass("com.xinyu.xinyu_flutter.MusicBridge")

    def invoke(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        raw = str(native.call(context, name, json.dumps(arguments, ensure_ascii=False)))
        if len(raw) > 12000:
            raise MCPFailure("媒体状态过长。")
        return dict(json.loads(raw))

    return AndroidMusicClient(invoke)
