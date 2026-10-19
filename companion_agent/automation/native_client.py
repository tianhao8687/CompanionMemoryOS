"""Route multiple bundled native providers without enabling arbitrary processes."""

from __future__ import annotations

from typing import Any

from companion_agent.automation.mcp_client import MCPClient, MCPFailure
from companion_agent.automation.models import MCPServerConfig


class NativeClients(MCPClient):
    def __init__(self, providers: dict[str, MCPClient]) -> None:
        self.providers = providers

    def accepts(self, server: MCPServerConfig) -> bool:
        return server.transport == "native" and server.id in self.providers

    def _run(
        self,
        server: MCPServerConfig,
        name: str | None = None,
        arguments: dict[str, Any] | None = None,
        expected: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        if not self.accepts(server):
            raise MCPFailure("当前设备不支持这项应用连接。")
        client = self.providers[server.id]
        if name is None:
            return client.discover(server)
        if expected is None:
            raise MCPFailure("请先连接并确认工具列表。")
        return client.call(server, name, arguments or {}, expected, timeout)
