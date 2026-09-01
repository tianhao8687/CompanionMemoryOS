from __future__ import annotations

from datetime import UTC, datetime

import pytest

from companion_memoryos.schemas import (
    ConsentState,
    MemoryInput,
    MemoryKind,
    RecallRequest,
    Sensitivity,
    TemporalAnchorInput,
    TemporalAnchorStatus,
)
from companion_memoryos.service import CompanionMemoryService

START = datetime(2026, 3, 1, tzinfo=UTC)
END = datetime(2026, 4, 1, tzinfo=UTC)


def _anchor(
    service: CompanionMemoryService,
    name: str = "备考期",
    *,
    aliases: list[str] | None = None,
):
    return service.remember_temporal_anchor(
        TemporalAnchorInput(
            user_id="alice",
            name=name,
            aliases=aliases or [],
            start_at=START,
            end_at=END,
            consent=ConsentState.GRANTED,
        )
    )


def test_personal_time_phrase_scopes_recall_and_is_rendered(
    service: CompanionMemoryService,
) -> None:
    stored = _anchor(service, aliases=["冲刺那阵子"])
    assert stored.anchor is not None
    inside = service.remember(
        MemoryInput(
            user_id="alice",
            kind=MemoryKind.SHARED_MOMENT,
            title="深夜散步",
            content="在河边走了很久",
            consent=ConsentState.GRANTED,
            explicit_user_request=True,
            event_at=datetime(2026, 3, 15, tzinfo=UTC),
        )
    ).memory
    service.remember(
        MemoryInput(
            user_id="alice",
            kind=MemoryKind.SHARED_MOMENT,
            title="另一场散步",
            content="后来也在河边散步",
            consent=ConsentState.GRANTED,
            explicit_user_request=True,
            event_at=datetime(2026, 5, 15, tzinfo=UTC),
        )
    )

    context = service.recall(RecallRequest(user_id="alice", query="冲刺那阵子的河边散步"))

    assert context.resolved_temporal_anchor is not None
    assert context.resolved_temporal_anchor.id == stored.anchor.id
    assert "[resolved_time_anchor]" in context.prompt_text
    assert context.rendered_tokens == service.token_counter.count(context.prompt_text)
    recalled = [item.memory.id for values in context.sections.values() for item in values]
    assert inside is not None and recalled == [inside.id]


def test_same_strength_anchor_matches_request_natural_disambiguation(
    service: CompanionMemoryService,
) -> None:
    _anchor(service, "第一次备考", aliases=["备考期"])
    service.remember_temporal_anchor(
        TemporalAnchorInput(
            user_id="alice",
            name="第二次备考",
            aliases=["备考期"],
            start_at=datetime(2026, 6, 1, tzinfo=UTC),
            end_at=datetime(2026, 7, 1, tzinfo=UTC),
            consent=ConsentState.GRANTED,
        )
    )

    context = service.recall(RecallRequest(user_id="alice", query="备考期发生了什么"))

    assert context.temporal_anchor_ambiguity is True
    assert context.ambiguity_detected is True
    assert context.resolved_temporal_anchor is None
    assert len(context.temporal_anchor_candidates) == 2


def test_exact_longer_anchor_beats_a_short_generic_alias(
    service: CompanionMemoryService,
) -> None:
    first = _anchor(service, "第一次备考期")
    service.remember_temporal_anchor(
        TemporalAnchorInput(
            user_id="alice",
            name="春天",
            aliases=["备考期"],
            start_at=datetime(2026, 2, 1, tzinfo=UTC),
            end_at=datetime(2026, 5, 1, tzinfo=UTC),
            consent=ConsentState.GRANTED,
        )
    )
    context = service.recall(RecallRequest(user_id="alice", query="第一次备考期"))
    assert first.anchor is not None
    assert context.resolved_temporal_anchor is not None
    assert context.resolved_temporal_anchor.id == first.anchor.id


def test_anchor_requires_consent_and_sensitive_storage_is_off_by_default(
    service: CompanionMemoryService,
) -> None:
    unknown = service.remember_temporal_anchor(
        TemporalAnchorInput(user_id="alice", name="那段时间", start_at=START, end_at=END)
    )
    sensitive = service.remember_temporal_anchor(
        TemporalAnchorInput(
            user_id="alice",
            name="治疗期",
            start_at=START,
            end_at=END,
            consent=ConsentState.GRANTED,
            sensitivity=Sensitivity.SENSITIVE,
        )
    )
    assert unknown.stored is False
    assert sensitive.stored is False


def test_anchor_version_forget_purge_and_export(service: CompanionMemoryService) -> None:
    first = _anchor(service).anchor
    second = service.remember_temporal_anchor(
        TemporalAnchorInput(
            user_id="alice",
            name="备考期",
            start_at=datetime(2026, 3, 2, tzinfo=UTC),
            end_at=END,
            consent=ConsentState.GRANTED,
        )
    ).anchor
    assert first is not None and second is not None
    assert second.supersedes_id == first.id
    superseded = service.list_temporal_anchors("alice", {TemporalAnchorStatus.SUPERSEDED})
    assert superseded[0].id == first.id
    forgotten = service.forget_temporal_anchor(second.id, "alice")
    assert forgotten.status is TemporalAnchorStatus.FORGOTTEN
    assert len(service.export("alice").temporal_anchors) == 2
    service.purge_temporal_anchor(second.id, "alice")
    assert [anchor.id for anchor in service.list_temporal_anchors("alice")] == [first.id]
    with service.store.database.connection() as connection:
        audit = connection.execute(
            "SELECT event_type, payload_json FROM audit_events WHERE memory_id = ?",
            (second.id,),
        ).fetchone()
    assert audit is not None
    assert audit["event_type"] == "temporal_anchor.purged"
    assert audit["payload_json"] == "{}"


def test_temporal_anchor_mutations_are_user_scoped(service: CompanionMemoryService) -> None:
    anchor = _anchor(service).anchor
    assert anchor is not None
    with pytest.raises(KeyError):
        service.forget_temporal_anchor(anchor.id, "bob")
    with pytest.raises(KeyError):
        service.purge_temporal_anchor(anchor.id, "bob")
