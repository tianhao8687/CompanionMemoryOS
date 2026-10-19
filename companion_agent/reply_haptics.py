"""Optional expression attached to a completed reply, using the existing phone MCP path."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from companion_agent.automation.hub import digest
from companion_agent.integrations.droid_catalog import HAPTIC_PATTERNS
from companion_agent.music_profile import current_source
from companion_memoryos.discourse import asserted_clause, direct_clauses, negated_predicate

if TYPE_CHECKING:
    from companion_agent.app import ChatInput, RomanceHost

TOOL = "app_reply_haptic"
VIBRATE = f"mcp_droid_{digest('vibrate_pattern')[:12]}"
COOLDOWN_SECONDS = 20
REFUSAL = re.compile(
    r"(?:别|不要|不用|停止|不想|不需要|不喜欢).{0,6}(?:震动|振动|触感|震了|振了)"
    r"|(?:关闭|关掉|取消|停用).{0,6}(?:震动|振动|触感)"
)


def refused(text: str) -> bool:
    text = text.replace("‘", "“").replace("’", "”")
    return any(
        asserted_clause(clause)
        and (match := REFUSAL.search(clause))
        and not negated_predicate(clause, match.start())
        for clause in direct_clauses(text)
    )


class ReplyHaptics:
    def __init__(self, host: RomanceHost) -> None:
        self.host = host

    def available(self) -> bool:
        hub = self.host.tools
        if not (
            hub.config.reply_haptics_enabled
            and hub.config.loop.enabled
            and hub.available()
            and hub.external_available()
        ):
            return False
        try:
            mode, _ = hub.inspect(VIBRATE, {"timings": HAPTIC_PATTERNS[0], "repeat": -1})
            return mode == "allow"
        except ValueError:
            return False

    def observe(self, item: ChatInput) -> None:
        if self.host.tools.config.reply_haptics_enabled and refused(item.content):
            config = self.host.tools.config.model_copy(deep=True)
            config.reply_haptics_enabled = False
            self.host.tools.configure(config)

    def prepare(self, args: dict[str, Any], conversation: str) -> dict[str, Any]:
        hub = self.host.tools
        active = hub.current_action.get()
        if not active or not self.available():
            return {"status": "skipped", "reason": "disabled"}
        source = current_source(self.host, conversation, active[2])
        if source is None or refused(source.content):
            return {"status": "skipped", "reason": "no_current_turn"}
        if any(
            row["tool_name"] == TOOL and row["result"].get("delivery") == "prepared"
            for row in hub.store.request_actions(conversation, active[2])
        ):
            return {"status": "skipped", "reason": "already_prepared"}
        return {
            "status": "succeeded",
            "delivery": "prepared",
            "phrase": args["phrase"],
            "message": "已准备；尚未震动。继续自然回复，完成后才核对，不必向用户解释。",
        }

    def deliver(self, item: ChatInput, reply: str) -> None:
        hub = self.host.tools
        with hub.lock:
            if not self.available() or refused(item.content):
                return
            actions = hub.store.request_actions(item.conversation_id, item.request_id)
            manual = {
                f"mcp_droid_{digest(name)[:12]}"
                for name in ("vibrate", "vibrate_pattern", "cancel_vibration")
            }
            if any(row["tool_name"] in manual for row in actions):
                return  # Never add an automatic touch after an explicit touch/stop this turn.
            prepared = next(
                (
                    row["result"]
                    for row in actions
                    if row["tool_name"] == TOOL and row["result"].get("delivery") == "prepared"
                ),
                None,
            )
            if not prepared or prepared["phrase"] not in reply:
                return
            # Persistent receipts span sessions/restarts; failures also cool down.
            # A separate request namespace keeps retries from replaying a touch.
            with hub.store.database.connection() as db:
                recent = db.execute(
                    "SELECT created_at FROM agent_actions WHERE tool_name=? "
                    "AND request_id LIKE 'reply-haptic:%' ORDER BY rowid DESC LIMIT 1",
                    (VIBRATE,),
                ).fetchone()
            if (
                recent
                and (
                    datetime.now(UTC) - datetime.fromisoformat(recent["created_at"])
                ).total_seconds()
                < COOLDOWN_SECONDS
            ):
                return
            hub.invoke(
                VIBRATE,
                {"timings": list(HAPTIC_PATTERNS[0]), "repeat": -1},
                item.conversation_id,
                "reply-haptic:" + item.request_id,
                timeout=2,
            )
