from __future__ import annotations

from datetime import UTC, datetime

import pytest

from companion_memoryos.schemas import (
    ConsentState,
    MemoryInput,
    MemoryKind,
    MemoryStatus,
    RecallRequest,
    ReviewDecision,
    StorageAction,
)
from companion_memoryos.service import CompanionMemoryService


def explicit_memory(
    content: str,
    *,
    user_id: str = "alice",
    kind: MemoryKind = MemoryKind.PREFERENCE,
    stable_key: str | None = "preferred_name",
) -> MemoryInput:
    return MemoryInput(
        user_id=user_id,
        kind=kind,
        title="偏好",
        content=content,
        stable_key=stable_key,
        consent=ConsentState.GRANTED,
        explicit_user_request=True,
    )


def test_stable_memory_supersedes_previous_version(service: CompanionMemoryService) -> None:
    first = service.remember(explicit_memory("叫我小禾")).memory
    second = service.remember(explicit_memory("叫我禾禾")).memory
    assert first is not None and second is not None
    assert second.supersedes_id == first.id
    assert service.store.get(first.id, "alice").status is MemoryStatus.SUPERSEDED
    context = service.recall(RecallRequest(user_id="alice", query="叫我"))
    recalled = [item.memory for values in context.sections.values() for item in values]
    assert second.id in {memory.id for memory in recalled}
    assert first.id not in {memory.id for memory in recalled}


def test_candidate_can_be_confirmed(service: CompanionMemoryService) -> None:
    candidate = service.remember(
        MemoryInput(
            user_id="alice",
            kind=MemoryKind.SUPPORT_STRATEGY,
            title="安慰方式",
            content="也许她更喜欢先被倾听",
        )
    )
    assert candidate.action is StorageAction.CANDIDATE
    assert candidate.memory is not None
    assert candidate.memory.expires_at is not None
    confirmed = service.review(candidate.memory.id, "alice", ReviewDecision.CONFIRM)
    assert confirmed.status is MemoryStatus.ACTIVE
    assert confirmed.consent is ConsentState.GRANTED
    assert confirmed.expires_at is None


def test_expired_candidate_cannot_be_confirmed(service: CompanionMemoryService) -> None:
    candidate = service.remember(
        MemoryInput(
            user_id="alice",
            kind=MemoryKind.SUPPORT_STRATEGY,
            title="过期候选",
            content="也许她以前喜欢先被倾听",
        )
    )
    assert candidate.memory is not None
    with service.store.database.connection() as connection:
        connection.execute(
            "UPDATE memories SET expires_at = ? WHERE id = ?",
            (datetime(2020, 1, 1, tzinfo=UTC).isoformat(), candidate.memory.id),
        )

    with pytest.raises(ValueError, match="only candidate"):
        service.review(candidate.memory.id, "alice", ReviewDecision.CONFIRM)

    assert service.store.get(candidate.memory.id, "alice").status is MemoryStatus.EXPIRED


def test_exact_duplicate_is_not_inserted_twice(service: CompanionMemoryService) -> None:
    first = service.remember(explicit_memory("不喜欢语音电话", stable_key="calls"))
    second = service.remember(explicit_memory("不喜欢语音电话", stable_key="calls"))
    assert first.memory is not None
    assert second.duplicate_of == first.memory.id
    assert len(service.list_memories("alice")) == 1


def test_generic_titles_do_not_auto_supersede_unrelated_memories(
    service: CompanionMemoryService,
) -> None:
    first = service.remember(explicit_memory("喜欢咖啡", stable_key=None)).memory
    second = service.remember(explicit_memory("最近不吃辣", stable_key=None)).memory

    assert first is not None and second is not None
    assert first.stable_key is None
    assert second.stable_key is None
    assert service.store.get(first.id, "alice").status is MemoryStatus.ACTIVE
    assert service.store.get(second.id, "alice").status is MemoryStatus.ACTIVE


def test_exact_text_with_different_stable_identities_is_not_merged(
    service: CompanionMemoryService,
) -> None:
    first = service.remember(explicit_memory("保留原话", stable_key="identity-one")).memory
    second = service.remember(explicit_memory("保留原话", stable_key="identity-two")).memory

    assert first is not None and second is not None
    assert first.id != second.id
    assert first.stable_key == "identity-one"
    assert second.stable_key == "identity-two"


def test_user_scope_is_enforced(service: CompanionMemoryService) -> None:
    created = service.remember(explicit_memory("喜欢简短回答")).memory
    assert created is not None
    with pytest.raises(KeyError):
        service.store.get(created.id, "bob")


def test_forget_then_purge(service: CompanionMemoryService) -> None:
    created = service.remember(explicit_memory("周日不提醒工作")).memory
    assert created is not None
    forgotten = service.forget(created.id, "alice")
    assert forgotten.status is MemoryStatus.FORGOTTEN
    service.purge(created.id, "alice")
    with pytest.raises(KeyError):
        service.store.get(created.id, "alice")
    with service.store.database.connection() as connection:
        audit = connection.execute(
            "SELECT event_type, payload_json FROM audit_events WHERE memory_id = ?",
            (created.id,),
        ).fetchone()
    assert audit is not None
    assert audit["event_type"] == "memory.purged"
    assert audit["payload_json"] == "{}"
