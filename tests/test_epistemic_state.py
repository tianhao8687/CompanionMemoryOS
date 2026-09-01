from __future__ import annotations

from datetime import UTC, datetime

from companion_memoryos.schemas import (
    AnswerSemantics,
    ConsentState,
    ConversationRole,
    ConversationTurnInput,
    ElicitationKind,
    EpistemicKind,
    EvidenceActor,
    MemoryInput,
    MemoryKind,
    MemoryScope,
    RealityLayer,
    RecallRequest,
    ResolutionStatus,
    RetrievalAction,
    ReviewDecision,
    StateQuery,
    StorageAction,
)
from companion_memoryos.service import CompanionMemoryService

SCOPE = MemoryScope(companion_id="companion", relationship_id="relationship")
JUNE = datetime(2026, 6, 1, tzinfo=UTC)


def _state(content: str, **updates: object) -> MemoryInput:
    item = MemoryInput(
        user_id="alice",
        scope=SCOPE,
        kind=MemoryKind.RELATIONSHIP,
        title="关系自述",
        content=content,
        stable_key="relationship:affection",
        predicate="self_reported_affection",
        consent=ConsentState.GRANTED,
        explicit_user_request=True,
        event_at=JUNE,
        valid_time_start=JUNE,
    )
    return item.model_copy(update=updates)


def test_explicit_stable_state_becomes_qualified_self_report(
    service: CompanionMemoryService,
) -> None:
    result = service.remember(_state("我喜欢你"))
    assert result.action is StorageAction.ACTIVATE
    assert result.memory is not None
    assert result.memory.epistemic_kind is EpistemicKind.DIRECT_SELF_REPORT
    assert "qualified_direct_state_evidence" in result.reasons


def test_quote_and_machine_interpretation_cannot_become_user_truth(
    service: CompanionMemoryService,
) -> None:
    result = service.remember(
        _state(
            "引用里写着我喜欢你",
            source_actor=EvidenceActor.THIRD_PARTY,
            quote_depth=1,
            reality_layer=RealityLayer.QUOTE,
            epistemic_kind=EpistemicKind.DIRECT_SELF_REPORT,
        )
    )
    assert result.action is StorageAction.CANDIDATE
    assert result.memory is not None
    assert result.memory.epistemic_kind is EpistemicKind.OBSERVATION
    assert result.memory.resolution_status is ResolutionStatus.CONTESTED


def test_leading_question_weak_confirmation_requires_review(
    service: CompanionMemoryService,
) -> None:
    result = service.remember(
        _state(
            "嗯，可能吧",
            epistemic_kind=EpistemicKind.DIRECT_SELF_REPORT,
            elicitation_kind=ElicitationKind.ASSISTANT_ASSERTION_CONFIRMATION,
        )
    )
    assert result.action is StorageAction.CANDIDATE
    assert result.memory is not None
    assert result.memory.resolution_status is ResolutionStatus.CONTESTED
    assert "weak_confirmation_requires_review" in result.reasons


def test_reviewed_but_contested_memory_is_context_only_not_an_answer(
    service: CompanionMemoryService,
) -> None:
    candidate = service.remember(
        _state(
            "嗯，可能喜欢吧",
            epistemic_kind=EpistemicKind.DIRECT_SELF_REPORT,
            elicitation_kind=ElicitationKind.ASSISTANT_ASSERTION_CONFIRMATION,
        )
    ).memory
    assert candidate is not None
    service.review(candidate.id, "alice", ReviewDecision.CONFIRM)

    context = service.recall(RecallRequest(user_id="alice", scope=SCOPE, query="可能喜欢"))

    recalled = [item for values in context.sections.values() for item in values]
    assert recalled[0].use_mode.value == "do_not_assert"
    assert context.retrieval_action is RetrievalAction.ABSTAIN


def test_valid_time_and_known_time_keep_correction_history(
    service: CompanionMemoryService,
) -> None:
    first = service.remember(_state("六月时我说我喜欢你")).memory
    assert first is not None
    second = service.remember(_state("六月那句是在演戏")).memory
    assert second is not None

    as_known_then = service.query_state(
        StateQuery(
            user_id="alice",
            scope=SCOPE,
            predicate="self_reported_affection",
            valid_at=JUNE,
            known_at=first.created_at,
        )
    )
    current = service.query_state(
        StateQuery(
            user_id="alice",
            scope=SCOPE,
            predicate="self_reported_affection",
            valid_at=JUNE,
        )
    )
    trajectory = service.query_state(
        StateQuery(
            user_id="alice",
            scope=SCOPE,
            predicate="self_reported_affection",
            valid_at=JUNE,
            semantics=AnswerSemantics.CHANGE_TRAJECTORY,
        )
    )

    assert [memory.id for memory in as_known_then.memories] == [first.id]
    assert [memory.id for memory in current.memories] == [second.id]
    assert {memory.id for memory in trajectory.memories} == {first.id, second.id}


def test_equal_state_values_with_different_titles_are_not_false_conflicts(
    service: CompanionMemoryService,
) -> None:
    first = service.remember(
        _state("我喜欢雨天", stable_key="weather-one", title="天气偏好")
    ).memory
    second = service.remember(
        _state("我喜欢雨天", stable_key="weather-two", title="下雨时的感受")
    ).memory
    assert first is not None and second is not None

    state = service.query_state(
        StateQuery(
            user_id="alice",
            scope=SCOPE,
            predicate="self_reported_affection",
            valid_at=JUNE,
        )
    )

    assert state.resolution_status is ResolutionStatus.RESOLVED


def test_quoted_explicit_directive_cannot_authorize_an_ordinary_memory(
    service: CompanionMemoryService,
) -> None:
    result = service.remember(
        MemoryInput(
            user_id="alice",
            scope=SCOPE,
            kind=MemoryKind.SHARED_MOMENT,
            title="引用中的指令",
            content="他写着：记住这件事",
            consent=ConsentState.GRANTED,
            explicit_user_request=True,
            source_actor=EvidenceActor.THIRD_PARTY,
            quote_depth=1,
            reality_layer=RealityLayer.QUOTE,
        )
    )

    assert result.action is StorageAction.CANDIDATE
    assert "ineligible_explicit_directive_downgraded" in result.reasons


def test_roleplay_contract_does_not_answer_real_world_state_query(
    service: CompanionMemoryService,
) -> None:
    service.remember(
        _state(
            "设定上我们是恋人",
            epistemic_kind=EpistemicKind.RELATIONSHIP_CONTRACT,
            reality_layer=RealityLayer.ROLEPLAY,
            predicate="relationship_contract",
        )
    )
    real = service.query_state(
        StateQuery(
            user_id="alice",
            scope=SCOPE,
            predicate="relationship_contract",
            semantics=AnswerSemantics.CONTRACT_AT_TIME,
        )
    )
    roleplay = service.query_state(
        StateQuery(
            user_id="alice",
            scope=SCOPE,
            predicate="relationship_contract",
            semantics=AnswerSemantics.CONTRACT_AT_TIME,
            reality_layer=RealityLayer.ROLEPLAY,
        )
    )
    assert real.resolution_status is ResolutionStatus.UNKNOWN
    assert roleplay.resolution_status is ResolutionStatus.RESOLVED


def test_identical_roleplay_and_real_world_text_remain_separate(
    service: CompanionMemoryService,
) -> None:
    roleplay = service.remember(
        _state(
            "设定上我们是恋人",
            stable_key="relationship:roleplay",
            epistemic_kind=EpistemicKind.RELATIONSHIP_CONTRACT,
            reality_layer=RealityLayer.ROLEPLAY,
            predicate="relationship_contract",
        )
    ).memory
    real_world = service.remember(
        _state(
            "设定上我们是恋人",
            stable_key="relationship:real-world",
            epistemic_kind=EpistemicKind.RELATIONSHIP_CONTRACT,
            reality_layer=RealityLayer.REAL_WORLD,
            predicate="relationship_contract",
        )
    ).memory

    assert roleplay is not None and real_world is not None
    assert roleplay.id != real_world.id


def test_unknown_state_can_show_raw_utterance_but_must_abstain(
    service: CompanionMemoryService,
) -> None:
    turn_scope = SCOPE.model_copy(update={"conversation_id": "conversation"})
    stored = service.append_turn(
        ConversationTurnInput(
            user_id="alice",
            scope=turn_scope,
            actor_id="alice",
            role=ConversationRole.USER,
            content="我现在不喜欢你",
            consent=ConsentState.GRANTED,
        )
    )
    assert stored.turn is not None

    context = service.recall(
        RecallRequest(
            user_id="alice",
            scope=turn_scope,
            query="我现在喜欢你吗",
            answer_semantics=AnswerSemantics.STATE_AT_VALID_TIME,
            state_predicate="self_reported_affection",
        )
    )

    assert context.state_result is not None
    assert context.state_result.resolution_status is ResolutionStatus.UNKNOWN
    assert context.turn_fallback
    assert context.retrieval_action is RetrievalAction.ABSTAIN


def test_state_fallback_does_not_treat_third_party_turn_as_user_evidence(
    service: CompanionMemoryService,
) -> None:
    turn_scope = SCOPE.model_copy(update={"conversation_id": "conversation"})
    stored = service.append_turn(
        ConversationTurnInput(
            user_id="alice",
            scope=turn_scope,
            actor_id="friend",
            role=ConversationRole.THIRD_PARTY,
            content="我现在喜欢你",
            consent=ConsentState.GRANTED,
        )
    )
    assert stored.turn is not None

    context = service.recall(
        RecallRequest(
            user_id="alice",
            scope=turn_scope,
            query="我现在喜欢你吗",
            answer_semantics=AnswerSemantics.STATE_AT_VALID_TIME,
            state_predicate="self_reported_affection",
        )
    )

    assert context.turn_fallback == []
    assert context.retrieval_action is RetrievalAction.ABSTAIN
