from __future__ import annotations

import pytest

from companion_memoryos.schemas import (
    ConsentState,
    ConversationRole,
    ConversationTurnInput,
    MemoryCorrectionRequest,
    MemoryInput,
    MemoryKind,
    MemoryScope,
    MemoryStatus,
    RecallRequest,
    ReviewDecision,
    Sensitivity,
    StorageAction,
)
from companion_memoryos.service import CompanionMemoryService


def _preference(service: CompanionMemoryService, *, sensitivity: Sensitivity = Sensitivity.NORMAL):
    result = service.remember(
        MemoryInput(
            user_id="alice",
            kind=MemoryKind.PREFERENCE,
            title="称呼偏好",
            content="叫我小禾",
            stable_key="preferred_name",
            consent=ConsentState.GRANTED,
            explicit_user_request=True,
            sensitivity=sensitivity,
        )
    )
    assert result.memory is not None
    return result.memory


def test_direct_correction_inherits_consent_and_supersedes_old_version(
    service: CompanionMemoryService,
) -> None:
    old = _preference(service)
    result = service.correct(
        old.id,
        MemoryCorrectionRequest(user_id="alice", content="叫我禾禾"),
    )

    assert result.action is StorageAction.ACTIVATE
    assert result.memory is not None
    assert result.memory.consent is ConsentState.GRANTED
    assert result.memory.supersedes_id == old.id
    assert result.memory.metadata["correction_of"] == old.id
    assert service.store.get(old.id, "alice").status is MemoryStatus.SUPERSEDED

    context = service.recall(RecallRequest(user_id="alice", query="怎么称呼我"))
    recalled = [item.memory for values in context.sections.values() for item in values]
    assert result.memory.id in {memory.id for memory in recalled}
    assert old.id not in {memory.id for memory in recalled}


def test_correction_is_user_scoped_and_requires_stable_identity(
    service: CompanionMemoryService,
) -> None:
    old = _preference(service)
    with pytest.raises(KeyError):
        service.correct(old.id, MemoryCorrectionRequest(user_id="bob", content="叫我禾禾"))

    moment = service.remember(
        MemoryInput(
            user_id="alice",
            kind=MemoryKind.SHARED_MOMENT,
            title="一件小事",
            content="买过一枝花",
            consent=ConsentState.GRANTED,
            explicit_user_request=True,
        )
    ).memory
    assert moment is not None
    with pytest.raises(ValueError):
        service.correct(
            moment.id,
            MemoryCorrectionRequest(user_id="alice", content="买过两枝花"),
        )


def test_highly_sensitive_correction_waits_for_review_before_replacing_old(
    service: CompanionMemoryService,
) -> None:
    candidate = _preference(service, sensitivity=Sensitivity.HIGHLY_SENSITIVE)
    old = service.review(candidate.id, "alice", ReviewDecision.CONFIRM)

    result = service.correct(
        old.id,
        MemoryCorrectionRequest(user_id="alice", content="更新后的敏感偏好"),
    )

    assert result.action is StorageAction.CANDIDATE
    assert result.memory is not None
    assert service.store.get(old.id, "alice").status is MemoryStatus.ACTIVE
    confirmed = service.review(result.memory.id, "alice", ReviewDecision.CONFIRM)
    assert confirmed.supersedes_id == old.id
    assert service.store.get(old.id, "alice").status is MemoryStatus.SUPERSEDED


def test_purging_old_version_detaches_surviving_version_safely(
    service: CompanionMemoryService,
) -> None:
    old = _preference(service)
    current = service.correct(
        old.id,
        MemoryCorrectionRequest(user_id="alice", content="叫我禾禾"),
    ).memory
    assert current is not None

    service.purge(old.id, "alice")

    assert service.store.get(current.id, "alice").supersedes_id is None


def test_correction_uses_new_evidence_instead_of_relabeling_old_turn(
    service: CompanionMemoryService,
) -> None:
    turn_scope = MemoryScope(
        companion_id="companion",
        relationship_id="relationship",
        conversation_id="conversation",
    )
    relationship_scope = turn_scope.model_copy(update={"conversation_id": None})
    old_turn = service.append_turn(
        ConversationTurnInput(
            user_id="alice",
            scope=turn_scope,
            actor_id="alice",
            role=ConversationRole.USER,
            content="叫我小禾",
            consent=ConsentState.GRANTED,
        )
    ).turn
    correction_turn = service.append_turn(
        ConversationTurnInput(
            user_id="alice",
            scope=turn_scope,
            actor_id="alice",
            role=ConversationRole.USER,
            content="不是小禾，是禾禾",
            consent=ConsentState.GRANTED,
        )
    ).turn
    assert old_turn is not None and correction_turn is not None
    old = service.remember(
        MemoryInput(
            user_id="alice",
            scope=relationship_scope,
            kind=MemoryKind.PREFERENCE,
            title="称呼偏好",
            content="叫我小禾",
            stable_key="preferred_name",
            predicate="preferred_name",
            consent=ConsentState.GRANTED,
            explicit_user_request=True,
            evidence_turn_ids=[old_turn.id],
        )
    ).memory
    assert old is not None

    corrected = service.correct(
        old.id,
        MemoryCorrectionRequest(
            user_id="alice",
            content="叫我禾禾",
            evidence_turn_ids=[correction_turn.id],
        ),
    ).memory
    assert corrected is not None
    assert corrected.evidence_turn_ids == [correction_turn.id]

    service.purge_turn(old_turn.id, "alice")

    surviving = service.store.get(corrected.id, "alice")
    assert surviving.evidence_turn_ids == [correction_turn.id]
    assert surviving.supersedes_id is None
