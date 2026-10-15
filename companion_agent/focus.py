"""One persisted companion clock; elapsed time is never evidence of work completed."""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable
from datetime import datetime
from sqlite3 import Connection
from typing import Any, Literal
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from pydantic import Field, field_validator

from companion_agent.persona.models import PersonaModel
from companion_memoryos.database import Database

Phase = Literal["focus", "focus_paused", "focus_done", "rest", "rest_paused", "done", "ended"]
CLOSED = {"focus_done", "done", "ended"}


def conflict(message: str) -> HTTPException:
    return HTTPException(409, detail={"code": "focus_conflict", "message": message})


class FocusStart(PersonaModel):
    request_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    conversation_id: str = Field(min_length=1, max_length=128)
    intention: str = Field(default="", max_length=160)
    focus_minutes: int = Field(default=30, ge=1, le=120, strict=True)
    rest_minutes: int = Field(default=5, ge=1, le=60, strict=True)

    @field_validator("intention")
    @classmethod
    def trim_intention(cls, value: str) -> str:
        return value.strip()


class FocusAction(PersonaModel):
    session_id: str = Field(min_length=1, max_length=128)
    revision: int = Field(ge=0, strict=True)
    action: Literal["pause", "resume", "rest", "extend", "finish"]


class FocusNotice(PersonaModel):
    session_id: str = Field(min_length=1, max_length=128)
    revision: int = Field(ge=0, strict=True)


class FocusEvent(PersonaModel):
    action: str
    at: float
    elapsed_seconds: float


class FocusSession(PersonaModel):
    id: str
    conversation_id: str
    intention: str
    focus_minutes: int
    rest_minutes: int
    phase: Phase = "focus"
    remaining_seconds: float
    deadline: float | None
    started_at: float
    # Backward compatible name: the timer's deadline, NOT task completion.
    completed_at: float | None = None
    ended_at: float | None = None
    elapsed_seconds: float = 0
    running_since: float | None = None
    events: list[FocusEvent] = Field(default_factory=list)
    notice_revision: int = -1
    revision: int = 0


class FocusClock:
    def __init__(
        self, database: Database, scope: str, *, clock: Callable[[], float] = time.time
    ) -> None:
        self.database = database
        self.scope = scope
        self.clock = clock
        with database.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS romance_focus_sessions (
                    id TEXT PRIMARY KEY, scope TEXT NOT NULL,
                    phase TEXT NOT NULL, request_json TEXT NOT NULL, data_json TEXT NOT NULL
                );
                DROP INDEX IF EXISTS romance_focus_one_active;
                CREATE UNIQUE INDEX romance_focus_one_active
                ON romance_focus_sessions(scope)
                WHERE phase NOT IN ('focus_done', 'done', 'ended', 'erased');
            """)

    @staticmethod
    def _load(value: str) -> FocusSession:
        raw = json.loads(value)
        if "elapsed_seconds" not in raw:
            # Upgrade old clocks without inventing historical pause events.
            total = raw["focus_minutes"] * 60
            raw["elapsed_seconds"] = (
                total if raw.get("completed_at") else max(0, total - raw["remaining_seconds"])
            )
            if raw["phase"] == "focus" and raw["deadline"] is not None:
                raw["running_since"] = raw["deadline"] - raw["remaining_seconds"]
            if raw["phase"] in CLOSED:
                raw["ended_at"] = raw.get("completed_at")
        return FocusSession.model_validate(raw)

    def _latest(self, db: Connection) -> FocusSession | None:
        row = db.execute(
            "SELECT data_json FROM romance_focus_sessions WHERE scope=? AND phase!='erased' "
            "ORDER BY rowid DESC LIMIT 1",
            (self.scope,),
        ).fetchone()
        return self._load(row["data_json"]) if row else None

    def _save(self, db: Connection, session: FocusSession) -> None:
        db.execute(
            "UPDATE romance_focus_sessions SET phase=?, data_json=? WHERE id=? AND scope=?",
            (session.phase, session.model_dump_json(), session.id, self.scope),
        )

    @staticmethod
    def _elapsed(session: FocusSession, now: float) -> float:
        extra = 0.0
        if session.phase == "focus" and session.running_since is not None:
            extra = max(0, min(now, session.deadline or now) - session.running_since)
        return session.elapsed_seconds + extra

    @staticmethod
    def _event(session: FocusSession, action: str, now: float) -> None:
        session.events.append(
            FocusEvent(
                action=action,
                at=now,
                elapsed_seconds=session.elapsed_seconds,
            )
        )

    def _settle(self, db: Connection, session: FocusSession | None, now: float) -> None:
        if session is None or session.deadline is None or now < session.deadline:
            return
        deadline = session.deadline
        if session.phase == "focus":
            session.elapsed_seconds = self._elapsed(session, deadline)
            session.completed_at = deadline
            session.phase = "focus_done"
        elif session.phase == "rest":
            session.phase = "done"
        else:
            return
        session.ended_at = deadline
        session.remaining_seconds = 0
        session.deadline = session.running_since = None
        session.revision += 1
        self._event(session, "timer_elapsed", deadline)
        self._save(db, session)

    def _public(self, session: FocusSession, now: float) -> dict[str, Any]:
        result = session.model_dump(mode="json")
        result["elapsed_seconds"] = self._elapsed(session, now)
        if session.deadline is not None:
            result["remaining_seconds"] = max(0, math.ceil(session.deadline - now))
        return result

    def _snapshot(
        self, db: Connection, session: FocusSession | None, now: float, timezone: str
    ) -> dict[str, Any]:
        local = datetime.fromtimestamp(now, ZoneInfo(timezone))
        midnight = local.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        rows = db.execute(
            "SELECT data_json FROM romance_focus_sessions WHERE scope=? AND phase!='erased' "
            "ORDER BY rowid DESC LIMIT 100",
            (self.scope,),
        ).fetchall()
        history = [self._load(row["data_json"]) for row in rows]
        # Activity totals include early stops; they do not grade attention or task outcomes.
        today = [item for item in history if midnight <= item.started_at <= now]
        return {
            "session": self._public(session, now) if session else None,
            "server_now": now,
            "today": {
                "date": local.date().isoformat(),
                "count": len(today),
                "minutes": math.floor(sum(self._elapsed(item, now) for item in today) / 60),
            },
            "history": [self._public(item, now) for item in history[:20]],
        }

    def read(self, timezone: str) -> dict[str, Any]:
        with self.database.atomic() as db:
            now = self.clock()
            session = self._latest(db)
            self._settle(db, session, now)
            return self._snapshot(db, session, now, timezone)

    def start(self, item: FocusStart, timezone: str) -> dict[str, Any]:
        with self.database.atomic() as db:
            now = self.clock()
            session = self._latest(db)
            self._settle(db, session, now)
            previous = db.execute(
                "SELECT scope, request_json FROM romance_focus_sessions WHERE id=?",
                (item.request_id,),
            ).fetchone()
            if previous:
                if (
                    previous["scope"] != self.scope
                    or previous["request_json"] != item.model_dump_json()
                ):
                    raise conflict("这次开始请求已经使用过，请刷新后再试。")
                return self._snapshot(db, session, now, timezone)
            if session and session.phase not in CLOSED:
                raise conflict("已经有一段陪伴在计时，请先继续或结束它。")
            session = FocusSession(
                id=item.request_id,
                conversation_id=item.conversation_id,
                intention=item.intention,
                focus_minutes=item.focus_minutes,
                rest_minutes=item.rest_minutes,
                remaining_seconds=item.focus_minutes * 60,
                deadline=now + item.focus_minutes * 60,
                started_at=now,
                running_since=now,
            )
            self._event(session, "start", now)
            db.execute(
                "INSERT INTO romance_focus_sessions VALUES (?, ?, ?, ?, ?)",
                (
                    session.id,
                    self.scope,
                    session.phase,
                    item.model_dump_json(),
                    session.model_dump_json(),
                ),
            )
            return self._snapshot(db, session, now, timezone)

    def act(self, item: FocusAction, timezone: str) -> dict[str, Any]:
        # Persist elapsed deadlines even when the caller's revision is stale.
        self.read(timezone)
        with self.database.atomic() as db:
            now = self.clock()
            session = self._latest(db)
            if not session or session.id != item.session_id or session.revision != item.revision:
                raise conflict("计时状态已更新，请按当前状态操作。")
            if session.deadline is not None and now >= session.deadline:
                raise conflict("这一段刚刚到时，请刷新计时状态。")
            session.elapsed_seconds = self._elapsed(session, now)
            if session.phase == "focus":
                session.running_since = now
            if item.action == "pause" and session.phase in {"focus", "rest"}:
                assert session.deadline is not None
                session.remaining_seconds = max(0, session.deadline - now)
                session.deadline = session.running_since = None
                session.phase = "focus_paused" if session.phase == "focus" else "rest_paused"
            elif item.action == "resume" and session.phase in {"focus_paused", "rest_paused"}:
                session.deadline = now + session.remaining_seconds
                session.phase = "focus" if session.phase == "focus_paused" else "rest"
                session.running_since = now if session.phase == "focus" else None
            elif item.action == "rest" and session.phase == "focus_done":
                session.phase = "rest"
                session.remaining_seconds = session.rest_minutes * 60
                session.deadline = now + session.remaining_seconds
                session.ended_at = None
            elif item.action == "extend" and session.phase == "focus_done":
                session.phase = "focus"
                session.focus_minutes += 5
                session.remaining_seconds = 5 * 60
                session.deadline = now + session.remaining_seconds
                session.running_since = now
                session.completed_at = session.ended_at = None
            elif item.action == "finish" and session.phase not in {"done", "ended"}:
                if session.deadline is not None:
                    session.remaining_seconds = max(0, session.deadline - now)
                session.phase = "ended"
                session.deadline = session.running_since = None
                session.ended_at = now
            else:
                raise conflict("当前阶段不能这样操作，请按最新状态操作。")
            session.revision += 1
            self._event(session, item.action, now)
            self._save(db, session)
            return self._snapshot(db, session, now, timezone)

    def claim_notice(self, item: FocusNotice, timezone: str) -> bool:
        self.read(timezone)
        with self.database.atomic() as db:
            session = self._latest(db)
            if (
                not session
                or session.id != item.session_id
                or session.revision != item.revision
                or session.phase not in {"focus_done", "done"}
                or session.notice_revision == session.revision
                or self.clock() - (session.ended_at or 0) > 120
            ):
                return False
            session.notice_revision = session.revision
            self._save(db, session)
            return True

    def quiet(self) -> bool:
        with self.database.atomic() as db:
            session = self._latest(db)
            self._settle(db, session, self.clock())
            return bool(session and session.phase in {"focus", "focus_paused"})

    def context(self) -> str:
        with self.database.atomic() as db:
            session = self._latest(db)
            self._settle(db, session, self.clock())
            phase = session.phase if session else "none"
            timing = (
                f" started_at={session.started_at}; deadline={session.deadline}; "
                f"ended_at={session.ended_at}."
                if session
                else ""
            )
        return (
            "\n[APPLICATION FOCUS CLOCK]\n"
            f"当前计时状态={phase}.{timing} 时间为 Unix 秒。"
            "只有 focus/rest 正在计时；focus_paused/rest_paused 已暂停；"
            "focus_done/done/ended 均已停止，不能再说正在陪用户做旧任务。"
            "计时只证明启动、暂停、流逝和结束，不证明专注程度或任务完成。"
            "任务进展必须来自用户明确自述。用户主动聊天时正常回应，不查岗、"
            "不默认鼓励或追问完成比例，不因暂停结束改变亲密度。"
            "网页关闭或手机系统挂起时无法保证到时通知，不作未经确认的提醒承诺。"
        )

    def clear_history(self) -> None:
        with self.database.atomic() as db:
            self._settle(db, self._latest(db), self.clock())
            db.execute(
                "UPDATE romance_focus_sessions SET phase='erased', request_json='', data_json='{}' "
                "WHERE scope=? AND phase IN ('focus_done', 'done', 'ended')",
                (self.scope,),
            )

    def export(self) -> list[dict[str, Any]]:
        with self.database.atomic() as db:
            self._settle(db, self._latest(db), self.clock())
            rows = db.execute(
                "SELECT data_json FROM romance_focus_sessions "
                "WHERE scope=? AND phase!='erased' ORDER BY rowid",
                (self.scope,),
            ).fetchall()
        return [self._public(self._load(row["data_json"]), self.clock()) for row in rows]
