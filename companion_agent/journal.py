"""User-curated journal over the existing memory, turn and open-loop ledgers."""

from __future__ import annotations

import calendar
import hashlib
import json
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING, Annotated, Any, Literal
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Query
from fastapi.responses import JSONResponse
from pydantic import Field, field_validator

from companion_agent.evidence_policy import filter_recent_turns
from companion_agent.persona.models import PersonaModel
from companion_memoryos.schemas import (
    ConsentState,
    ConversationRole,
    ConversationTurnInput,
    ConversationTurnRecord,
    ExperienceEvidenceKind,
    ExperienceEvidenceRef,
    FollowUpMode,
    MemoryInput,
    MemoryKind,
    MemoryRecord,
    MemoryReferenceMode,
    MemoryStatus,
    MemoryUseDecision,
    MemoryUsePlan,
    OpenLoopInput,
    OpenLoopKind,
    RealityLayer,
    RetentionClass,
    TurnDeletionState,
)

if TYPE_CHECKING:
    from companion_agent.app import RomanceHost

Category = Literal["self", "companion", "together", "promises"]


class JournalError(ValueError):
    """Known, user-facing journal validation error; never contains model diagnostics."""


class JournalFlags(PersonaModel):
    category: Category
    important: bool = False


class MomentInput(PersonaModel):
    request_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    conversation_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=80)
    content: str = Field(min_length=1, max_length=2000)
    happened_on: date
    reality_layer: Literal["real_world", "roleplay"] = "real_world"
    source_ids: list[str] = Field(default_factory=list, max_length=8)
    image_ids: list[str] = Field(default_factory=list, max_length=4)

    @field_validator("title", "content")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise JournalError("请填写回忆标题和内容。")
        return value.strip()


class JournalEventInput(PersonaModel):
    request_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    conversation_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=80)
    note: str = Field(default="", max_length=500)
    kind: Literal["anniversary", "appointment"] = "appointment"
    event_date: date
    at: str = Field(default="09:00", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    yearly: bool = False
    mode: Literal["none", "reminder", "checkin"] = "reminder"
    timezone: str = "Asia/Shanghai"

    @field_validator("title")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise JournalError("请填写标题。")
        return value.strip()

    @field_validator("timezone")
    @classmethod
    def zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ValueError, KeyError):
            raise JournalError("时区无效。") from None
        return value


def occurrence(day: date, at: str, zone: str, yearly: bool, now: datetime) -> datetime:
    """Gregorian anniversaries clamp leap day to Feb 28 in common years."""
    tz = ZoneInfo(zone)
    year = max(day.year, now.astimezone(tz).year) if yearly else day.year
    while True:
        actual = date(year, day.month, min(day.day, calendar.monthrange(year, day.month)[1]))
        result = datetime.combine(actual, time.fromisoformat(at), tz).astimezone(UTC)
        if not yearly or result >= now:
            return result
        year += 1


class Journal:
    def __init__(self, host: RomanceHost) -> None:
        self.host = host
        with host.database.connection() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS journal_event_details ("
                "id TEXT PRIMARY KEY REFERENCES agent_events(id) ON DELETE CASCADE, "
                "data_json TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1)"
            )
            cleanup = (
                "DELETE FROM journal_event_details WHERE id IN "
                "(SELECT id FROM agent_events WHERE source_turn=OLD.id); "
                "UPDATE agent_events SET summary='',status='invalidated',due_at=NULL,"
                "reason='source_unavailable' WHERE source_turn=OLD.id; "
            )
            db.execute(
                "CREATE TRIGGER IF NOT EXISTS journal_event_forget AFTER UPDATE ON "
                "conversation_turns WHEN NEW.deletion_state!='active' OR NEW.consent!='granted' "
                "OR json_extract(NEW.metadata_json,'$.content_redacted_at') IS NOT NULL "
                "BEGIN " + cleanup + " END"
            )
            db.execute(
                "CREATE TRIGGER IF NOT EXISTS journal_event_purge AFTER DELETE ON "
                "conversation_turns BEGIN " + cleanup + " END"
            )

    def require_storage(self) -> None:
        if not self.host.settings.storage_consent:
            raise JournalError("请先在设置中允许本地保存。")

    def require_turn(
        self,
        identifier: str,
        conversation: str | None = None,
        *,
        for_model: bool = False,
    ) -> ConversationTurnRecord:
        host = self.host
        try:
            turn = host.memory.store.get_turn(identifier, host.key.user_id)
        except KeyError:
            raise JournalError("原消息已不可用。") from None
        if (
            turn.scope.companion_id != host.key.companion_id
            or turn.scope.relationship_id != host.key.relationship_id
            or turn.scope.group_id is not None
            or (conversation is not None and turn.scope.conversation_id != conversation)
            or turn.consent is not ConsentState.GRANTED
            or turn.deletion_state is not TurnDeletionState.ACTIVE
            or turn.metadata.get("content_redacted_at")
        ):
            raise JournalError("原消息已不可用。")
        if for_model and not filter_recent_turns(
            host.memory,
            host.key,
            [turn],
            MemoryUsePlan(),
            datetime.now(UTC),
        ):
            raise JournalError("这条消息当前不允许用于模型引用。")
        return turn

    def quote(self, turn: ConversationTurnRecord) -> dict[str, Any] | None:
        if turn.role is not ConversationRole.USER or not turn.reply_to_turn_id:
            return None
        try:
            source = self.require_turn(turn.reply_to_turn_id, turn.scope.conversation_id)
            return {
                "id": source.id,
                "content": source.content[:300],
                "role": source.role.value,
                "available": True,
            }
        except ValueError:
            return {
                "id": turn.reply_to_turn_id,
                "content": "原消息已不可用",
                "role": "user",
                "available": False,
            }

    def require_memory(self, identifier: str) -> MemoryRecord:
        try:
            record = self.host.memory.store.get(identifier, self.host.key.user_id)
        except KeyError:
            raise JournalError("这条记忆已不可用。") from None
        if (
            record.scope.companion_id != self.host.key.companion_id
            or record.scope.relationship_id != self.host.key.relationship_id
            or record.scope.group_id is not None
            or record.status is not MemoryStatus.ACTIVE
            or record.consent is not ConsentState.GRANTED
            or (record.expires_at and record.expires_at <= datetime.now(UTC))
        ):
            raise JournalError("这条记忆已不可用。")
        for source in record.evidence_turn_ids:
            self.require_turn(source)
        return record

    def entry(self, record: MemoryRecord) -> dict[str, Any]:
        category = record.metadata.get("journal_category")
        if category not in {"self", "companion", "together", "promises"}:
            category = (
                "promises"
                if record.kind in {MemoryKind.COMMITMENT, MemoryKind.RITUAL}
                else "companion"
                if record.subject_actor_id == self.host.key.companion_id
                else "together"
                if record.kind in {MemoryKind.SHARED_MOMENT, MemoryKind.RELATIONSHIP}
                else "self"
            )
        sources = [self.require_turn(i) for i in record.evidence_turn_ids]
        images = []
        for identifier in record.metadata.get("journal_images", []):
            with self.host.database.connection() as db:
                if db.execute("SELECT 1 FROM romance_images WHERE id=?", (identifier,)).fetchone():
                    images.append(identifier)
        return {
            **record.model_dump(mode="json"),
            "category": category,
            "important": bool(record.metadata.get("journal_important")),
            "happened_on": record.metadata.get("journal_date", record.event_at.date().isoformat()),
            "image_ids": images,
            "sources": [
                {
                    "id": t.id,
                    "conversation_id": t.scope.conversation_id,
                    "role": t.role.value,
                    "excerpt": t.content[:160],
                }
                for t in sources
            ],
        }

    def entries(self, *, moments: bool, category: str, offset: int, limit: int) -> dict[str, Any]:
        self.require_storage()
        host = self.host
        clause = "AND json_extract(metadata_json,'$.journal_moment')=1 " if moments else ""
        with host.database.connection() as db:
            rows = db.execute(
                "SELECT * FROM memories WHERE user_id=? AND companion_id=? AND relationship_id=? "
                "AND group_id IS NULL AND status='active' AND consent='granted' "
                + clause
                + "ORDER BY COALESCE(json_extract(metadata_json,'$.journal_important'),0) DESC, "
                "COALESCE(json_extract(metadata_json,'$.journal_date'),event_at) DESC, id DESC",
                host.key.values,
            ).fetchall()
        eligible = []
        for row in rows:
            try:
                record = self.require_memory(row["id"])
                entry = self.entry(record)
            except (ValueError, KeyError):
                continue
            if category == "all" or entry["category"] == category:
                eligible.append(entry)
        return {
            "items": eligible[offset : offset + limit],
            "has_more": len(eligible) > offset + limit,
            "total": len(eligible),
            "offset": offset + limit,
        }

    def flags(self, identifier: str, flags: JournalFlags) -> dict[str, Any]:
        self.require_storage()
        record = self.require_memory(identifier)
        metadata = {
            **record.metadata,
            "journal_category": flags.category,
            "journal_important": flags.important,
        }
        original = metadata.setdefault("journal_original_salience", record.salience)
        with self.host.database.connection() as db:
            db.execute(
                "UPDATE memories SET metadata_json=?,salience=? WHERE id=? AND user_id=?",
                (
                    json.dumps(metadata, ensure_ascii=False),
                    1.0 if flags.important else original,
                    identifier,
                    self.host.key.user_id,
                ),
            )
        return self.entry(self.require_memory(identifier))

    def moment(self, item: MomentInput) -> dict[str, Any]:
        self.require_storage()
        host = self.host
        scope = host.scope(item.conversation_id)
        if item.happened_on > datetime.now(ZoneInfo(host.settings.calendar_timezone)).date():
            raise JournalError("回忆日期不能在未来，未来的事可以记为约定。")
        with host.database.atomic() as db:
            stable = "journal:moment:" + item.request_id
            existing = db.execute(
                "SELECT id,metadata_json FROM memories WHERE user_id=? AND stable_key=? "
                "ORDER BY created_at DESC LIMIT 1",
                (host.key.user_id, stable),
            ).fetchone()
            if existing:
                if (
                    json.loads(existing["metadata_json"]).get("journal_input_hash")
                    != hashlib.sha256(item.model_dump_json().encode()).hexdigest()
                ):
                    raise JournalError("此保存请求已使用，请刷新后再试。")
                return self.entry(self.require_memory(existing["id"]))
            sources = [
                self.require_turn(i, item.conversation_id) for i in dict.fromkeys(item.source_ids)
            ]
            attached = {i for t in sources for i in host.images.ids(t)}
            for image in item.image_ids:
                if image not in attached:
                    host.images.require(image, "moment")
                    if db.execute(
                        "SELECT 1 FROM memories,json_each(metadata_json,'$.journal_images') "
                        "WHERE value=?",
                        (image,),
                    ).fetchone():
                        raise JournalError("图片已属于另一段回忆，请重新选择。")
            source = host.memory.append_turn(
                ConversationTurnInput(
                    user_id=host.key.user_id,
                    scope=scope,
                    actor_id=host.key.user_id,
                    role=ConversationRole.USER,
                    content="记下一段共同回忆：" + item.title + "\n" + item.content,
                    consent=ConsentState.GRANTED,
                    source_ref="journal:moment",
                    idempotency_key=stable,
                    metadata={"reality_layer": item.reality_layer},
                )
            ).turn
            assert source is not None
            result = host.memory.remember(
                MemoryInput(
                    user_id=host.key.user_id,
                    scope=scope.model_copy(update={"conversation_id": None}),
                    kind=MemoryKind.SHARED_MOMENT,
                    title=item.title,
                    content=item.content,
                    stable_key=stable,
                    consent=ConsentState.GRANTED,
                    explicit_user_request=True,
                    retention=RetentionClass.DURABLE,
                    reality_layer=RealityLayer(item.reality_layer),
                    source_ref="journal:moment",
                    evidence_turn_ids=[source.id, *[t.id for t in sources]],
                    event_at=datetime.combine(
                        item.happened_on, time(12), ZoneInfo(host.settings.calendar_timezone)
                    ),
                    metadata={
                        "journal_moment": True,
                        "journal_category": "together",
                        "journal_date": item.happened_on.isoformat(),
                        "journal_images": list(dict.fromkeys(item.image_ids)),
                        "journal_input_hash": hashlib.sha256(
                            item.model_dump_json().encode()
                        ).hexdigest(),
                    },
                )
            )
            if result.memory is None or result.memory.status is not MemoryStatus.ACTIVE:
                raise JournalError("回忆未能保存，请检查来源和内容。")
            return self.entry(result.memory)

    def events(self) -> list[dict[str, Any]]:
        host = self.host
        if not host.settings.storage_consent:
            return []
        with host.database.connection() as db:
            rows = db.execute(
                "SELECT e.*,d.data_json,d.revision FROM agent_events e "
                "LEFT JOIN journal_event_details d ON e.id=d.id "
                "ORDER BY COALESCE(e.due_at,'9999') ASC, e.rowid DESC",
            ).fetchall()
        result = []
        for row in rows:
            try:
                self.require_turn(row["source_turn"], row["conversation_id"])
            except ValueError:
                continue
            data = (
                json.loads(row["data_json"])
                if row["data_json"]
                else {
                    "title": row["summary"],
                    "kind": "appointment",
                    "mode": "none",
                    "note": "从聊天中记下的事项，可编辑日期与提醒方式。",
                    "yearly": False,
                    "timezone": host.settings.calendar_timezone,
                }
            )
            extra: dict[str, Any] = {}
            if row["due_at"]:
                local_due = datetime.fromisoformat(row["due_at"]).astimezone(
                    ZoneInfo(data["timezone"])
                )
                extra = {
                    "next_local": local_due.strftime("%Y-%m-%d %H:%M"),
                    "days_until": (
                        local_due.date() - datetime.now(ZoneInfo(data["timezone"])).date()
                    ).days,
                }
            values = dict(row)
            values.pop("data_json")
            result.append({**data, **values, **extra})
        return result

    def event(self, item: JournalEventInput, identifier: str | None = None) -> dict[str, Any]:
        self.require_storage()
        host = self.host
        scope = host.scope(item.conversation_id)
        now = datetime.now(UTC)
        due = occurrence(item.event_date, item.at, item.timezone, item.yearly, now)
        if item.mode != "none" and due < now - timedelta(minutes=1):
            raise JournalError("提醒时间已经过去，请选未来时间或改为仅记录。")
        eid = identifier or "journal:" + item.request_id
        with host.database.atomic() as db:
            previous = next((e for e in self.events() if e["id"] == eid), None)
            if previous:
                saved = db.execute(
                    "SELECT data_json FROM journal_event_details WHERE id=?", (eid,)
                ).fetchone()
                if saved and json.loads(saved[0]) == item.model_dump(mode="json"):
                    return previous
                if not identifier:
                    raise JournalError("此保存请求已使用，请刷新后再试。")
            if identifier and (
                previous is None or previous["status"] in {"cancelled", "resolved", "invalidated"}
            ):
                raise JournalError("这件事已关闭或不可用。")
            if previous and previous["conversation_id"] != item.conversation_id:
                raise JournalError("不能更换约定所属对话。")
            source = host.memory.append_turn(
                ConversationTurnInput(
                    user_id=host.key.user_id,
                    scope=scope,
                    actor_id=host.key.user_id,
                    role=ConversationRole.USER,
                    consent=ConsentState.GRANTED,
                    content=f"手账记录：{item.title}\n"
                    f"日期：{item.event_date.isoformat()} {item.at}"
                    f"（{item.timezone}）"
                    + ("，每年重复" if item.yearly else "")
                    + "\n"
                    + item.note,
                    source_ref="journal:event",
                    idempotency_key="journal:event:" + item.request_id,
                )
            ).turn
            assert source is not None
            if previous:
                host.continuity.change(eid, "cancelled", source_turn=source.id)
            loop = host.memory.create_open_loop(
                OpenLoopInput(
                    user_id=host.key.user_id,
                    scope=scope,
                    kind=OpenLoopKind.EVENT_OUTCOME,
                    summary=item.title,
                    source_turn_id=source.id,
                    consent=ConsentState.GRANTED,
                    follow_up_mode=FollowUpMode.USER_LED,
                    metadata={"application_event": eid},
                )
            ).open_loop
            if loop is None:
                raise JournalError("约定未能保存。")
            db.execute(
                "INSERT INTO agent_events (id,conversation_id,source_turn,loop_id,summary,"
                "due_at,status,delivered_at,reason) "
                "VALUES (?,?,?,?,?,?,'scheduled',NULL,'') ON CONFLICT(id) DO UPDATE SET "
                "source_turn=excluded.source_turn,loop_id=excluded.loop_id,summary=excluded.summary,"
                "due_at=excluded.due_at,status='scheduled',delivered_at=NULL,reason=''",
                (eid, item.conversation_id, source.id, loop.id, item.title, due.isoformat()),
            )
            db.execute(
                "INSERT INTO journal_event_details VALUES (?,?,1) ON CONFLICT(id) DO UPDATE SET "
                "data_json=excluded.data_json,revision=journal_event_details.revision+1",
                (eid, item.model_dump_json()),
            )
            if item.mode == "none":
                db.execute("UPDATE agent_events SET status='candidate' WHERE id=?", (eid,))
        return next(e for e in self.events() if e["id"] == eid)

    def event_valid(self, turn: ConversationTurnRecord) -> bool:
        eid = turn.metadata.get("journal_event_id")
        if not eid:
            return True
        return any(
            e["id"] == eid
            and e["revision"] == turn.metadata.get("journal_event_revision")
            and e["status"] not in {"cancelled", "resolved", "invalidated"}
            for e in self.events()
        )

    def pending(self, mode: str, now: datetime | None = None) -> list[dict[str, Any]]:
        result = [e for e in self.events() if e["mode"] == mode and e["status"] == "scheduled"]
        if now is not None:
            result = [
                e for e in result if e["due_at"] and datetime.fromisoformat(e["due_at"]) <= now
            ]
        return result

    def filter_proactive(
        self,
        turns: list[ConversationTurnRecord],
        plan: MemoryUsePlan,
        now: datetime,
    ) -> list[ConversationTurnRecord]:
        # Closed/replaced manual event notes are history, not a current reason to
        # contact the user. Reference filtering also checks dependent replies.
        with self.host.database.connection() as db:
            hidden = [
                row[0]
                for row in db.execute(
                    "SELECT t.id FROM conversation_turns t LEFT JOIN agent_events e "
                    "ON e.source_turn=t.id WHERE t.user_id=? AND "
                    "(t.source_ref='journal:event_update' OR (t.source_ref='journal:event' "
                    "AND (e.id IS NULL OR e.status IN ('cancelled','resolved','invalidated'))))",
                    (self.host.key.user_id,),
                )
            ]
        augmented = plan.model_copy(
            update={
                "decisions": [
                    *plan.decisions,
                    *[
                        MemoryUseDecision(
                            evidence=ExperienceEvidenceRef(kind=ExperienceEvidenceKind.TURN, id=i),
                            mode=MemoryReferenceMode.SUPPRESS,
                            reasons=["closed_journal_event"],
                        )
                        for i in hidden
                    ],
                ]
            }
        )
        return filter_recent_turns(self.host.memory, self.host.key, turns, augmented, now)

    def close_event(self, identifier: str, status: str) -> None:
        self.require_storage()
        event = next((e for e in self.events() if e["id"] == identifier), None)
        if event is None or status not in {"cancelled", "resolved"}:
            raise JournalError("这件事已不可用。")
        if event["status"] == status:
            return
        host = self.host
        with host.database.atomic():
            source = host.memory.append_turn(
                ConversationTurnInput(
                    user_id=host.key.user_id,
                    scope=host.scope(event["conversation_id"]),
                    actor_id=host.key.user_id,
                    role=ConversationRole.USER,
                    consent=ConsentState.GRANTED,
                    source_ref="journal:event_update",
                    content=("已取消约定：" if status == "cancelled" else "已完成约定：")
                    + event["title"],
                    idempotency_key=f"journal:close:{identifier}:{event.get('revision')}:{status}",
                )
            ).turn
            assert source is not None
            host.continuity.change(identifier, status, source_turn=source.id)

    def complete_occurrence(self, event: dict[str, Any], now: datetime, reason: str = "") -> None:
        due = None
        if event["yearly"]:
            due = occurrence(
                date.fromisoformat(event["event_date"]),
                event["at"],
                event["timezone"],
                True,
                now + timedelta(seconds=1),
            ).isoformat()
        with self.host.database.connection() as db:
            db.execute(
                "UPDATE agent_events SET status=?,due_at=COALESCE(?,due_at),"
                "delivered_at=?,reason=? WHERE id=?",
                ("scheduled" if due else "waiting", due, now.isoformat(), reason, event["id"]),
            )

    def tick_reminders(self, now: datetime | None = None) -> None:
        if not self.host.lock.acquire(blocking=False):
            return
        try:
            self._tick_reminders(now or datetime.now(UTC))
        finally:
            self.host.lock.release()

    def _tick_reminders(self, now: datetime) -> None:
        host = self.host
        if not host.settings.storage_consent or host.outreach.quiet(now):
            return
        for event in self.pending("reminder", now)[:3]:
            if now - datetime.fromisoformat(event["due_at"]) > timedelta(days=1):
                self.complete_occurrence(event, now, "missed")
                continue
            with host.database.atomic() as db:
                source = self.require_turn(event["source_turn"], event["conversation_id"])
                turn = host.memory.append_turn(
                    ConversationTurnInput(
                        user_id=host.key.user_id,
                        scope=source.scope,
                        actor_id="journal",
                        role=ConversationRole.SYSTEM,
                        consent=ConsentState.GRANTED,
                        occurred_at=now,
                        content="约定提醒："
                        + event["title"]
                        + "\n"
                        + datetime.fromisoformat(event["due_at"])
                        .astimezone(ZoneInfo(event["timezone"]))
                        .strftime("%Y-%m-%d %H:%M")
                        + ("\n" + event["note"] if event["note"] else ""),
                        idempotency_key=f"journal:reminder:{event['id']}:{event['revision']}:{event['due_at']}",
                        reply_to_turn_id=source.id,
                        source_ref="journal:reminder",
                        metadata={
                            "journal_reminder": True,
                            "journal_event_id": event["id"],
                            "journal_event_revision": event["revision"],
                            "context_turn_ids": [source.id],
                        },
                    )
                ).turn
                assert turn is not None
                db.execute("INSERT OR IGNORE INTO romance_outreach(turn_id) VALUES (?)", (turn.id,))
                db.execute(
                    "UPDATE romance_conversations SET updated_at=? WHERE id=?",
                    (now.isoformat(), event["conversation_id"]),
                )
                self.complete_occurrence(event, now)


def install_routes(app: FastAPI, host: RomanceHost, authorized: Callable[..., Any]) -> None:
    dependencies = [Depends(authorized)]

    @app.exception_handler(JournalError)
    async def journal_error(request: Any, error: JournalError) -> JSONResponse:
        return JSONResponse(
            {"detail": {"message": str(error), "code": "journal_unavailable"}}, status_code=422
        )

    @app.get("/api/journal/entries", dependencies=dependencies)
    def entries(
        moments: bool = False,
        category: Literal["all", "self", "companion", "together", "promises"] = "all",
        offset: Annotated[int, Query(ge=0, le=100000)] = 0,
        limit: Annotated[int, Query(ge=1, le=100)] = 40,
    ) -> dict[str, Any]:
        with host.lock:
            return host.journal.entries(
                moments=moments, category=category, offset=offset, limit=limit
            )

    @app.put("/api/journal/entries/{identifier}/flags", dependencies=dependencies)
    def flags(identifier: str, item: JournalFlags) -> dict[str, Any]:
        with host.exclusive():
            return host.journal.flags(identifier, item)

    @app.post("/api/journal/moments", dependencies=dependencies)
    def moment(item: MomentInput) -> dict[str, Any]:
        with host.exclusive():
            return host.journal.moment(item)

    @app.get("/api/journal/events", dependencies=dependencies)
    def events() -> dict[str, Any]:
        with host.lock:
            return {"items": host.journal.events()}

    @app.post("/api/journal/events", dependencies=dependencies)
    def create_event(item: JournalEventInput) -> dict[str, Any]:
        with host.exclusive():
            return host.journal.event(item)

    @app.put("/api/journal/events/{identifier}", dependencies=dependencies)
    def edit_event(identifier: str, item: JournalEventInput) -> dict[str, Any]:
        with host.exclusive():
            return host.journal.event(item, identifier)
