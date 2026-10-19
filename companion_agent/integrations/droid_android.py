"""Native droid-mcp SDK adapter; every action still passes through ToolHub."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry

from companion_agent.automation.mcp_client import MCPClient, MCPFailure
from companion_agent.automation.models import MCPServerConfig, ToolRule
from companion_agent.integrations.droid_catalog import GROUPS, TOOL_NAMES, UI_TOOLS, definition

Bridge = Callable[[str, dict[str, Any], int], dict[str, Any]]


class AndroidPhoneClient(MCPClient):
    def __init__(self, bridge: Bridge) -> None:
        self.bridge = bridge

    def state(self) -> dict[str, Any]:
        try:
            state = self.bridge("state", {}, 2000)
            return {**state, "groups": GROUPS, "provider": "droid-mcp v0.11.0"}
        except Exception:
            return {"supported": False, "message": "手机能力暂未就绪，请重启应用后重试。"}

    def template(self) -> MCPServerConfig:
        if not self.state().get("supported"):
            raise MCPFailure("手机能力需要 Android 9 或更高版本。")
        return MCPServerConfig(
            id="droid",
            label="手机能力",
            transport="native",
            enabled=False,
            tools={
                name: ToolRule(
                    mode="off" if name in UI_TOOLS or name == "read_chat_notifications" else "ask"
                )
                for name in TOOL_NAMES
            },
        )

    def _run(
        self,
        server: MCPServerConfig,
        name: str | None = None,
        arguments: dict[str, Any] | None = None,
        expected: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        if server.transport != "native" or server.id != "droid":
            raise MCPFailure("不支持此手机连接。")
        budget = min(
            server.timeout_seconds, timeout if timeout is not None else server.timeout_seconds
        )
        if budget < 1:
            raise MCPFailure("剩余执行时间不足。")
        response = self.bridge("catalog", {}, 1000)
        if not response.get("supported"):
            raise MCPFailure("当前设备不支持手机能力。")
        raw = response.get("tools", [])
        if not isinstance(raw, list) or len(raw) > 64:
            raise MCPFailure("手机工具列表无效。")
        catalog = [definition(item) for item in raw if item.get("name") in TOOL_NAMES]
        if len({item["name"] for item in catalog}) != len(catalog):
            raise MCPFailure("手机工具名称重复。")
        if name is None:
            return catalog
        actual = next((item for item in catalog if item["name"] == name), None)
        if actual is None or actual != expected:
            raise MCPFailure("手机工具已变化，请重新连接。")
        args = arguments or {}
        Draft202012Validator(actual["inputSchema"], registry=Registry()).validate(args)
        # The JNI call and SDK coroutine own the deadline. Never retry a write
        # after an ambiguous response or start an unbounded detached worker.
        data = self.bridge(
            "call", {"name": name, "arguments": args}, max(1, int((budget - 0.5) * 1000))
        )
        if data.get("status") not in {"succeeded", "failed", "uncertain", "denied"}:
            data = {"status": "uncertain", "message": "手机未返回明确结果，请先核对。"}
        encoded = json.dumps(data, ensure_ascii=False)
        if len(encoded) > 12000:
            data = {"status": "uncertain", "message": "手机结果过长，请缩小读取范围后核对。"}
            encoded = json.dumps(data, ensure_ascii=False)
        return {"status": data["status"], "text": encoded, "data": data}


def android_phone_client(context: Any) -> AndroidPhoneClient:
    from importlib import import_module

    native = import_module("java").jclass("com.xinyu.xinyu_flutter.PhoneBridge")

    def invoke(operation: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
        raw = str(
            native.exchange(context, operation, json.dumps(payload, ensure_ascii=False), timeout)
        )
        if len(raw) > 100000:
            raise MCPFailure("手机返回数据过长。")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise MCPFailure("手机返回格式无效。")
        return value

    return AndroidPhoneClient(invoke)
