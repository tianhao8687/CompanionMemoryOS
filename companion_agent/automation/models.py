from __future__ import annotations

import ipaddress
from contextlib import suppress
from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator, model_validator

from companion_agent.persona.models import PersonaModel


class LoopConfig(PersonaModel):
    enabled: bool = True
    max_steps: int = Field(default=6, ge=1, le=12)
    max_tool_calls: int = Field(default=8, ge=1, le=24)
    timeout_seconds: int = Field(default=180, ge=10, le=600)
    max_total_tokens: int = Field(default=30000, ge=1000, le=100000)


class ToolRule(PersonaModel):
    mode: Literal["ask", "allow", "off"] = "ask"
    # Exact, top-level argument allowlists, e.g. recipient_id or package_name.
    arguments: dict[str, list[str | int | bool]] = Field(default_factory=dict, max_length=20)


class MCPServerConfig(PersonaModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,31}$")
    label: str = Field(min_length=1, max_length=80)
    enabled: bool = False
    transport: Literal["stdio", "streamable_http", "sse"] = "stdio"
    command: str = Field(default="", max_length=1000)
    args: list[str] = Field(default_factory=list, max_length=40)
    url: str = Field(default="", max_length=2000)
    # Values are environment variable NAMES, never credentials in the settings DB.
    env: dict[str, str] = Field(default_factory=dict, max_length=30)
    bearer_env: str = Field(default="", max_length=128)
    timeout_seconds: int = Field(default=20, ge=2, le=60)
    tools: dict[str, ToolRule] = Field(default_factory=dict, max_length=128)

    @model_validator(mode="after")
    def valid_transport(self) -> MCPServerConfig:
        import re

        for name in [*self.env, *self.env.values(), self.bearer_env]:
            if name and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                raise ValueError("use environment variable names for credentials")
        if self.transport == "stdio":
            if not self.command.strip() or self.url or self.bearer_env:
                raise ValueError("stdio requires a command, not a URL")
            if any("\x00" in part for part in [self.command, *self.args]):
                raise ValueError("invalid command")
        else:
            parts = urlsplit(self.url)
            local = parts.hostname == "localhost"
            with suppress(ValueError):
                local = local or ipaddress.ip_address(parts.hostname or "").is_loopback
            if (
                not parts.hostname
                or parts.username
                or parts.password
                or parts.query
                or parts.fragment
                or parts.scheme not in {"http", "https"}
                or (parts.scheme == "http" and not local)
            ):
                raise ValueError("use HTTPS, or loopback HTTP; no URL credentials/query")
            if self.command or self.args or self.env:
                raise ValueError("HTTP transport does not use command or env")
        return self


class AutomationConfig(PersonaModel):
    loop: LoopConfig = Field(default_factory=LoopConfig)
    servers: list[MCPServerConfig] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def unique_servers(self) -> AutomationConfig:
        if len({server.id for server in self.servers}) != len(self.servers):
            raise ValueError("duplicate server id")
        return self


class ScheduleInput(PersonaModel):
    title: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=2000)
    at: datetime
    timezone: str = "Asia/Shanghai"
    repeat: Literal["once", "daily", "interval"] = "once"
    interval_minutes: int | None = Field(default=None, ge=1, le=525600)
    conversation_id: str = Field(min_length=1, max_length=128)
    tool_name: str | None = Field(default=None, max_length=64)
    arguments: dict[str, Any] = Field(default_factory=dict)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ValueError, KeyError) as error:
            raise ValueError("unknown timezone") from error
        return value

    @model_validator(mode="after")
    def valid_schedule(self) -> ScheduleInput:
        if self.at.tzinfo is None or self.at.utcoffset() is None:
            raise ValueError("schedule time requires a UTC offset")
        if self.repeat == "interval" and self.interval_minutes is None:
            raise ValueError("interval_minutes is required")
        if not self.title.strip() or not self.message.strip():
            raise ValueError("schedule text is required")
        return self
