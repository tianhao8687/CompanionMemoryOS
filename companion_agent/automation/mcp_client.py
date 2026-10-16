"""Short-lived MCP sessions. Server processes and credentials never come from the model."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from contextlib import AsyncExitStack
from datetime import timedelta
from typing import Any

import httpx

from companion_agent.automation.models import MCPServerConfig


class MCPFailure(RuntimeError):
    pass


class MCPClient:
    def discover(self, server: MCPServerConfig) -> list[dict[str, Any]]:
        result = self._run(server)
        assert isinstance(result, list)
        return result

    def call(
        self,
        server: MCPServerConfig,
        name: str,
        arguments: dict[str, Any],
        expected: dict[str, Any],
        timeout: float | None = None,
    ) -> dict[str, Any]:
        result = self._run(server, name, arguments, expected, timeout)
        assert isinstance(result, dict)
        return result

    def _run(
        self,
        server: MCPServerConfig,
        name: str | None = None,
        arguments: dict[str, Any] | None = None,
        expected: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        if server.transport == "native":
            raise MCPFailure("此引擎未连接安卓音乐服务。")
        try:
            # A Windows stdio MCP process belongs to the SDK's kill-on-close Job.
            # A GUI launched inside it would be killed before forwarding its command.
            # Retain the existing host route for the two fixed bundled music tools.
            # open_song now uses CDP and never launches; open_app remains separate.
            # ToolHub authorization/idempotency and exact contracts still apply.
            from companion_agent.automation.bundled_music import is_bundled_music

            if (
                sys.platform == "win32"
                and name in {"netease_open_app", "netease_open_song"}
                and is_bundled_music(server, sys.executable)
            ):
                return asyncio.run(
                    self._host_music_launch(server, name, arguments, expected, timeout)
                )
            return asyncio.run(self._session(server, name, arguments, expected, timeout))
        except Exception:
            # Never expose subprocess stderr, headers, credentials or SDK exception groups.
            raise MCPFailure("MCP 连接或执行失败；请检查服务、环境变量和超时设置。") from None

    async def _host_music_launch(
        self,
        server: MCPServerConfig,
        name: str,
        arguments: dict[str, Any] | None,
        expected: dict[str, Any] | None,
        timeout: float | None,
    ) -> dict[str, Any]:
        from companion_agent.integrations.netease import build_server

        # Use the same MCP definitions and argument validation as discovery. No second
        # schema, model-selected executable, generic dispatch, or retry on failure.
        async with asyncio.timeout(min(server.timeout_seconds, timeout or server.timeout_seconds)):
            local = build_server()
            tool = next((tool for tool in await local.list_tools() if tool.name == name), None)
            if (
                tool is None
                or {
                    "name": tool.name,
                    "description": (tool.description or "")[:2000],
                    "inputSchema": tool.inputSchema,
                }
                != expected
            ):
                raise MCPFailure("tool changed; rediscover and authorize")
            result = await local.call_tool(name, arguments or {})
            if not isinstance(result, tuple):
                raise MCPFailure("bundled launch result is missing structured content")
            content, structured = result
            return self._result(content, structured, False)

    @staticmethod
    def _result(content: Any, structured: Any, is_error: bool) -> dict[str, Any]:
        text = "\n".join(item.text for item in content if item.type == "text")[:12000]
        if structured is not None and len(json.dumps(structured)) > 12000:
            structured = {"truncated": True}
        declared = structured.get("status") if isinstance(structured, dict) else None
        status = (
            "failed"
            if is_error
            else (
                declared
                if declared in {"succeeded", "failed", "uncertain", "denied"}
                else "succeeded"
            )
        )
        return {"status": status, "text": text, "data": structured}

    async def _session(
        self,
        server: MCPServerConfig,
        name: str | None,
        arguments: dict[str, Any] | None,
        expected: dict[str, Any] | None,
        timeout: float | None,
    ) -> Any:
        # Desktop integrations are optional in an embedded mobile runtime.
        # Import their transport only when a user-authorized connection is used.
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.sse import sse_client
        from mcp.client.stdio import stdio_client
        from mcp.client.streamable_http import streamable_http_client

        limit = min(server.timeout_seconds, timeout or server.timeout_seconds)
        async with asyncio.timeout(limit), AsyncExitStack() as stack:
            if server.transport == "stdio":
                env = {key: os.environ[value] for key, value in server.env.items()}
                # The SDK inherits only its minimal platform environment, not all secrets.
                log = stack.enter_context(open(os.devnull, "w"))  # noqa: SIM115
                streams = await stack.enter_async_context(
                    stdio_client(
                        StdioServerParameters(command=server.command, args=server.args, env=env),
                        errlog=log,
                    )
                )
                read, write = streams
            else:
                headers = (
                    {"Authorization": f"Bearer {os.environ[server.bearer_env]}"}
                    if server.bearer_env
                    else {}
                )
                if server.transport == "sse":
                    read, write = await stack.enter_async_context(
                        sse_client(
                            server.url,
                            headers=headers,
                            timeout=limit,
                            sse_read_timeout=limit,
                        )
                    )
                else:
                    client = await stack.enter_async_context(
                        httpx.AsyncClient(
                            headers=headers,
                            timeout=limit,
                            follow_redirects=False,
                            trust_env=False,
                        )
                    )
                    read, write, _ = await stack.enter_async_context(
                        streamable_http_client(
                            server.url,
                            http_client=client,
                        )
                    )
            session = await stack.enter_async_context(
                ClientSession(
                    read,
                    write,
                    read_timeout_seconds=timedelta(seconds=limit),
                )
            )
            await session.initialize()
            catalog: list[dict[str, Any]] = []
            cursor: str | None = None
            for _ in range(8):
                page = await session.list_tools(cursor=cursor)
                for tool in page.tools:
                    item = {
                        "name": tool.name,
                        "description": (tool.description or "")[:2000],
                        "inputSchema": tool.inputSchema,
                    }
                    if len(json.dumps(item)) > 16000 or len(catalog) >= 128:
                        raise MCPFailure("tool catalog exceeds limit")
                    catalog.append(item)
                cursor = page.nextCursor
                if not cursor:
                    break
            else:
                raise MCPFailure("too many catalog pages")
            if name is None:
                return catalog
            found = next((item for item in catalog if item["name"] == name), None)
            if found is None or found != expected:
                raise MCPFailure("tool changed; rediscover and authorize")
            result = await session.call_tool(name, arguments or {})
            return self._result(result.content, result.structuredContent, result.isError)
