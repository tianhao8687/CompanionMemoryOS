from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from companion_memoryos.schemas import (
    ConsentState,
    ConversationEventInput,
    ConversationRole,
    MemoryInput,
    MemoryKind,
    MemoryScope,
    RecallRequest,
    Sensitivity,
)
from companion_memoryos.service import CompanionMemoryService

SESSION_SCOPE = MemoryScope(conversation_id="session-one")


def event(
    consent: ConsentState, content: str = "路过花店买了一枝白色郁金香"
) -> ConversationEventInput:
    return ConversationEventInput(
        user_id="alice",
        session_id="session-one",
        role=ConversationRole.USER,
        content=content,
        consent=consent,
    )


def test_event_archive_requires_session_level_consent(
    service: CompanionMemoryService,
) -> None:
    result = service.archive_event(event(ConsentState.UNKNOWN))

    assert result.stored is False
    assert service.list_events("alice") == []


def test_highly_sensitive_raw_event_is_disabled_by_default(
    service: CompanionMemoryService,
) -> None:
    item = event(ConsentState.GRANTED).model_copy(
        update={"sensitivity": Sensitivity.HIGHLY_SENSITIVE}
    )

    result = service.archive_event(item)

    assert result.stored is False
    assert result.reasons == ["highly_sensitive_event_disabled"]
    assert service.list_events("alice") == []


def test_assistant_output_is_not_archived_as_user_evidence_by_default(
    service: CompanionMemoryService,
) -> None:
    item = event(ConsentState.GRANTED).model_copy(update={"role": ConversationRole.ASSISTANT})

    result = service.archive_event(item)

    assert result.stored is False
    assert result.reasons == ["assistant_event_disabled"]
    assert service.list_events("alice") == []


def test_unpromoted_small_event_can_be_recalled_without_user_review(
    service: CompanionMemoryService,
) -> None:
    stored = service.archive_event(event(ConsentState.GRANTED))
    assert stored.event is not None

    context = service.recall(
        RecallRequest(user_id="alice", scope=SESSION_SCOPE, query="上次买的白色郁金香")
    )

    assert context.sections == {}
    assert context.event_fallback[0].event.id == stored.event.id
    assert "raw_event_fallback" in context.event_fallback[0].reasons


def test_raw_event_recall_requires_conversation_scope(
    service: CompanionMemoryService,
) -> None:
    service.archive_event(event(ConsentState.GRANTED))

    context = service.recall(RecallRequest(user_id="alice", query="白色郁金香"))

    assert context.event_fallback == []


def test_raw_event_is_not_injected_when_structured_memory_can_answer(
    service: CompanionMemoryService,
) -> None:
    service.archive_event(event(ConsentState.GRANTED))
    service.remember(
        MemoryInput(
            user_id="alice",
            kind=MemoryKind.SHARED_MOMENT,
            title="白色郁金香",
            content="下班路上买过一枝白色郁金香",
            consent=ConsentState.GRANTED,
            explicit_user_request=True,
        )
    )

    context = service.recall(
        RecallRequest(user_id="alice", scope=SESSION_SCOPE, query="白色郁金香")
    )

    assert context.sections["shared_history"]
    assert context.event_fallback == []


def test_event_can_be_purged_and_is_included_in_export(
    service: CompanionMemoryService,
) -> None:
    stored = service.archive_event(event(ConsentState.GRANTED))
    assert stored.event is not None
    assert service.export("alice").events[0].id == stored.event.id

    service.purge_event(stored.event.id, "alice")

    assert service.export("alice").events == []


def test_expired_raw_event_is_physically_removed_but_minimally_audited(
    service: CompanionMemoryService,
) -> None:
    item = event(ConsentState.GRANTED, "一件到期后不应留下原文的小事")
    record = service.store.create_event(item, datetime.now(UTC) - timedelta(seconds=1))

    assert service.store.expire_events(datetime.now(UTC)) == 1
    with pytest.raises(KeyError):
        service.store.get_event(record.id, "alice")

    with service.store.database.connection() as connection:
        audits = connection.execute(
            "SELECT event_type, payload_json FROM audit_events WHERE memory_id = ?",
            (record.id,),
        ).fetchall()
    assert [row["event_type"] for row in audits] == ["event.expired_and_purged"]
    assert audits[0]["payload_json"] == "{}"
