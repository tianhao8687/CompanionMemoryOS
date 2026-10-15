"""Chat/UI bridges to the existing evidence-backed memory store and shared clock."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

from pydantic import Field

from companion_agent.communication import project_preferences
from companion_agent.focus import CLOSED, FocusAction
from companion_agent.persona.models import PersonaModel
from companion_memoryos.discourse import direct_clauses
from companion_memoryos.schemas import (
    ConsentState,
    ConversationRole,
    ConversationTurnInput,
    ConversationTurnRecord,
    EpistemicKind,
    MemoryInput,
    MemoryKind,
    MemoryStatus,
    ReviewDecision,
    TurnDeletionState,
)

if TYPE_CHECKING:
    from companion_agent.app import ChatInput, RomanceHost


def proposal(text: str) -> dict[str, Any] | None:
    clauses = direct_clauses(text)
    direct = "，".join(clauses)
    # A conservative command grammar: hypothetical, quoted, deferred and reported speech
    # remain ordinary chat. Starting always requires the editable confirmation card.
    if re.search(
        r"如果|假如|明天|后天|以后|下次|他说|她说|你说|我说|不要|别陪|不想|翻译|例如", text
    ):
        return None
    request = re.search(
        r"(?:你)?陪我(?:专注|一起|半(?:个)?小时|\d|[一二两三四五六七八九十])", direct
    )
    if not request:
        return None
    requested = direct[request.start() :]
    duration = re.search(r"(?<!\d)(\d+|[一二两三四五六七八九十百]+)\s*分钟", requested)
    hours = re.search(r"(\d+|[一二两三四五六七八九十])(?:个)?(半)?小时|半(?:个)?小时", requested)
    minutes = 30
    if duration:
        number = duration.group(1)
        if number.isdigit():
            minutes = int(number)
        else:
            digits = dict(zip("一二两三四五六七八九", [1, 2, 2, 3, 4, 5, 6, 7, 8, 9], strict=True))
            if "百" in number:
                return None
            if "十" in number:
                tens, units = number.split("十", 1)
                minutes = digits.get(tens, 1) * 10 + digits.get(units, 0)
            else:
                minutes = digits.get(number, 0)
    elif hours:
        number = hours.group(1)
        if number is None:
            minutes = 30
        else:
            count = int(number) if number.isdigit() else {"一": 1, "二": 2, "两": 2}.get(number, 3)
            minutes = count * 60 + (30 if hours.group(2) else 0)
    elif re.search(r"\d|分钟|小时|秒", requested):
        return None
    if not 1 <= minutes <= 120:
        return None
    task = ""
    for clause in clauses:
        if "陪我" in clause:
            continue
        cleaned = re.sub(r"^我(?:得|要|想|准备|打算|需要)(?:先)?", "", clause)
        match = re.fullmatch(r"把(.+?)(整理|写|读|看|做)(?:一下|完|好)?", cleaned)
        if match:
            cleaned = match[2] + match[1]
        cleaned = re.sub(r"(?:一下|一会儿|一会)$", "", cleaned)
        if cleaned != clause or re.match(r"整理|写|读|做|看", cleaned):
            task = cleaned.strip("，。！!?？ ")[:160]
            break
    return {"intention": task, "focus_minutes": minutes, "rest_minutes": 5}


class FocusPreferenceInput(PersonaModel):
    request_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    conversation_id: str = Field(min_length=1, max_length=128)
    dimension: Literal["focus_sound", "focus_notice"]
    value: Literal["silent", "rain", "once", "off"]


class FocusProgressInput(PersonaModel):
    request_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    session_id: str = Field(min_length=1, max_length=128)
    content: str = Field(min_length=1, max_length=500)


class FocusCompanion:
    def __init__(self, host: RomanceHost) -> None:
        self.host = host

    def _existing_source(
        self, conversation: str, key: str, content: str, ref: str
    ) -> ConversationTurnRecord | None:
        host = self.host
        scope = host.scope(conversation)
        with host.database.connection() as db:
            row = db.execute(
                "SELECT id FROM conversation_turns WHERE user_id=? AND companion_id=? "
                "AND relationship_id=? AND conversation_id=? AND group_id IS NULL "
                "AND idempotency_key=?",
                (
                    host.key.user_id,
                    host.key.companion_id,
                    host.key.relationship_id,
                    conversation,
                    key,
                ),
            ).fetchone()
        if not row:
            return None
        source = host.memory.store.get_turn(row["id"], host.key.user_id)
        if (
            source.content != content
            or source.source_ref != ref
            or source.scope != scope
            or source.deletion_state is not TurnDeletionState.ACTIVE
        ):
            raise ValueError("focus request was changed or its source was removed")
        return source

    def preferences(self, conversation_id: str) -> dict[str, str]:
        host = self.host
        entries = project_preferences(
            host.memory,
            host.agent.relationships,
            host.key,
            host.scope(conversation_id),
            datetime.now(UTC),
        )
        values = {"focus_sound": "silent", "focus_notice": "once"}
        values.update({s["dimension"]: s["value"] for s in entries if s["dimension"] in values})
        return values

    def save_preference(self, item: FocusPreferenceInput) -> None:
        phrases = {
            ("focus_sound", "silent"): "专注的时候别放音乐",
            ("focus_sound", "rain"): "专注的时候放雨声",
            ("focus_notice", "once"): "专注到时间提醒一次就行",
            ("focus_notice", "off"): "专注到时间不用提醒",
        }
        phrase = phrases.get((item.dimension, item.value))
        if phrase is None:
            raise ValueError("invalid focus preference")
        host = self.host
        with host.database.atomic():
            if self._existing_source(
                item.conversation_id, "focus_pref:" + item.request_id, phrase, "focus:preference"
            ):
                return
            source = host.memory.append_turn(
                ConversationTurnInput(
                    user_id=host.key.user_id,
                    scope=host.scope(item.conversation_id),
                    role=ConversationRole.USER,
                    actor_id=host.key.user_id,
                    content=phrase,
                    consent=ConsentState.GRANTED,
                    idempotency_key="focus_pref:" + item.request_id,
                    source_ref="focus:preference",
                )
            ).turn
            assert source is not None
            decision = host.memory.remember(
                MemoryInput(
                    user_id=source.user_id,
                    scope=source.scope.model_copy(update={"conversation_id": None}),
                    kind=MemoryKind.PREFERENCE,
                    title="专注时的相处偏好",
                    content=phrase,
                    stable_key="natural:"
                    + hashlib.sha256(("communication:" + item.dimension).encode()).hexdigest()[:24],
                    consent=ConsentState.GRANTED,
                    explicit_user_request=True,
                    event_at=source.occurred_at,
                    evidence_turn_ids=[source.id],
                    source_ref=f"turn:{source.id}",
                    source_excerpt=phrase,
                    metadata={
                        "subject": "communication:" + item.dimension,
                        "behavior_lifetime": "durable",
                    },
                )
            )
            if decision.memory and decision.memory.status is MemoryStatus.CANDIDATE:
                host.memory.review(decision.memory.id, source.user_id, ReviewDecision.CONFIRM)

    def save_progress(self, item: FocusProgressInput) -> dict[str, Any]:
        from companion_agent.app import problem

        host = self.host
        if not item.content.strip():
            raise problem(422, "empty_progress", "写下你想留住的进展。")
        session = next((s for s in host.focus.export() if s["id"] == item.session_id), None)
        if session is None:
            raise problem(404, "focus_missing", "找不到这段陪伴。")
        if session["phase"] not in CLOSED:
            raise problem(409, "focus_running", "结束计时后可以留下进展，现在也可以直接聊天。")
        with host.database.atomic():
            ref = "focus:user_report:" + item.session_id
            existing = self._existing_source(
                session["conversation_id"],
                "focus_progress:" + item.request_id,
                item.content.strip(),
                ref,
            )
            if existing:
                memories = host.memory.store.list_memories(host.key.user_id, {MemoryStatus.ACTIVE})
                previous = next(
                    (m for m in memories if m.stable_key == "focus_progress:" + existing.id), None
                )
                if previous is None:
                    raise problem(409, "progress_removed", "这条进展已修改或遗忘，不会重新写入。")
                return {"saved": True, "memory_id": previous.id}
            source = host.memory.append_turn(
                ConversationTurnInput(
                    user_id=host.key.user_id,
                    scope=host.scope(session["conversation_id"]),
                    role=ConversationRole.USER,
                    actor_id=host.key.user_id,
                    content=item.content.strip(),
                    consent=ConsentState.GRANTED,
                    idempotency_key="focus_progress:" + item.request_id,
                    source_ref=ref,
                )
            ).turn
            assert source is not None
            result = host.memory.remember(
                MemoryInput(
                    user_id=source.user_id,
                    scope=source.scope,
                    kind=MemoryKind.SHARED_MOMENT,
                    title="这次陪伴后，我想留下的进展",
                    content=source.content,
                    consent=ConsentState.GRANTED,
                    explicit_user_request=True,
                    epistemic_kind=EpistemicKind.DIRECT_SELF_REPORT,
                    subject_actor_id=source.user_id,
                    event_at=source.occurred_at,
                    evidence_turn_ids=[source.id],
                    source_ref=f"turn:{source.id}",
                    source_excerpt=source.content,
                    stable_key="focus_progress:" + source.id,
                    metadata={"user_reported": True},
                )
            )
            if result.memory and result.memory.status is MemoryStatus.CANDIDATE:
                host.memory.review(result.memory.id, source.user_id, ReviewDecision.CONFIRM)
        return {"saved": True, "memory_id": result.memory.id if result.memory else None}

    def chat(self, item: ChatInput) -> dict[str, Any] | None:
        from companion_agent.app import public_turn

        # Rich messages retain the current frontend's image and quote pipeline.
        # The small command bridge only owns plain-text control messages.
        if item.image_ids or item.quote_id:
            return None
        host = self.host
        scope = host.scope(item.conversation_id)
        turns = host.memory.list_turns(host.key.user_id, scope)
        previous = next(
            (t for t in turns if t.idempotency_key == "focus_reply:" + item.request_id), None
        )
        if previous:
            cached_source = host.memory.store.get_turn(
                previous.reply_to_turn_id or "", host.key.user_id
            )
            if cached_source.content != item.content:
                raise ValueError("idempotency key reused with different input")
            if any(
                t.deletion_state is not TurnDeletionState.ACTIVE for t in (cached_source, previous)
            ):
                raise ValueError("cached focus conversation no longer available")
            return {
                "user": public_turn(cached_source),
                "assistant": public_turn(previous),
                "reused": True,
            }
        draft = proposal(item.content)
        snapshot = host.focus.read(host.settings.calendar_timezone)
        session = snapshot["session"]
        direct = "，".join(direct_clauses(item.content)).strip("，。！!?？ ")
        action: Literal["finish", "pause", "resume"] | None = None
        if session and session["phase"] not in {"done", "ended"}:
            if re.fullmatch(
                r"(?:今天|现在)?(?:不想弄了|不做了|先到这里|结束专注|结束计时)", direct
            ):
                action = "finish"
            elif re.fullmatch(r"(?:先)?暂停(?:一下|专注|计时)?", direct) and session["phase"] in {
                "focus",
                "rest",
            }:
                action = "pause"
            elif re.fullmatch(r"继续(?:专注|计时)", direct) and session["phase"] in {
                "focus_paused",
                "rest_paused",
            }:
                action = "resume"
        if draft is None and action is None:
            return None
        with host.database.atomic():
            source = host.memory.append_turn(
                ConversationTurnInput(
                    user_id=host.key.user_id,
                    scope=scope,
                    role=ConversationRole.USER,
                    actor_id=host.key.user_id,
                    content=item.content,
                    consent=ConsentState.GRANTED,
                    idempotency_key=item.request_id,
                    source_ref="focus:chat",
                )
            ).turn
            assert source is not None
            if action:
                host.focus.act(
                    FocusAction(
                        session_id=session["id"],
                        revision=session["revision"],
                        action=action,
                    ),
                    host.settings.calendar_timezone,
                )
                reply = {
                    "finish": "好，先到这里。",
                    "pause": "好，暂停了。",
                    "resume": "好，接着来。",
                }[action]
            elif session and session["phase"] not in CLOSED:
                reply, draft = "这段计时还在，随时可以暂停或结束。", None
            else:
                reply = "好。时间和要做的事都可以改，准备好了就开始。"
            assistant = host.memory.append_turn(
                ConversationTurnInput(
                    user_id=host.key.user_id,
                    scope=scope,
                    role=ConversationRole.ASSISTANT,
                    actor_id=host.key.companion_id,
                    content=reply,
                    consent=ConsentState.GRANTED,
                    idempotency_key="focus_reply:" + item.request_id,
                    reply_to_turn_id=source.id,
                    source_ref="focus:control",
                    metadata={"focus_proposal": draft} if draft else {},
                )
            ).turn
            assert assistant is not None
            with host.database.connection() as db:
                db.execute(
                    "UPDATE romance_conversations SET title=CASE WHEN title='新的对话' "
                    "THEN ? ELSE title END, updated_at=? WHERE id=?",
                    (item.content[:24], datetime.now(UTC).isoformat(), item.conversation_id),
                )
        return {"user": public_turn(source), "assistant": public_turn(assistant), "reused": False}
