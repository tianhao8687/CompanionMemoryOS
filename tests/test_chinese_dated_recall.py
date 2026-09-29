from datetime import UTC, datetime, timedelta

import pytest

from companion_agent.cognition import ApplicationMemory
from companion_memoryos.schemas import (
    AnswerCardinality,
    ConsentState,
    ConversationRole,
    ConversationTurnInput,
    ExperienceEvidenceKind,
    MemoryReferenceFeedbackInput,
    MemoryScope,
    RecallRequest,
    ReferenceFeedbackKind,
    Sensitivity,
)

SCOPE = MemoryScope(companion_id="c", relationship_id="r", conversation_id="history")
NOW = datetime(2026, 9, 29, tzinfo=UTC)


def append(memory, content, occurred_at, **changes):
    fields = dict(
        user_id="u",
        scope=SCOPE,
        actor_id="u",
        role=ConversationRole.USER,
        content=content,
        occurred_at=occurred_at,
        consent=ConsentState.GRANTED,
    )
    fields.update(changes)
    turn = memory.append_turn(ConversationTurnInput(**fields)).turn
    assert turn
    return turn


def request(**changes):
    fields = dict(
        user_id="u",
        scope=SCOPE.model_copy(update={"conversation_id": "new"}),
        query="8月3号我和你聊了些什么？",
        as_of=NOW,
        include_turn_evidence=True,
        include_relationship_turns=True,
        answer_cardinality=AnswerCardinality.OPEN,
        turn_limit=6,
        max_tokens=2500,
        max_characters=12000,
    )
    fields.update(changes)
    return RecallRequest(**fields)


def test_dated_context_survives_a_full_recent_candidate_pool(service):
    memory = ApplicationMemory(service.store, service.config)
    day = datetime(2026, 8, 3, tzinfo=UTC)
    a = append(memory, "午饭吃了凉面。", day)
    b = append(memory, "新买的钢笔漏墨了。", day + timedelta(minutes=2))
    with memory.store.database.session():
        for i in range(memory.config.retrieval.turn_candidate_pool + 10):
            append(memory, f"今天聊了编号{i}的话题。", NOW - timedelta(minutes=i + 1))
    results = memory.recall(request()).turn_fallback
    assert {a.id, b.id} <= {item.turn.id for item in results}
    assert all(item.turn.occurred_at.date() == day.date() for item in results[:2])


@pytest.mark.parametrize("restriction", ["scope", "exclude", "feedback", "forgotten", "sensitive"])
def test_date_candidates_keep_source_restrictions(service, restriction):
    memory = ApplicationMemory(service.store, service.config)
    turn = append(
        memory,
        "午饭吃了凉面。",
        datetime(2026, 8, 3, tzinfo=UTC),
        **(
            {"scope": SCOPE.model_copy(update={"group_id": "other"})}
            if restriction == "scope"
            else {}
        ),
        **({"sensitivity": Sensitivity.SENSITIVE} if restriction == "sensitive" else {}),
    )
    changes = {}
    if restriction == "exclude":
        changes["exclude_turn_ids"] = [turn.id]
    elif restriction == "feedback":
        memory.record_reference_feedback(
            MemoryReferenceFeedbackInput(
                user_id="u",
                scope=SCOPE,
                evidence_kind=ExperienceEvidenceKind.TURN,
                evidence_id=turn.id,
                kind=ReferenceFeedbackKind.DO_NOT_REFERENCE,
                recorded_at=NOW,
            )
        )
    elif restriction == "forgotten":
        memory.forget_turn(turn.id, "u")
    assert turn.id not in {item.turn.id for item in memory.recall(request(**changes)).turn_fallback}


def test_date_candidate_lookup_does_not_override_explicit_filter(service):
    memory = ApplicationMemory(service.store, service.config)
    turn = append(memory, "午饭吃了凉面。", datetime(2026, 8, 3, tzinfo=UTC))
    result = memory.recall(request(event_after=datetime(2026, 9, 1, tzinfo=UTC)))
    assert turn.id not in {item.turn.id for item in result.turn_fallback}


def test_event_date_does_not_remove_later_report(service):
    memory = ApplicationMemory(service.store, service.config)
    turn = append(memory, "昨天8月3日去了植物园看睡莲。", datetime(2026, 8, 4, tzinfo=UTC))
    result = memory.recall(request(query="8月3号我在植物园看了什么？"))
    assert turn.id in {item.turn.id for item in result.turn_fallback}
