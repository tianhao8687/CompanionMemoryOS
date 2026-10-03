"""Large provenance sets must not exceed SQLite's expression/parameter limits."""

from datetime import UTC, datetime, timedelta

import pytest

from companion_agent.evidence_policy import filter_recent_turns
from companion_agent.relationship.models import RelationshipKey
from companion_memoryos.schemas import (
    ConsentState,
    ConversationRole,
    ConversationTurnInput,
    ExperienceEvidenceKind,
    ExperienceEvidenceRef,
    MemoryReferenceFeedbackInput,
    MemoryScope,
    MemoryUsePlan,
    ReferenceFeedbackKind,
)


@pytest.mark.parametrize("size", [1200, 20000])
def test_feedback_and_usage_lookup_accept_long_provenance_sets(service, size):
    refs = [
        ExperienceEvidenceRef(kind=ExperienceEvidenceKind.TURN, id=f"synthetic-{index}")
        for index in range(size)
    ]
    now = datetime.now(UTC)
    scope = MemoryScope(companion_id="companion", relationship_id="long", conversation_id="c")
    assert service.store.latest_reference_feedback("user", scope, refs, now) == {}
    assert (
        service.store.used_experience_evidence_since(
            "user", scope, refs, now - timedelta(days=1), now
        )
        == set()
    )


def test_large_provenance_closure_still_enforces_latest_scoped_feedback(service):
    scope = MemoryScope(companion_id="companion", relationship_id="long", conversation_id="c")
    key = RelationshipKey(user_id="user", companion_id="companion", relationship_id="long")
    now = datetime.now(UTC)
    sources = []
    with service.store.database.atomic():
        for index in range(1200):
            source = service.append_turn(
                ConversationTurnInput(
                    user_id="user",
                    scope=scope,
                    actor_id="user",
                    role=ConversationRole.USER,
                    content=f"独立合成来源 {index}。",
                    consent=ConsentState.GRANTED,
                    occurred_at=now - timedelta(hours=1),
                )
            ).turn
            assert source
            sources.append(source.id)
        reply = service.append_turn(
            ConversationTurnInput(
                user_id="user",
                scope=scope,
                actor_id="companion",
                role=ConversationRole.ASSISTANT,
                content="基于这批来源的回复。",
                consent=ConsentState.GRANTED,
                occurred_at=now - timedelta(minutes=1),
                metadata={"context_turn_ids": sources},
            )
        ).turn
    assert reply
    service.record_reference_feedback(
        MemoryReferenceFeedbackInput(
            user_id="user",
            scope=scope,
            evidence_kind=ExperienceEvidenceKind.TURN,
            evidence_id=sources[-1],
            kind=ReferenceFeedbackKind.DO_NOT_REFERENCE,
            recorded_at=now + timedelta(seconds=1),
        )
    )
    assert filter_recent_turns(service, key, [reply], MemoryUsePlan(), now) == [reply]
    assert (
        filter_recent_turns(service, key, [reply], MemoryUsePlan(), now + timedelta(seconds=2))
        == []
    )
    refs = [ExperienceEvidenceRef(kind=ExperienceEvidenceKind.TURN, id=ref) for ref in sources]
    assert service.store.latest_reference_feedback("other-user", scope, refs, now) == {}
    other_scope = scope.model_copy(update={"conversation_id": "other"})
    assert (
        service.store.latest_reference_feedback(
            "user", other_scope, refs, now + timedelta(seconds=2)
        )
        == {}
    )
    assert (
        service.store.latest_reference_feedback(
            "user",
            scope,
            [ExperienceEvidenceRef(kind=ExperienceEvidenceKind.MEMORY, id=sources[-1])],
            now + timedelta(seconds=2),
        )
        == {}
    )
    assert service.store.get_turn(reply.id, "user").content == "基于这批来源的回复。"
