from __future__ import annotations

import pytest

from companion_memoryos.schemas import (
    ConsentState,
    MemoryInput,
    MemoryKind,
    MemoryStatus,
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
    confirmed = service.review(candidate.memory.id, "alice", ReviewDecision.CONFIRM)
    assert confirmed.status is MemoryStatus.ACTIVE


def test_exact_duplicate_is_not_inserted_twice(service: CompanionMemoryService) -> None:
    first = service.remember(explicit_memory("不喜欢语音电话", stable_key="calls"))
    second = service.remember(explicit_memory("不喜欢语音电话", stable_key="calls"))
    assert first.memory is not None
    assert second.duplicate_of == first.memory.id
    assert len(service.list_memories("alice")) == 1


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
