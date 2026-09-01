from __future__ import annotations

from uuid import uuid4

import pytest

from companion_memoryos.schemas import (
    AutomaticActionStatus,
    ConsentState,
    ConversationRole,
    ConversationTurnInput,
    DiscourseInterpretationStatus,
    DiscourseInterpretRequest,
    DiscourseSignal,
    InterpretedResponsePlanRequest,
    MemoryInput,
    MemoryKind,
    MemoryScope,
    OpenLoopInput,
    OpenLoopKind,
    OpenLoopStatus,
    RealityLayer,
    RecallRequest,
    ResponseBeatSentRequest,
    ResponseGoal,
    ResponsePlanRequest,
    ResponsePlanResolutionStatus,
    ResponsePlanResolveRequest,
    ResponsePlanStatus,
    SpeechAct,
    SpeechSpan,
)
from companion_memoryos.service import CompanionMemoryService

SCOPE = MemoryScope(
    companion_id="companion-a",
    relationship_id="relationship-a",
    conversation_id="conversation-a",
)


def append_user_turn(service: CompanionMemoryService, content: str) -> str:
    result = service.append_turn(
        ConversationTurnInput(
            user_id="alice",
            scope=SCOPE,
            actor_id="alice",
            role=ConversationRole.USER,
            content=content,
            consent=ConsentState.GRANTED,
        )
    )
    assert result.turn is not None
    return result.turn.id


def test_interpreted_entry_turns_explicit_listen_language_into_an_immediate_plan(
    service: CompanionMemoryService,
) -> None:
    turn_id = append_user_turn(service, "你先听我说完，别给建议")
    result = service.stage_interpreted_response_plan(
        InterpretedResponsePlanRequest(user_id="alice", scope=SCOPE, turn_id=turn_id)
    )
    assert result.interpretation.signals == [DiscourseSignal.LISTEN_ONLY]
    assert result.interpretation.suggested_goal is ResponseGoal.LISTEN
    assert result.interpretation.current_turn_requires_full_attention is True
    assert result.plan.resolution_status is ResponsePlanResolutionStatus.PENDING
    assert result.plan.revision == 0
    assert len(result.plan.beats) == 1
    assert result.plan.beats[0].source.value == "current_turn"


def test_conflicting_explicit_control_language_is_not_silently_decided(
    service: CompanionMemoryService,
) -> None:
    turn_id = append_user_turn(service, "先别给建议，不过想了想你还是给我建议吧")
    result = service.interpret_turn(
        DiscourseInterpretRequest(
            user_id="alice", scope=SCOPE, turn_id=turn_id, apply_low_risk_actions=False
        )
    )
    assert result.status is DiscourseInterpretationStatus.CONFLICTING
    assert result.suggested_goal is None
    assert result.current_turn_requires_full_attention is True


def test_wrong_reference_without_a_unique_sent_target_requests_natural_disambiguation(
    service: CompanionMemoryService,
) -> None:
    turn_id = append_user_turn(service, "不是那个，你记错了")
    result = service.interpret_turn(
        DiscourseInterpretRequest(user_id="alice", scope=SCOPE, turn_id=turn_id)
    )
    assert result.automatic_action_status is AutomaticActionStatus.NEEDS_TARGET
    assert result.repair is None


def test_quoted_control_language_does_not_operate_the_users_runtime(
    service: CompanionMemoryService,
) -> None:
    quoted = "她发来的原话：以后别提这件事"
    result = service.append_turn(
        ConversationTurnInput(
            user_id="alice",
            scope=SCOPE,
            actor_id="alice",
            role=ConversationRole.USER,
            content=quoted,
            consent=ConsentState.GRANTED,
            speech_spans=[
                SpeechSpan(
                    start_offset=7,
                    end_offset=len(quoted),
                    quote_depth=1,
                    attributed_speaker_id="other-person",
                    reality_layer=RealityLayer.QUOTE,
                    speech_act=SpeechAct.QUOTE,
                    machine_generated=False,
                )
            ],
        )
    )
    assert result.turn is not None
    interpreted = service.interpret_turn(
        DiscourseInterpretRequest(user_id="alice", scope=SCOPE, turn_id=result.turn.id)
    )
    assert DiscourseSignal.STOP_REFERENCING not in interpreted.signals


def test_reported_outcome_closes_only_one_topic_matched_open_loop(
    service: CompanionMemoryService,
) -> None:
    source_turn_id = append_user_turn(service, "明天有一场考试")
    stored = service.create_open_loop(
        OpenLoopInput(
            user_id="alice",
            scope=SCOPE,
            kind=OpenLoopKind.EVENT_OUTCOME,
            summary="考试结果",
            topic_keys=["考试"],
            source_turn_id=source_turn_id,
            consent=ConsentState.GRANTED,
        )
    )
    assert stored.open_loop is not None
    outcome_turn_id = append_user_turn(service, "已经考完了")
    result = service.interpret_turn(
        DiscourseInterpretRequest(
            user_id="alice",
            scope=SCOPE,
            turn_id=outcome_turn_id,
            current_topic_keys=["考试"],
        )
    )
    assert result.automatic_action_status is AutomaticActionStatus.APPLIED
    assert result.repair is not None
    assert result.repair.open_loop is not None
    assert result.repair.open_loop.status is OpenLoopStatus.RESOLVED


def test_staged_plan_can_send_ack_before_retrieval_and_resolve_idempotently(
    service: CompanionMemoryService,
) -> None:
    evidence_turn_id = append_user_turn(service, "奶奶送给我一个蓝色杯子")
    stored = service.remember(
        MemoryInput(
            user_id="alice",
            scope=SCOPE,
            kind=MemoryKind.SHARED_MOMENT,
            title="蓝色杯子",
            content="奶奶送给用户一个蓝色杯子",
            consent=ConsentState.GRANTED,
            explicit_user_request=True,
            evidence_turn_ids=[evidence_turn_id],
        )
    )
    assert stored.memory is not None
    trigger_id = append_user_turn(service, "你还记得那个蓝色杯子吗")
    staged = service.stage_response_plan(
        ResponsePlanRequest(
            user_id="alice",
            scope=SCOPE,
            trigger_turn_id=trigger_id,
            goal=ResponseGoal.REFLECT,
            recall_request=RecallRequest(user_id="alice", scope=SCOPE, query="蓝色杯子"),
            user_asked_memory_question=True,
        )
    )
    after_ack = service.mark_response_beat_sent(
        staged.id,
        staged.beats[0].id,
        ResponseBeatSentRequest(
            user_id="alice",
            rendered_text="等一下，我想想你说的是哪次。",
            task_policy_version=staged.policy_version,
        ),
    )
    assert after_ack.status is ResponsePlanStatus.ACTIVE
    assert after_ack.resolution_status is ResponsePlanResolutionStatus.PENDING

    resolution_key = str(uuid4())
    request = ResponsePlanResolveRequest(
        user_id="alice",
        expected_revision=0,
        resolution_key=resolution_key,
    )
    resolved = service.resolve_staged_response_plan(staged.id, request)
    replayed = service.resolve_staged_response_plan(staged.id, request)
    assert resolved == replayed
    assert resolved.revision == 1
    assert resolved.resolution_status is ResponsePlanResolutionStatus.RESOLVED
    assert len(resolved.beats) > 1
    assert resolved.beats[1].status.value == "ready"


def test_new_user_turn_invalidates_a_pending_retrieval_result(
    service: CompanionMemoryService,
) -> None:
    trigger_id = append_user_turn(service, "你还记得上次那件事吗")
    staged = service.stage_response_plan(
        ResponsePlanRequest(
            user_id="alice",
            scope=SCOPE,
            trigger_turn_id=trigger_id,
            goal=ResponseGoal.REFLECT,
            recall_request=RecallRequest(user_id="alice", scope=SCOPE, query="上次那件事"),
            user_asked_memory_question=True,
        )
    )
    append_user_turn(service, "算了，换个话题")
    with pytest.raises(ValueError, match="cancelled or completed"):
        service.resolve_staged_response_plan(
            staged.id,
            ResponsePlanResolveRequest(
                user_id="alice", expected_revision=0, resolution_key=str(uuid4())
            ),
        )


def test_explicit_wrong_reference_uses_the_last_single_sent_evidence(
    service: CompanionMemoryService,
) -> None:
    evidence_turn_id = append_user_turn(service, "校门口捡到一片心形叶子")
    stored = service.remember(
        MemoryInput(
            user_id="alice",
            scope=SCOPE,
            kind=MemoryKind.SHARED_MOMENT,
            title="心形叶子",
            content="在校门口捡到一片心形叶子",
            consent=ConsentState.GRANTED,
            explicit_user_request=True,
            evidence_turn_ids=[evidence_turn_id],
        )
    )
    assert stored.memory is not None
    trigger_id = append_user_turn(service, "你还记得幸运东西吗")
    plan = service.plan_response(
        ResponsePlanRequest(
            user_id="alice",
            scope=SCOPE,
            trigger_turn_id=trigger_id,
            goal=ResponseGoal.REFLECT,
            recall_request=RecallRequest(user_id="alice", scope=SCOPE, query="心形叶子"),
            user_asked_memory_question=True,
        )
    )
    for beat in plan.beats:
        plan = service.mark_response_beat_sent(
            plan.id,
            beat.id,
            ResponseBeatSentRequest(
                user_id="alice",
                rendered_text="我想到心形叶子那次。",
                task_policy_version=plan.policy_version,
            ),
        )
    correction_turn_id = append_user_turn(service, "不是那个，你记错了")
    interpreted = service.interpret_turn(
        DiscourseInterpretRequest(
            user_id="alice",
            scope=SCOPE,
            turn_id=correction_turn_id,
        )
    )
    assert interpreted.automatic_action_status is AutomaticActionStatus.APPLIED
    assert interpreted.repair is not None
    assert interpreted.repair.reference_feedback is not None
    assert interpreted.repair.reference_feedback.evidence_id == stored.memory.id
