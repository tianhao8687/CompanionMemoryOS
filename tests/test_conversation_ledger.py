from __future__ import annotations

from datetime import UTC, datetime

import pytest

from companion_memoryos.schemas import (
    AnswerSemantics,
    ChannelStatus,
    ConsentState,
    ConversationRole,
    ConversationTurnInput,
    EpistemicKind,
    MemoryInput,
    MemoryKind,
    MemoryScope,
    MemoryStatus,
    ProcessingWatermarkInput,
    RealityLayer,
    RecallRequest,
    ResolutionStatus,
    SpeechAct,
    SpeechSpan,
    TurnDeletionState,
)
from companion_memoryos.service import CompanionMemoryService

RELATIONSHIP = MemoryScope(
    companion_id="companion-a",
    relationship_id="relationship-a",
    conversation_id="conversation-a",
)


def _turn(
    content: str,
    *,
    scope: MemoryScope = RELATIONSHIP,
    role: ConversationRole = ConversationRole.USER,
    actor_id: str = "alice",
) -> ConversationTurnInput:
    return ConversationTurnInput(
        user_id="alice",
        scope=scope,
        actor_id=actor_id,
        role=role,
        content=content,
        consent=ConsentState.GRANTED,
        occurred_at=datetime(2026, 8, 1, tzinfo=UTC),
    )


def test_authorized_raw_turn_survives_extraction_failure_and_is_recalled(
    service: CompanionMemoryService,
) -> None:
    stored = service.append_turn(_turn("在校门口捡到一片心形叶子"))
    assert stored.stored is True
    assert stored.turn is not None

    context = service.recall(
        RecallRequest(
            user_id="alice",
            scope=RELATIONSHIP,
            query="心形叶子",
            event_limit=0,
        )
    )

    assert context.retrieval_action.value == "answer_single"
    assert context.turn_fallback[0].turn.id == stored.turn.id
    assert "[raw_turn_evidence]" in context.prompt_text
    assert context.integrity_manifest.negative_claim_safe is False
    assert context.policy_bundle.production_eligible is False


def test_turn_write_requires_consent_and_is_idempotent(
    service: CompanionMemoryService,
) -> None:
    denied = service.append_turn(
        _turn("不应落盘").model_copy(update={"consent": ConsentState.UNKNOWN})
    )
    delivery = _turn("同一条投递").model_copy(update={"idempotency_key": "provider-message-1"})
    first = service.append_turn(delivery)
    duplicate = service.append_turn(delivery)

    assert denied.stored is False
    assert first.turn is not None
    assert duplicate.duplicate_of == first.turn.id
    assert len(service.list_turns("alice", RELATIONSHIP)) == 1


def test_nested_quote_attribution_survives_turn_round_trip(
    service: CompanionMemoryService,
) -> None:
    content = "前任写道：我永远爱你"
    quoted = "我永远爱你"
    start = content.index(quoted)
    stored = service.append_turn(
        _turn(content).model_copy(
            update={
                "speech_spans": [
                    SpeechSpan(
                        start_offset=start,
                        end_offset=start + len(quoted),
                        quote_depth=1,
                        attributed_speaker_id="former-partner",
                        target_actor_id="alice",
                        reality_layer=RealityLayer.QUOTE,
                        speech_act=SpeechAct.QUOTE,
                        model_fingerprint="discourse:test",
                    )
                ]
            }
        )
    )

    assert stored.turn is not None
    assert stored.turn.speech_spans[0].attributed_speaker_id == "former-partner"
    assert stored.turn.speech_spans[0].quote_depth == 1


def test_turn_references_and_recall_cannot_cross_relationships(
    service: CompanionMemoryService,
) -> None:
    first = service.append_turn(_turn("关系 A 的蓝色杯子")).turn
    other_scope = MemoryScope(
        companion_id="companion-b",
        relationship_id="relationship-b",
        conversation_id="conversation-b",
    )
    service.append_turn(_turn("关系 B 的蓝色杯子", scope=other_scope))
    assert first is not None

    with pytest.raises(ValueError):
        service.append_turn(
            _turn("错误跨会话回复", scope=other_scope).model_copy(
                update={"reply_to_turn_id": first.id}
            )
        )

    context = service.recall(
        RecallRequest(user_id="alice", scope=RELATIONSHIP, query="蓝色杯子", event_limit=0)
    )
    assert {item.turn.scope.relationship_id for item in context.turn_fallback} == {"relationship-a"}


def test_turn_idempotency_and_references_use_the_full_scope(
    service: CompanionMemoryService,
) -> None:
    first_scope = MemoryScope(
        companion_id="companion-a",
        relationship_id="relationship-a",
        conversation_id="shared-conversation-id",
    )
    second_scope = MemoryScope(
        companion_id="companion-b",
        relationship_id="relationship-b",
        conversation_id="shared-conversation-id",
    )
    first = service.append_turn(
        _turn("同一内容", scope=first_scope).model_copy(
            update={"idempotency_key": "shared-provider-id"}
        )
    ).turn
    second = service.append_turn(
        _turn("同一内容", scope=second_scope).model_copy(
            update={"idempotency_key": "shared-provider-id"}
        )
    )

    assert first is not None
    assert second.turn is not None
    assert second.duplicate_of is None
    assert second.turn.id != first.id
    with pytest.raises(ValueError, match="same exact scope"):
        service.append_turn(
            _turn("跨关系引用", scope=second_scope).model_copy(
                update={"reply_to_turn_id": first.id}
            )
        )

    partial = service.recall(
        RecallRequest(
            user_id="alice",
            scope=MemoryScope(conversation_id="shared-conversation-id"),
            query="同一内容",
            event_limit=0,
        )
    )
    first_context = service.recall(
        RecallRequest(user_id="alice", scope=first_scope, query="同一内容", event_limit=0)
    )
    second_context = service.recall(
        RecallRequest(user_id="alice", scope=second_scope, query="同一内容", event_limit=0)
    )

    assert partial.turn_fallback == []
    assert [item.turn.id for item in first_context.turn_fallback] == [first.id]
    assert [item.turn.id for item in second_context.turn_fallback] == [second.turn.id]


def test_identical_turns_are_not_merged_without_an_idempotency_key(
    service: CompanionMemoryService,
) -> None:
    first = service.append_turn(_turn("嗯")).turn
    second = service.append_turn(_turn("嗯")).turn

    assert first is not None and second is not None
    assert first.id != second.id
    assert len(service.list_turns("alice", RELATIONSHIP)) == 2


def test_idempotency_key_reuse_with_changed_payload_is_rejected(
    service: CompanionMemoryService,
) -> None:
    first = _turn("第一条内容").model_copy(update={"idempotency_key": "delivery-42"})
    service.append_turn(first)

    with pytest.raises(ValueError, match="different turn payload"):
        service.append_turn(first.model_copy(update={"content": "被错误复用键的另一条内容"}))


def test_idempotency_payload_comparison_preserves_case(
    service: CompanionMemoryService,
) -> None:
    first = _turn("US").model_copy(update={"idempotency_key": "delivery-case"})
    service.append_turn(first)

    with pytest.raises(ValueError, match="different turn payload"):
        service.append_turn(first.model_copy(update={"content": "us"}))


def test_utterance_history_requires_actor_and_excludes_quoted_speaker_text(
    service: CompanionMemoryService,
) -> None:
    content = "前任写道：我永远爱你"
    quoted = "我永远爱你"
    start = content.index(quoted)
    service.append_turn(
        _turn(content).model_copy(
            update={
                "speech_spans": [
                    SpeechSpan(
                        start_offset=start,
                        end_offset=start + len(quoted),
                        quote_depth=1,
                        attributed_speaker_id="former-partner",
                        target_actor_id="alice",
                        reality_layer=RealityLayer.QUOTE,
                        speech_act=SpeechAct.QUOTE,
                        model_fingerprint="discourse:test",
                    )
                ]
            }
        )
    )
    service.append_turn(_turn("我真的很喜欢雨天"))

    with pytest.raises(ValueError, match="utterance_actor_id"):
        RecallRequest(
            user_id="alice",
            scope=RELATIONSHIP,
            query="我说过什么",
            answer_semantics=AnswerSemantics.UTTERANCE_HISTORY,
        )

    quoted_result = service.recall(
        RecallRequest(
            user_id="alice",
            scope=RELATIONSHIP,
            query=quoted,
            answer_semantics=AnswerSemantics.UTTERANCE_HISTORY,
            utterance_actor_id="alice",
            event_limit=0,
        )
    )
    direct_result = service.recall(
        RecallRequest(
            user_id="alice",
            scope=RELATIONSHIP,
            query="喜欢雨天",
            answer_semantics=AnswerSemantics.UTTERANCE_HISTORY,
            utterance_actor_id="alice",
            event_limit=0,
        )
    )

    assert quoted_result.turn_fallback == []
    assert direct_result.turn_fallback[0].turn.content == "我真的很喜欢雨天"


def test_utterance_prompt_does_not_reinject_masked_quoted_text(
    service: CompanionMemoryService,
) -> None:
    content = "我真的很开心；前任写我永远爱你"
    quoted = "我永远爱你"
    start = content.index(quoted)
    service.append_turn(
        _turn(content).model_copy(
            update={
                "speech_spans": [
                    SpeechSpan(
                        start_offset=start,
                        end_offset=start + len(quoted),
                        quote_depth=1,
                        attributed_speaker_id="former-partner",
                        target_actor_id="alice",
                        reality_layer=RealityLayer.QUOTE,
                        speech_act=SpeechAct.QUOTE,
                        model_fingerprint="discourse:test",
                    )
                ]
            }
        )
    )

    result = service.recall(
        RecallRequest(
            user_id="alice",
            scope=RELATIONSHIP,
            query="真的很开心",
            answer_semantics=AnswerSemantics.UTTERANCE_HISTORY,
            utterance_actor_id="alice",
            event_limit=0,
        )
    )

    assert result.turn_fallback
    assert "我永远爱你" not in result.turn_fallback[0].evidence_text
    assert "我永远爱你" not in result.prompt_text
    assert "non_direct_spans_excluded" in result.prompt_text


def test_unscoped_raw_recall_is_conservatively_disabled(
    service: CompanionMemoryService,
) -> None:
    service.append_turn(_turn("只属于关系 A 的秘密"))
    context = service.recall(RecallRequest(user_id="alice", query="秘密", event_limit=0))
    relationship_only = service.recall(
        RecallRequest(
            user_id="alice",
            scope=MemoryScope(relationship_id="relationship-a"),
            query="秘密",
            event_limit=0,
        )
    )
    assert context.turn_fallback == []
    assert "scoped_turn_recall_required" in context.integrity_manifest.reasons
    assert relationship_only.turn_fallback == []
    assert "scoped_turn_recall_required" in relationship_only.integrity_manifest.reasons


def test_watermark_can_report_complete_external_semantic_index(
    service: CompanionMemoryService,
) -> None:
    turn = service.append_turn(_turn("幸运东西是一片叶子")).turn
    assert turn is not None
    service.update_processing_watermark(
        ProcessingWatermarkInput(
            user_id="alice",
            scope=RELATIONSHIP,
            channel="raw_turn_semantic",
            status=ChannelStatus.READY,
            durable_sequence=turn.server_sequence,
            indexed_sequence=turn.server_sequence,
            model_fingerprint="embedding:test",
        )
    )
    context = service.recall(
        RecallRequest(user_id="alice", scope=RELATIONSHIP, query="不存在的词", event_limit=0)
    )
    assert context.integrity_manifest.negative_claim_safe is False
    assert "raw_semantic_query_not_requested" in context.integrity_manifest.reasons


def test_turn_forget_purge_and_export_are_user_scoped(
    service: CompanionMemoryService,
) -> None:
    turn = service.append_turn(_turn("待删除的原始回合")).turn
    assert turn is not None
    with pytest.raises(KeyError):
        service.forget_turn(turn.id, "bob")
    forgotten = service.forget_turn(turn.id, "alice")
    assert forgotten.deletion_state is TurnDeletionState.FORGOTTEN
    assert service.export("alice").conversation_turns[0].id == turn.id
    service.purge_turn(turn.id, "alice")
    assert service.list_turns("alice") == []
    with service.store.database.connection() as connection:
        audit_rows = connection.execute(
            "SELECT event_type, payload_json FROM audit_events WHERE memory_id = ?",
            (turn.id,),
        ).fetchall()
    assert [row["event_type"] for row in audit_rows] == ["conversation_turn.purged"]
    assert audit_rows[0]["payload_json"] == "{}"


def test_forgetting_source_turn_removes_descendant_from_recall(
    service: CompanionMemoryService,
) -> None:
    turn = service.append_turn(_turn("以后叫我禾禾")).turn
    assert turn is not None
    memory = service.remember(
        MemoryInput(
            user_id="alice",
            scope=RELATIONSHIP,
            kind=MemoryKind.PREFERENCE,
            title="称呼",
            content="叫我禾禾",
            consent=ConsentState.GRANTED,
            explicit_user_request=True,
            evidence_turn_ids=[turn.id],
        )
    ).memory
    assert memory is not None

    service.forget_turn(turn.id, "alice")
    invalidated = service.store.get(memory.id, "alice")
    context = service.recall(RecallRequest(user_id="alice", scope=RELATIONSHIP, query="怎么称呼我"))

    assert invalidated.status is MemoryStatus.FORGOTTEN
    assert invalidated.resolution_status is ResolutionStatus.CONTESTED
    assert all(
        item.memory.id != memory.id for values in context.sections.values() for item in values
    )

    service.purge_turn(turn.id, "alice")
    with pytest.raises(KeyError):
        service.store.get(memory.id, "alice")


def test_evidence_memory_can_cross_conversations_but_not_consent_domains(
    service: CompanionMemoryService,
) -> None:
    turn = service.append_turn(_turn("以后叫我禾禾")).turn
    assert turn is not None
    relationship_scope = RELATIONSHIP.model_copy(update={"conversation_id": None})

    promoted = service.remember(
        MemoryInput(
            user_id="alice",
            scope=relationship_scope,
            kind=MemoryKind.PREFERENCE,
            title="称呼",
            content="叫我禾禾",
            consent=ConsentState.GRANTED,
            explicit_user_request=True,
            evidence_turn_ids=[turn.id],
        )
    )
    assert promoted.memory is not None

    with pytest.raises(ValueError, match="cannot widen"):
        service.remember(
            MemoryInput(
                user_id="alice",
                kind=MemoryKind.PREFERENCE,
                title="全局称呼",
                content="在所有角色里都叫我禾禾",
                consent=ConsentState.GRANTED,
                explicit_user_request=True,
                evidence_turn_ids=[turn.id],
            )
        )


def test_third_party_turn_cannot_support_a_user_self_report(
    service: CompanionMemoryService,
) -> None:
    turn = service.append_turn(
        _turn(
            "她说自己喜欢下雨天",
            role=ConversationRole.THIRD_PARTY,
            actor_id="friend",
        )
    ).turn
    assert turn is not None

    with pytest.raises(ValueError, match="user-authored"):
        service.remember(
            MemoryInput(
                user_id="alice",
                scope=RELATIONSHIP,
                kind=MemoryKind.PREFERENCE,
                title="天气偏好",
                content="我喜欢下雨天",
                consent=ConsentState.GRANTED,
                explicit_user_request=True,
                evidence_turn_ids=[turn.id],
            )
        )


def test_quote_only_user_turn_cannot_be_promoted_to_direct_self_report(
    service: CompanionMemoryService,
) -> None:
    content = "她说：我喜欢你"
    quoted = "我喜欢你"
    start = content.index(quoted)
    turn = service.append_turn(
        _turn(content).model_copy(
            update={
                "speech_spans": [
                    SpeechSpan(
                        start_offset=start,
                        end_offset=start + len(quoted),
                        quote_depth=1,
                        attributed_speaker_id="friend",
                        target_actor_id="companion-a",
                        reality_layer=RealityLayer.QUOTE,
                        speech_act=SpeechAct.QUOTE,
                        model_fingerprint="discourse:test",
                    )
                ]
            }
        )
    ).turn
    assert turn is not None

    with pytest.raises(ValueError, match="quoted or fictional"):
        service.remember(
            MemoryInput(
                user_id="alice",
                scope=RELATIONSHIP,
                kind=MemoryKind.RELATIONSHIP,
                title="关系自述",
                content="我喜欢你",
                stable_key="affection",
                predicate="self_reported_affection",
                epistemic_kind=EpistemicKind.DIRECT_SELF_REPORT,
                consent=ConsentState.GRANTED,
                explicit_user_request=True,
                evidence_turn_ids=[turn.id],
            )
        )
