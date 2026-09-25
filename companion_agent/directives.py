"""Keep explicit user notes with their original wording and evidence scope."""

from __future__ import annotations

import re

from companion_agent.memory_language import memory_note
from companion_memoryos.schemas import (
    AnswerSemantics,
    ConversationRole,
    ConversationTurnRecord,
    MemoryInput,
    MemoryKind,
    MemoryScope,
    MemoryStatus,
    RecallIntent,
    RecallRequest,
)
from companion_memoryos.service import CompanionMemoryService
from companion_memoryos.temporal import literal_event_day

NICKNAME = re.compile(r"(?:以后|今后|从现在起)?(?:请)?叫我(?P<name>[\w·-]{1,24})[。.!！]?$")
NAME_QUESTION = re.compile(
    r"叫我什么|我叫什么|怎么称呼我|我的(?:名字|昵称|称呼).*(?:什么|吗|？|\?)"
)


def directive_recall(user_id: str, scope: MemoryScope, text: str) -> RecallRequest | None:
    if not NAME_QUESTION.search(text):
        return None
    # Use the core's explicit state resolution instead of relying on lexical
    # similarity to a short name. Deleted/changed/source-invalid facts stay excluded.
    return RecallRequest(
        user_id=user_id,
        scope=scope,
        query=text,
        intent=RecallIntent.REFLECT,
        answer_semantics=AnswerSemantics.LATEST_SELF_REPORT_ABOUT_TIME,
        state_predicate="preferred_name",
        state_subject_actor_id=user_id,
    )


def remember_directive(
    memory: CompanionMemoryService,
    turn: ConversationTurnRecord,
    calendar_timezone: str = "UTC",
) -> bool:
    if turn.role is not ConversationRole.USER:
        return False
    # Reuse the core's quote, actor and reality-layer filtering. Do not turn a
    # hypothetical, quotation or someone else's instruction into the user's preference.
    direct = memory._direct_user_discourse_text(turn).strip()
    nickname = NICKNAME.fullmatch(direct)
    note = memory_note(direct)
    if not nickname and not note:
        return False
    event_day = literal_event_day(note, turn.occurred_at, calendar_timezone) if note else None
    decision = memory.remember(
        MemoryInput(
            user_id=turn.user_id,
            scope=turn.scope.model_copy(update={"conversation_id": None}),
            kind=MemoryKind.PREFERENCE if nickname else MemoryKind.SHARED_MOMENT,
            title="希望被称呼的名字" if nickname else "你明确希望记住的小事",
            # Preserve the exact statement, not an inferred paraphrase.
            content=direct,
            predicate="preferred_name" if nickname else None,
            subject_actor_id=turn.user_id if nickname else None,
            explicit_user_request=True,
            consent=turn.consent,
            sensitivity=turn.sensitivity,
            event_at=(event_day.start if event_day is not None else None) or turn.occurred_at,
            evidence_turn_ids=[turn.id],
            source_ref=f"turn:{turn.id}",
            metadata=(
                {
                    "event_time_precision": "day",
                    "event_time_basis": "literal_source_date",
                    "source_occurred_at": turn.occurred_at.isoformat(),
                }
                if event_day is not None
                else {}
            ),
        )
    )
    return bool(decision.memory and decision.memory.status is MemoryStatus.ACTIVE)
