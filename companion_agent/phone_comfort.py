"""Small, reversible phone adjustments chosen by the chat model, with saved consent."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from time import monotonic
from typing import TYPE_CHECKING, Any

from companion_agent.automation.hub import digest
from companion_agent.current_state.evaluator import analyze_current_turn
from companion_agent.music_profile import current_source
from companion_agent.phone_environment import screen_environment
from companion_agent.streaming import cancelled
from companion_memoryos.discourse import asserted_clause, direct_clauses, negated_predicate

if TYPE_CHECKING:
    from companion_agent.app import ChatInput, RomanceHost

TOOL = "app_comfort_phone"
RESTORE = "app_restore_phone"
CHANNELS = {
    "media": ("get_settings", "set_volume", "媒体音量"),
    "screen": ("get_settings", "set_brightness", "屏幕亮度"),
    "interruptions": ("get_dnd_status", "set_dnd_mode", "勿扰"),
}
REFUSAL = re.compile(
    r"(?:别|不要|不用|不想|不需要|停止).{0,10}(?:自动|主动|替我|帮我|擅自).{0,8}(?:调|改|操作|动手机)"
    r"|(?:别|不要|不用|不想|不需要).{0,5}(?:调|改|操作|动).{0,8}(?:手机|音量|亮度|勿扰|设置)"
    r"|(?:关闭|关掉|取消|停用).{0,6}(?:手机陪伴|情绪联动|手机联动)"
)
RESTORE_REQUEST = re.compile(r"恢复|还原|调回|改回|撤销")
EXCLUDED = re.compile(
    r"功能|代码|测试|翻译|台词|举例|假设|如果|人设|扮演|故事|小说|昨天|以前|曾经|上次"
)
BUSY = re.compile(
    r"(?:正|我|还)在.{0,3}(?:开车|驾车|导航|开会|上课|通话)"
    r"|(?:等|不能错过|要接).{0,12}(?:电话|来电|消息|通知)"
    r"|只(?:想|要).{0,6}(?:聊|听我说)|什么都别做|别做别的"
)


def refused(text: str) -> bool:
    return any(
        asserted_clause(clause)
        and (match := REFUSAL.search(clause))
        and not negated_predicate(clause, match.start())
        for clause in direct_clauses(text)
    )


def evidence_in_turn(text: str, evidence: str) -> bool:
    # The model decides whether the situation calls for help. This only anchors
    # that decision to an actual present-tense self-report, never a memory/quote.
    return len(evidence.strip()) >= 3 and any(
        evidence in clause and asserted_clause(clause) and not EXCLUDED.search(clause)
        for clause in direct_clauses(text)
    )


def available_turn(text: str) -> bool:
    state = analyze_current_turn(text)
    return not (
        refused(text)
        or state.concrete_task
        or state.celebrating
        or any(asserted_clause(clause) and BUSY.search(clause) for clause in direct_clauses(text))
    )


def restore_requested(text: str) -> bool:
    return any(
        asserted_clause(clause)
        and (match := RESTORE_REQUEST.search(clause))
        and not negated_predicate(clause, match.start())
        for clause in direct_clauses(text)
    )


class PhoneComfort:
    def __init__(self, host: RomanceHost) -> None:
        self.host = host
        self.manual_restore: ContextVar[bool] = ContextVar("phone_manual_restore", default=False)
        with host.database.connection() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS phone_comfort_changes ("
                "channel TEXT PRIMARY KEY, action_id TEXT NOT NULL, conversation_id TEXT NOT NULL, "
                "before_state TEXT NOT NULL, after_state TEXT NOT NULL, status TEXT NOT NULL, "
                "created_at TEXT NOT NULL)"
            )

    def active(self) -> list[dict[str, Any]]:
        with self.host.database.connection() as db:
            rows = db.execute("SELECT * FROM phone_comfort_changes ORDER BY channel").fetchall()
        return [
            {
                **dict(row),
                "before_state": json.loads(row["before_state"]),
                "after_state": json.loads(row["after_state"]),
            }
            for row in rows
        ]

    def public_state(self) -> dict[str, Any]:
        return {
            "paused": self.paused(),
            "active": [
                {
                    "channel": row["channel"],
                    "action_id": row["action_id"],
                    "title": CHANNELS[row["channel"]][2],
                    "status": row["status"],
                    "created_at": row["created_at"],
                }
                for row in self.active()
            ],
        }

    def paused(self) -> bool:
        until = self.host.tools.config.phone_comfort.paused_until
        return until is not None and until > datetime.now(UTC)

    def control(self, action: str, action_ids: list[str]) -> dict[str, Any]:
        # UI-only controls share the execution lock with phone operations. A stale
        # screen must never discard a newer action's recovery information.
        with self.host.tools.lock:
            if action == "keep":
                rows = self.active()
                if rows and (
                    {row["action_id"] for row in rows} != set(action_ids)
                    or any(row["status"] != "applied" for row in rows)
                ):
                    raise ValueError("调整记录已变化或结果尚未确认，请刷新并核对后再保留。")
                with self.host.database.connection() as db:
                    db.execute("DELETE FROM phone_comfort_changes")
                return {
                    "status": "succeeded",
                    "message": "已保留当前设置，不再恢复这次调整。下次仍遵守联动间隔。",
                }
            config = self.host.tools.config.model_copy(deep=True)
            if action == "pause":
                config.phone_comfort.paused_until = datetime.now(UTC) + timedelta(minutes=15)
                message = "已暂停主动联动 15 分钟。聊天和手动恢复仍可使用。"
            elif action == "resume":
                config.phone_comfort.paused_until = None
                message = (
                    "已结束暂停，TA 会在后续聊天中判断是否需要调整。"
                    if config.phone_comfort.enabled
                    else "已结束暂停；手机陪伴仍保持关闭。"
                )
            else:
                raise ValueError("未知的手机陪伴操作。")
            self.host.tools.configure(config)
            return {"status": "succeeded", "message": message}

    def observe(self, item: ChatInput) -> None:
        if self.host.tools.config.phone_comfort.enabled and refused(item.content):
            config = self.host.tools.config.model_copy(deep=True)
            config.phone_comfort.enabled = False
            self.host.tools.configure(config)

    def context(self) -> str:
        config = self.host.tools.config.phone_comfort
        active = [CHANNELS[row["channel"]][2] for row in self.active()]
        if not config.enabled and not active:
            return ""
        return (
            "\n[聊天中的手机陪伴] "
            + (
                "用户已暂停主动手机调整，暂停期间只聊天；用户明确要求恢复时仍可核对恢复。"
                if config.enabled and self.paused()
                else "用户已一次性开启："
                + "、".join(
                    label for channel, (_, _, label) in CHANNELS.items() if getattr(config, channel)
                )
                if config.enabled
                else "主动手机调整已关闭。"
            )
            + "。这是 app_comfort_phone 的有限授权，不授权通用点击、输入、发消息或打开其他应用。"
            "结合当前聊天语义判断是否适合，不按关键词机械触发，也不每轮都操作。先回应人的感受。"
            "疲惫准备歇息、眼睛被屏幕刺得不舒服时可选 screen；"
            "screen 会按需读取环境光和接近传感器，仅前台、低光稳定且未疑似遮挡时调暗；"
            "系统自动亮度已开启、环境偏亮或读数不可用时保持亮度。光线不能证明用户情绪或房间全貌。"
            "设备声音让人烦躁、想安静时可选 media；"
            "明确受通知打断、想暂时不被打扰时才考虑 interruptions。单纯难过不等于需要勿扰，"
            "等待重要来电/消息、通话、开车导航、会议或正在处理任务时保持设置。"
            "只引用本轮用户直接表达的一小段作为 evidence，scene 为 rest/overload/wind_down，"
            "选最多两种真正相关的调整，不填具体数值。无需再追问指令或逐次确认；"
            "不合适就继续陪伴。工具 skipped 后不重试，也不用普通手机工具绕过检查。"
            "工具只有 verified=true 的变化才可说已经调整，轻声说明做了什么，并可随时恢复。"
            "用户已缓过来、结束休息或要求恢复时，用 app_restore_phone 核对并恢复本次调整；"
            "用户手动改过的值会保留。用户拒绝代调时立即停止主动调整。"
            "没有后台定时恢复；不能承诺离开应用或到点后自动恢复。"
            f"两次调整尝试至少间隔 {config.cooldown_minutes} 分钟；暂停到期仅允许后续聊天重新判断，"
            "不会到点自动操作手机。"
            + (
                "当前仍保留的调整：" + "、".join(active) + "。"
                if active
                else "当前没有待恢复调整。"
            )
            + "\n"
        )

    @staticmethod
    def skipped(reason: str, message: str, **extra: Any) -> dict[str, Any]:
        return {
            "status": "succeeded",
            "outcome": "skipped",
            "verified": False,
            "reason": reason,
            "message": message,
            **extra,
        }

    def _cooling(self, action_id: str) -> bool:
        cooldown = timedelta(minutes=self.host.tools.config.phone_comfort.cooldown_minutes)
        with self.host.database.connection() as db:
            rows = db.execute(
                "SELECT status, result FROM agent_actions WHERE tool_name IN (?,?) AND id<>? "
                "AND updated_at>=?",
                (TOOL, RESTORE, action_id, (datetime.now(UTC) - cooldown).isoformat()),
            ).fetchall()
        return any(
            row["status"] in {"running", "uncertain", "failed"}
            or json.loads(row["result"]).get("attempted") is True
            for row in rows
        )

    def _call(
        self, tool: str, args: dict[str, Any], conversation: str, key: str, deadline: float
    ) -> dict[str, Any]:
        hub = self.host.tools
        name = f"mcp_droid_{digest(tool)[:12]}"
        signal = cancelled.get()
        if deadline - monotonic() < 2 or (signal is not None and signal.is_set()):
            return {"status": "denied"}
        binding = hub.bindings().get(name)
        if binding is None or binding[0].transport != "native":
            return {"status": "denied"}
        try:
            if hub.inspect(name, args)[0] != "allow":
                return {"status": "denied"}
        except ValueError:
            return {"status": "denied"}
        return hub.invoke(name, args, conversation, key, deadline - monotonic())

    def _read(
        self, channel: str, conversation: str, key: str, deadline: float
    ) -> dict[str, Any] | None:
        result = self._call(CHANNELS[channel][0], {}, conversation, key, deadline)
        if result.get("status") != "succeeded":
            return None
        data = result.get("data", {})
        if channel == "interruptions":
            mode = data.get("filter")
            return (
                {"mode": "off" if mode == "all" else mode}
                if mode in {"all", "priority", "alarms", "none"}
                and data.get("has_policy_access") is True
                else None
            )
        if data.get("audio_mode") != 0:
            return None  # Calls/ringtone/unknown audio state are never adjusted.
        if channel == "media":
            level, maximum = data.get("volume_media"), data.get("volume_media_max")
            if type(level) is int and type(maximum) is int and 0 <= level <= maximum <= 100:
                return {"level": level, "max": maximum, "playing": data.get("music_active") is True}
        else:
            level, mode = data.get("screen_brightness"), data.get("brightness_mode")
            if type(level) is int and 10 <= level <= 255 and mode in {0, 1}:
                return {"level": level, "automatic": mode == 1}
        return None

    @staticmethod
    def _target(
        channel: str, before: dict[str, Any], environment: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        if channel == "media":
            if not before["playing"] or before["level"] <= 1:
                return None
            return {
                **before,
                "level": max(1, before["level"] - max(1, round(before["max"] * 0.15))),
            }
        if channel == "screen":
            if (
                before["automatic"]
                or before["level"] <= 64
                or not (environment or {}).get("eligible")
            ):
                return None
            step = 40 if environment and environment["lux"] <= 20 else 20
            return {"level": max(64, before["level"] - step), "automatic": False}
        return {"mode": "priority"} if before["mode"] == "off" else None

    @staticmethod
    def _same(channel: str, left: dict[str, Any], right: dict[str, Any]) -> bool:
        keys = (
            ("level", "max")
            if channel == "media"
            else ("level", "automatic")
            if channel == "screen"
            else ("mode",)
        )
        return all(left.get(key) == right.get(key) for key in keys)

    @staticmethod
    def _args(channel: str, target: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
        if channel == "media":
            return {
                "stream": "media",
                "level": target["level"],
                "expected_level": expected["level"],
                "require_idle_audio": True,
            }
        if channel == "screen":
            return {
                "level": target["level"],
                "automatic": target["automatic"],
                "expected_level": expected["level"],
                "expected_automatic": expected["automatic"],
                "require_idle_audio": True,
            }
        return {
            "mode": target["mode"],
            "expected_mode": expected["mode"],
            "require_idle_audio": True,
        }

    def _remove(self, channel: str) -> None:
        with self.host.database.connection() as db:
            db.execute("DELETE FROM phone_comfort_changes WHERE channel=?", (channel,))

    def adjust(self, args: dict[str, Any], conversation: str) -> dict[str, Any]:
        hub = self.host.tools
        active = hub.current_action.get()
        if not active or active[1] != conversation:
            return self.skipped("source", "没有当前聊天，保持手机现状。")
        action_id, _, request, timeout = active
        source = current_source(self.host, conversation, request)
        config = hub.config.phone_comfort
        if self.paused():
            return self.skipped("paused", "用户已暂停主动联动，继续聊天。")
        if (
            not config.enabled
            or source is None
            or not available_turn(source.content)
            or not evidence_in_turn(source.content, args["evidence"])
        ):
            return self.skipped("source", "当前不适合主动调整，继续聊天。")
        if self.active() or self._cooling(action_id):
            return self.skipped("cooldown", "已有陪伴调整或刚尝试过，保持现状，继续聊天。")
        deadline = monotonic() + min(40, timeout if timeout is not None else 40)
        changes: list[dict[str, Any]] = []
        environment: dict[str, Any] | None = None
        attempted = False
        for channel in dict.fromkeys(args["adjustments"]):
            if (
                not getattr(hub.config.phone_comfort, channel)
                or not hub.config.phone_comfort.enabled
                or self.paused()
            ):
                continue
            key = f"phone_comfort:{action_id}:{channel}"
            before = self._read(channel, conversation, key + ":before", deadline)
            observed_at = monotonic()
            if channel == "screen" and before is not None:
                environment = {
                    "eligible": False,
                    "reason": "automatic_brightness" if before["automatic"] else "already_dim",
                }
                if not before["automatic"] and before["level"] > 64:
                    light = self._call(
                        "get_light_level",
                        {"duration_ms": 1500},
                        conversation,
                        key + ":light",
                        deadline,
                    )
                    proximity = self._call(
                        "get_proximity", {}, conversation, key + ":proximity", deadline
                    )
                    environment = screen_environment(
                        light.get("data", {}), proximity.get("data", {})
                    )
                    if monotonic() - observed_at > 5:
                        environment = {"eligible": False, "reason": "expired"}
            target = self._target(channel, before, environment) if before is not None else None
            if before is None or target is None:
                continue
            # Save before sending the external effect, so a process exit keeps a
            # recoverable record rather than silently losing the original state.
            with self.host.database.connection() as db:
                db.execute(
                    "INSERT INTO phone_comfort_changes VALUES (?,?,?,?,?,?,?)",
                    (
                        channel,
                        action_id,
                        conversation,
                        json.dumps(before),
                        json.dumps(target),
                        "uncertain",
                        datetime.now(UTC).isoformat(),
                    ),
                )
            if (
                self.paused()
                or not hub.config.phone_comfort.enabled
                or not getattr(hub.config.phone_comfort, channel)
            ):
                self._remove(channel)
                break
            write_args = self._args(channel, target, before)
            if channel == "screen":
                if monotonic() - observed_at > 5:
                    self._remove(channel)
                    continue
                write_args["require_foreground"] = True
            attempted = True
            result = self._call(
                CHANNELS[channel][1],
                write_args,
                conversation,
                key + ":write",
                deadline,
            )
            after = self._read(channel, conversation, key + ":after", deadline)
            verified = (
                result.get("status") == "succeeded"
                and after is not None
                and self._same(channel, after, target)
            )
            if verified:
                with self.host.database.connection() as db:
                    db.execute(
                        "UPDATE phone_comfort_changes SET status='applied' WHERE channel=?",
                        (channel,),
                    )
            elif after is not None and self._same(channel, after, before):
                self._remove(channel)
            changes.append(
                {"channel": channel, "title": CHANNELS[channel][2], "verified": verified}
            )
            if not verified:
                break
        if not changes:
            return self.skipped(
                "unchanged",
                "无需调整或尚无对应权限，保持现状，继续陪伴。",
                attempted=attempted,
                environment=environment,
            )
        return {
            "status": "succeeded",
            "outcome": "adjusted",
            "attempted": attempted,
            "verified": all(change["verified"] for change in changes),
            "changes": changes,
            "environment": environment,
            "message": "仅说明已核对成功的调整；可在手机陪伴中恢复，不承诺定时恢复。",
        }

    @contextmanager
    def from_button(self) -> Iterator[None]:
        token = self.manual_restore.set(True)
        try:
            yield
        finally:
            self.manual_restore.reset(token)

    def restore(self, args: dict[str, Any], conversation: str) -> dict[str, Any]:
        hub = self.host.tools
        active = hub.current_action.get()
        if not active:
            return self.skipped("source", "没有可恢复的操作请求。")
        action_id, _, request, timeout = active
        explicit = self.manual_restore.get()
        if not self.manual_restore.get():
            source = current_source(self.host, conversation, request)
            if source is None or not evidence_in_turn(source.content, args.get("evidence", "")):
                return self.skipped("source", "仅根据当前聊天或恢复按钮核对恢复。")
            explicit = restore_requested(source.content)
            if RESTORE_REQUEST.search(source.content) and not explicit:
                return self.skipped("refusal", "用户没有要求恢复，保持当前设置。")
            if not explicit and (
                not hub.config.phone_comfort.enabled
                or self.paused()
                or not available_turn(source.content)
            ):
                return self.skipped("disabled", "已停用主动调整，保留当前设置。")
        deadline = monotonic() + min(40, timeout if timeout is not None else 40)
        changes: list[dict[str, Any]] = []
        for row in self.active():
            if not explicit and (
                row["conversation_id"] != conversation
                or datetime.now(UTC) - datetime.fromisoformat(row["created_at"])
                > timedelta(hours=6)
            ):
                continue
            channel = row["channel"]
            key = f"phone_restore:{action_id}:{channel}"
            current = self._read(channel, conversation, key + ":before", deadline)
            if current is None:
                changes.append({"channel": channel, "outcome": "unavailable"})
                continue
            if not self._same(channel, current, row["after_state"]):
                self._remove(channel)
                changes.append({"channel": channel, "outcome": "kept_current"})
                continue
            result = self._call(
                CHANNELS[channel][1],
                self._args(channel, row["before_state"], current),
                conversation,
                key + ":write",
                deadline,
            )
            after = self._read(channel, conversation, key + ":after", deadline)
            verified = (
                result.get("status") == "succeeded"
                and after is not None
                and (
                    self._same(channel, after, row["before_state"])
                    or (
                        channel == "screen"
                        and row["before_state"]["automatic"]
                        and after["automatic"]
                    )
                )
            )
            if verified:
                self._remove(channel)
            changes.append({"channel": channel, "outcome": "restored" if verified else "uncertain"})
        if not changes:
            return self.skipped("no_changes", "当前没有符合恢复条件的调整，保持手机现状。")
        return {
            "status": "succeeded",
            "outcome": "restored",
            "attempted": bool(changes),
            "verified": all(c["outcome"] in {"restored", "kept_current"} for c in changes),
            "changes": changes,
            "message": "已核对恢复；用户手动改过的设置保持现状，未确认的项目留待检查。",
        }
