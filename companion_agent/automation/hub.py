from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from threading import RLock
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry

from companion_agent.automation.mcp_client import MCPClient
from companion_agent.automation.models import (
    AutomationConfig,
    MCPServerConfig,
    ScheduleInput,
    ToolRule,
)
from companion_agent.automation.scheduler import Scheduler
from companion_agent.automation.store import AutomationStore, utc_now
from companion_memoryos.database import Database


def canonical(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def definition(
    name: str, description: str, properties: dict[str, Any], required: list[str] | None = None
) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required or [],
                "additionalProperties": False,
            },
        },
    }


BUILTINS = [
    definition("local_time", "读取当前本地时间与日期，解释用户说的明天、下周等时间。", {}),
    definition("schedule_list", "查询当前对话的提醒和定时任务。", {}),
    definition(
        "schedule_cancel",
        "根据用户要求取消当前对话的一个任务。",
        {"job_id": {"type": "string"}},
        ["job_id"],
    ),
    definition(
        "schedule_create",
        "用户要求提醒或定时操作时创建任务；需要明确未来时间。"
        "提醒在应用内送达，服务需要保持运行。外部工具仍按工具权限执行。",
        {
            "title": {"type": "string", "maxLength": 100},
            "message": {"type": "string", "maxLength": 2000},
            "at": {
                "type": "string",
                "description": "带时区的 ISO 8601 时间，如 2026-09-23T09:00:00+08:00",
            },
            "timezone": {"type": "string", "default": "Asia/Shanghai"},
            "repeat": {"type": "string", "enum": ["once", "daily", "interval"]},
            "interval_minutes": {"type": "integer", "minimum": 1},
            "tool_name": {"type": "string", "description": "可选：已连接的 mcp_ 工具名"},
            "arguments": {"type": "object", "description": "可选：定时执行该工具的固定参数"},
        },
        ["title", "message", "at"],
    ),
]


class ToolHub:
    def __init__(self, database: Database, client: MCPClient | None = None) -> None:
        self.store = AutomationStore(database)
        self.client = client or MCPClient()
        self.lock = RLock()
        self.available: Callable[[], bool] = lambda: True
        with database.connection() as db:
            row = db.execute("SELECT data FROM agent_config WHERE id=1").fetchone()
        saved = json.loads(row["data"]) if row else {}
        self.config = AutomationConfig.model_validate(saved.get("config", {}))
        self.catalog: dict[str, list[dict[str, Any]]] = saved.get("catalog", {})
        self.scheduler = Scheduler(self.store)
        self.scheduler.dispatch = self.dispatch_job
        self.scheduler.enabled = lambda: self.available() and self.config.loop.enabled

    def persist(self) -> None:
        with self.store.database.connection() as db:
            db.execute(
                "INSERT INTO agent_config VALUES (1, ?) "
                "ON CONFLICT(id) DO UPDATE SET data=excluded.data",
                (
                    canonical(
                        {
                            "config": self.config.model_dump(mode="json"),
                            "catalog": self.catalog,
                        }
                    ),
                ),
            )

    def configure(self, config: AutomationConfig) -> None:
        with self.lock:
            previous = {server.id: server for server in self.config.servers}
            self.catalog = {
                server.id: self.catalog[server.id]
                for server in config.servers
                if server.id in self.catalog
                and server.model_dump(exclude={"tools", "enabled"})
                == (
                    previous[server.id].model_dump(exclude={"tools", "enabled"})
                    if server.id in previous
                    else {}
                )
            }
            self.config = config.model_copy(deep=True)
            self.persist()

    def server(self, server_id: str) -> MCPServerConfig:
        server = next((s for s in self.config.servers if s.id == server_id and s.enabled), None)
        if server is None:
            raise ValueError("MCP 服务未启用。")
        return server

    def discover(self, server_id: str) -> list[dict[str, Any]]:
        with self.lock:
            server = self.server(server_id)
            catalog = self.client.discover(server)
            for item in catalog:
                Draft202012Validator.check_schema(item["inputSchema"])
            if len({item["name"] for item in catalog}) != len(catalog):
                raise ValueError("MCP 工具名称重复。")
            self.catalog[server_id] = catalog
            self.persist()
            return catalog

    def bindings(self) -> dict[str, tuple[MCPServerConfig, dict[str, Any], ToolRule]]:
        result = {}
        for server in self.config.servers:
            if server.enabled:
                for tool in self.catalog.get(server.id, []):
                    rule = server.tools.get(tool["name"], ToolRule())
                    if rule.mode != "off":
                        name = f"mcp_{server.id}_{digest(tool['name'])[:12]}"
                        result[name] = (server, tool, rule)
        return result

    def definitions(self) -> list[dict[str, Any]]:
        with self.lock:
            result = list(BUILTINS)
            for name, (server, tool, rule) in self.bindings().items():
                result.append(
                    {
                        "type": "function",
                        "function": {
                            "name": name,
                            "description": f"{server.label} / {tool['name']}（权限 {rule.mode}）\n"
                            + tool["description"][:1000],
                            "parameters": tool["inputSchema"],
                        },
                    }
                )
            # Keep provider tool/context limits bounded.
            return result[:64]

    def inspect(self, name: str, arguments: dict[str, Any]) -> tuple[str, str]:
        if len(canonical(arguments)) > 12000:
            raise ValueError("工具参数过长。")
        builtin = next((d for d in BUILTINS if d["function"]["name"] == name), None)
        if builtin:
            schema = builtin["function"]["parameters"]
            mode, fingerprint = "allow", digest(builtin)
        else:
            binding = self.bindings().get(name)
            if binding is None:
                raise ValueError("工具不存在或已禁用，请重新连接。")
            server, tool, rule = binding
            schema = tool["inputSchema"]
            mode, fingerprint = rule.mode, digest([server.model_dump(), tool])
            for field, allowed in rule.arguments.items():
                # Compare JSON encodings so bools cannot match integer enum entries.
                if field not in arguments or canonical(arguments[field]) not in {
                    canonical(value) for value in allowed
                }:
                    raise ValueError("参数超出已设置的联系人、设备或应用范围。")
        try:
            # An empty registry prevents schemas from making network requests via $ref.
            Draft202012Validator(schema, registry=Registry()).validate(arguments)
        except Exception:
            raise ValueError("工具参数不符合接口要求。") from None
        return mode, fingerprint

    def invoke(
        self,
        name: str,
        arguments: dict[str, Any],
        conversation: str,
        request_id: str,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        with self.lock:
            if not self.available() or not self.config.loop.enabled:
                return {"status": "denied", "message": "工具运行已关闭。"}
            try:
                mode, fingerprint = self.inspect(name, arguments)
            except ValueError as error:
                return {"status": "denied", "message": str(error)}
            action_id = digest([conversation, request_id, name, arguments])[:32]
            with self.store.database.atomic() as db:
                old = db.execute("SELECT * FROM agent_actions WHERE id=?", (action_id,)).fetchone()
                if old:
                    return {
                        **json.loads(old["result"]),
                        "action_id": action_id,
                        "status": old["status"],
                        "reused": True,
                    }
                status = "pending" if mode == "ask" else "running"
                result = {"status": status, "action_id": action_id}
                db.execute(
                    "INSERT INTO agent_actions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        action_id,
                        conversation,
                        request_id,
                        name,
                        canonical(arguments),
                        fingerprint,
                        status,
                        canonical(result),
                        utc_now(),
                        utc_now(),
                    ),
                )
            if mode == "ask":
                return result
            return self._execute(action_id, name, arguments, conversation, request_id, timeout)

    def _execute(
        self,
        action_id: str,
        name: str,
        arguments: dict[str, Any],
        conversation: str,
        request_id: str,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        try:
            if name.startswith("mcp_"):
                server, tool, _ = self.bindings()[name]
                result = self.client.call(server, tool["name"], arguments, tool, timeout)
            else:
                result = self._builtin(name, arguments, conversation, request_id + action_id)
        except ValueError:
            result = {"status": "failed", "message": "参数或任务状态无效，请检查内容与时间。"}
        except Exception:
            result = {"status": "uncertain", "message": "工具没有返回明确结果，请核对后再操作。"}
        result["action_id"] = action_id
        with self.store.database.connection() as db:
            db.execute(
                "UPDATE agent_actions SET status=?, result=?, updated_at=? WHERE id=?",
                (result["status"], canonical(result), utc_now(), action_id),
            )
        return result

    def approve(self, action_id: str, approved: bool) -> dict[str, Any]:
        with self.lock:
            if approved and (not self.available() or not self.config.loop.enabled):
                raise ValueError("工具运行已关闭。")
            with self.store.database.atomic() as db:
                row = db.execute("SELECT * FROM agent_actions WHERE id=?", (action_id,)).fetchone()
                if row is None or row["status"] != "pending":
                    raise ValueError("该操作不存在或已处理。")
                args = json.loads(row["arguments"])
                if approved:
                    _, fingerprint = self.inspect(row["tool_name"], args)
                    if fingerprint != row["fingerprint"]:
                        raise ValueError("工具配置已变化，请拒绝此操作并重新发起。")
                    if (
                        datetime.now(UTC) - datetime.fromisoformat(row["created_at"])
                    ).total_seconds() > 900:
                        raise ValueError("操作已超过 15 分钟，请拒绝后重新发起。")
                db.execute(
                    "UPDATE agent_actions SET status=?, updated_at=? WHERE id=?",
                    ("running" if approved else "denied", utc_now(), action_id),
                )
            if not approved:
                denied = {"status": "denied", "action_id": action_id}
                with self.store.database.connection() as db:
                    db.execute(
                        "UPDATE agent_actions SET result=? WHERE id=?",
                        (canonical(denied), action_id),
                    )
                return denied
            result = self._execute(
                action_id, row["tool_name"], args, row["conversation_id"], row["request_id"]
            )
            summary = {
                "succeeded": "操作已完成。",
                "failed": "操作失败，请查看记录。",
                "uncertain": "暂时无法确认操作结果，请先核对外部应用。",
            }
            self.store.notification(
                row["conversation_id"],
                "工具执行结果",
                summary.get(result["status"], "操作已结束，请查看记录。"),
            )
            return result

    def _builtin(
        self, name: str, args: dict[str, Any], conversation: str, key: str
    ) -> dict[str, Any]:
        if name == "local_time":
            from zoneinfo import ZoneInfo

            return {
                "status": "succeeded",
                "time": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
            }
        if name == "schedule_list":
            return {
                "status": "succeeded",
                "jobs": [
                    j for j in self.store.jobs() if j["data"]["conversation_id"] == conversation
                ],
            }
        if name == "schedule_cancel":
            if not any(
                j["id"] == args["job_id"] and j["data"]["conversation_id"] == conversation
                for j in self.store.jobs()
            ):
                raise ValueError("找不到当前对话的任务。")
            self.scheduler.change(args["job_id"], "cancelled")
            return {"status": "succeeded", "message": "任务已取消。"}
        if name == "schedule_create":
            item = ScheduleInput.model_validate({**args, "conversation_id": conversation})
            if item.tool_name:
                if not item.tool_name.startswith("mcp_"):
                    raise ValueError("只能定时调用已连接的 MCP 工具。")
                self.inspect(item.tool_name, item.arguments)
            return self.scheduler.create(item, key)
        raise ValueError("未知工具。")

    def dispatch_job(self, row: dict[str, Any], key: str) -> dict[str, Any]:
        item = ScheduleInput.model_validate_json(row["data"])
        return self.invoke(item.tool_name or "", item.arguments, item.conversation_id, key)

    def public_state(self) -> dict[str, Any]:
        with self.lock:
            return {
                "config": self.config.model_dump(mode="json"),
                "catalog": self.catalog,
                "tools": [
                    {
                        "name": name,
                        "server_id": server.id,
                        "remote_name": tool["name"],
                        "mode": rule.mode,
                    }
                    for name, (server, tool, rule) in self.bindings().items()
                ],
                "actions": self.store.actions(),
                "jobs": self.store.jobs(),
                "notifications": self.store.notifications(),
            }
