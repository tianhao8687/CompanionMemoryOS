from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from companion_memoryos.experience import build_response_beats, plan_memory_use
from companion_memoryos.schemas import (
    ConsentState,
    ConversationRepairRequest,
    ConversationRole,
    ConversationTurnInput,
    ExperienceEvidenceKind,
    FollowUpAction,
    FollowUpMode,
    FollowUpRequest,
    MemoryInput,
    MemoryKind,
    MemoryReferenceFeedbackInput,
    MemoryReferenceMode,
    MemoryScope,
    OpenLoopInput,
    OpenLoopKind,
    OpenLoopStatus,
    OpenLoopTransition,
    OpenLoopUpdateRequest,
    RecallIntent,
    RecallRequest,
    ReferenceFeedbackKind,
    RepairKind,
    ResponseBeatKind,
    ResponseBeatSentRequest,
    ResponseBeatStatus,
    ResponseDeliveryMode,
    ResponseGoal,
    ResponsePlanInterruptRequest,
    ResponsePlanRequest,
    ResponsePlanStatus,
    RetrievalAction,
)
from companion_memoryos.service import CompanionMemoryService

RELATIONSHIP_SCOPE = MemoryScope(
    companion_id="companion-a",
    relationship_id="relationship-a",
)
CONVERSATION_SCOPE = RELATIONSHIP_SCOPE.model_copy(update={"conversation_id": "conversation-a"})


def append_user_turn(
    service: CompanionMemoryService,
    content: str,
    *,
    retrieval_keys: list[str] | None = None,
    episode_id: str | None = None,
) -> str:
    result = service.append_turn(
        ConversationTurnInput(
            user_id="alice",
            scope=CONVERSATION_SCOPE,
            actor_id="alice",
            role=ConversationRole.USER,
            content=content,
            consent=ConsentState.GRANTED,
            retrieval_keys=retrieval_keys or [],
            episode_id=episode_id,
        )
    )
    assert result.turn is not None
    return result.turn.id


def remember_shared_moment(service: CompanionMemoryService, evidence_turn_id: str) -> str:
    result = service.remember(
        MemoryInput(
            user_id="alice",
            scope=CONVERSATION_SCOPE,
            kind=MemoryKind.SHARED_MOMENT,
            title="幸运叶子",
            content="在校门口捡到一片心形叶子，后来叫它幸运叶",
            consent=ConsentState.GRANTED,
            explicit_user_request=True,
            evidence_turn_ids=[evidence_turn_id],
        )
    )
    assert result.memory is not None
    return result.memory.id


def test_open_loop_waits_for_a_relevant_moment_and_stops_after_follow_up(
    service: CompanionMemoryService,
) -> None:
    source_turn_id = append_user_turn(service, "明天带团子去复查")
    now = datetime.now(UTC)
    stored = service.create_open_loop(
        OpenLoopInput(
            user_id="alice",
            scope=RELATIONSHIP_SCOPE,
            kind=OpenLoopKind.EVENT_OUTCOME,
            summary="团子的复查结果",
            topic_keys=["团子", "复查", "猫"],
            follow_up_mode=FollowUpMode.AT_OR_AFTER_TIME,
            follow_up_after=now - timedelta(minutes=1),
            opened_at=now - timedelta(minutes=1),
            source_turn_id=source_turn_id,
            consent=ConsentState.GRANTED,
        )
    )
    assert stored.open_loop is not None

    unrelated = service.evaluate_follow_up(
        FollowUpRequest(
            user_id="alice",
            scope=CONVERSATION_SCOPE,
            current_topic_keys=["工作"],
            as_of=now,
        )
    )
    relevant_but_busy = service.evaluate_follow_up(
        FollowUpRequest(
            user_id="alice",
            scope=CONVERSATION_SCOPE,
            current_topic_keys=["团子"],
            current_turn_requires_full_attention=True,
            as_of=now,
        )
    )
    relevant = service.evaluate_follow_up(
        FollowUpRequest(
            user_id="alice",
            scope=CONVERSATION_SCOPE,
            current_topic_keys=["团子"],
            as_of=now,
        )
    )

    assert unrelated.action is FollowUpAction.HOLD
    assert relevant_but_busy.action is FollowUpAction.HOLD
    assert relevant.action is FollowUpAction.ASK_NOW

    trigger_turn_id = append_user_turn(service, "团子今天有点没精神")
    plan = service.plan_response(
        ResponsePlanRequest(
            user_id="alice",
            scope=CONVERSATION_SCOPE,
            trigger_turn_id=trigger_turn_id,
            goal=ResponseGoal.CHECK_IN,
            current_topic_keys=["团子"],
            as_of=now,
        )
    )
    assert [beat.kind for beat in plan.beats] == [
        ResponseBeatKind.ACKNOWLEDGEMENT,
        ResponseBeatKind.FOLLOW_UP,
    ]
    for beat in plan.beats:
        plan = service.mark_response_beat_sent(
            plan.id,
            beat.id,
            ResponseBeatSentRequest(
                user_id="alice",
                rendered_text="团子现在怎么样？",
                task_policy_version=plan.policy_version,
                sent_at=now,
            ),
        )
    updated = service.list_open_loops(
        "alice", RELATIONSHIP_SCOPE, {OpenLoopStatus.WAITING_FOR_REPLY}
    )
    assert [item.id for item in updated] == [stored.open_loop.id]
    assert updated[0].follow_up_count == 1


def test_memory_is_used_silently_until_the_user_really_asks_for_it(
    service: CompanionMemoryService,
) -> None:
    evidence_turn_id = append_user_turn(service, "校门口那片心形叶子后来成了我的幸运叶")
    memory_id = remember_shared_moment(service, evidence_turn_id)

    ordinary_turn = append_user_turn(service, "明天还有一次面试")
    ordinary = service.plan_response(
        ResponsePlanRequest(
            user_id="alice",
            scope=CONVERSATION_SCOPE,
            trigger_turn_id=ordinary_turn,
            goal=ResponseGoal.COMFORT,
            recall_request=RecallRequest(
                user_id="alice",
                scope=CONVERSATION_SCOPE,
                query="幸运叶",
                intent=RecallIntent.COMFORT,
            ),
        )
    )
    ordinary_decision = next(
        item for item in ordinary.memory_use_plan.decisions if item.evidence.id == memory_id
    )
    assert ordinary_decision.mode is MemoryReferenceMode.SILENT_INFLUENCE
    assert all(beat.kind is not ResponseBeatKind.MEMORY_REFERENCE for beat in ordinary.beats)

    question_turn = append_user_turn(service, "你还记得我的幸运东西吗？")
    explicit = service.plan_response(
        ResponsePlanRequest(
            user_id="alice",
            scope=CONVERSATION_SCOPE,
            trigger_turn_id=question_turn,
            goal=ResponseGoal.DIRECT_ANSWER,
            recall_request=RecallRequest(
                user_id="alice",
                scope=CONVERSATION_SCOPE,
                query="幸运叶",
                intent=RecallIntent.REFLECT,
            ),
            user_asked_memory_question=True,
        )
    )
    explicit_decision = next(
        item for item in explicit.memory_use_plan.decisions if item.evidence.id == memory_id
    )
    assert explicit_decision.mode is MemoryReferenceMode.EXPLICIT_RECALL
    assert any(beat.kind is ResponseBeatKind.MEMORY_REFERENCE for beat in explicit.beats)


def test_sent_memory_is_not_repeated_in_the_same_conversation(
    service: CompanionMemoryService,
) -> None:
    conversation_started_at = datetime.now(UTC) - timedelta(minutes=1)
    evidence_turn_id = append_user_turn(service, "我的幸运叶是校门口捡到的心形叶子")
    memory_id = remember_shared_moment(service, evidence_turn_id)
    first_trigger = append_user_turn(service, "那片幸运叶你记得吗")
    first = service.plan_response(
        ResponsePlanRequest(
            user_id="alice",
            scope=CONVERSATION_SCOPE,
            trigger_turn_id=first_trigger,
            goal=ResponseGoal.DIRECT_ANSWER,
            recall_request=RecallRequest(
                user_id="alice",
                scope=CONVERSATION_SCOPE,
                query="幸运叶",
            ),
            user_asked_memory_question=True,
            conversation_started_at=conversation_started_at,
        )
    )
    for beat in first.beats:
        first = service.mark_response_beat_sent(
            first.id,
            beat.id,
            ResponseBeatSentRequest(
                user_id="alice",
                rendered_text="是校门口捡到的心形叶子。",
                task_policy_version=first.policy_version,
            ),
        )

    next_trigger = append_user_turn(service, "明天也带着它吧")
    second = service.plan_response(
        ResponsePlanRequest(
            user_id="alice",
            scope=CONVERSATION_SCOPE,
            trigger_turn_id=next_trigger,
            goal=ResponseGoal.COMFORT,
            recall_request=RecallRequest(
                user_id="alice",
                scope=CONVERSATION_SCOPE,
                query="幸运叶",
                intent=RecallIntent.COMFORT,
            ),
            conversation_started_at=conversation_started_at,
        )
    )
    decision = next(
        item for item in second.memory_use_plan.decisions if item.evidence.id == memory_id
    )
    assert decision.mode is MemoryReferenceMode.SILENT_INFLUENCE
    assert "already_referenced_in_conversation" in decision.reasons


def test_new_user_turn_cancels_unsent_semantic_beats(
    service: CompanionMemoryService,
) -> None:
    trigger_turn_id = append_user_turn(service, "我今天有点累")
    plan = service.plan_response(
        ResponsePlanRequest(
            user_id="alice",
            scope=CONVERSATION_SCOPE,
            trigger_turn_id=trigger_turn_id,
            goal=ResponseGoal.COMFORT,
            allow_afterthought=True,
        )
    )
    assert plan.status.value == "active"

    next_turn = service.append_turn(
        ConversationTurnInput(
            user_id="alice",
            scope=CONVERSATION_SCOPE,
            actor_id="alice",
            role=ConversationRole.USER,
            content="算了，我想说另一件事",
            consent=ConsentState.GRANTED,
        )
    )

    assert next_turn.cancelled_response_plan_ids == [plan.id]
    assert service.get_response_plan(plan.id, "alice").status.value == "cancelled"


def test_natural_wrong_reference_feedback_suppresses_the_next_callback(
    service: CompanionMemoryService,
) -> None:
    evidence_turn_id = append_user_turn(service, "校门口捡到一片心形叶子")
    memory_id = remember_shared_moment(service, evidence_turn_id)
    repair_turn_id = append_user_turn(service, "不是那件事，你串了")
    result = service.apply_repair(
        ConversationRepairRequest(
            user_id="alice",
            scope=CONVERSATION_SCOPE,
            kind=RepairKind.WRONG_REFERENCE,
            source_turn_id=repair_turn_id,
            memory_id=memory_id,
        )
    )
    assert result.applied is True
    assert "不要展示内部记录" in result.acknowledgement_guidance

    next_turn_id = append_user_turn(service, "我说的是另一个幸运东西")
    plan = service.plan_response(
        ResponsePlanRequest(
            user_id="alice",
            scope=CONVERSATION_SCOPE,
            trigger_turn_id=next_turn_id,
            goal=ResponseGoal.DIRECT_ANSWER,
            recall_request=RecallRequest(
                user_id="alice",
                scope=CONVERSATION_SCOPE,
                query="幸运东西",
            ),
            user_asked_memory_question=True,
        )
    )
    decision = next(
        item for item in plan.memory_use_plan.decisions if item.evidence.id == memory_id
    )
    assert decision.mode is MemoryReferenceMode.SUPPRESS


def test_raw_turn_retrieval_keys_embeddings_and_episode_diversity(
    service: CompanionMemoryService,
) -> None:
    first = service.append_turn(
        ConversationTurnInput(
            user_id="alice",
            scope=CONVERSATION_SCOPE,
            actor_id="alice",
            role=ConversationRole.USER,
            content="在校门口捡到一片心形叶子",
            consent=ConsentState.GRANTED,
            retrieval_keys=["幸运东西", "低谷时期的象征"],
            embedding=[1.0, 0.0],
            embedding_space="experience-test",
            episode_id="episode:heart-leaf",
        )
    ).turn
    second = service.append_turn(
        ConversationTurnInput(
            user_id="alice",
            scope=CONVERSATION_SCOPE,
            actor_id="alice",
            role=ConversationRole.USER,
            content="后来我一直把那片叶子夹在本子里",
            consent=ConsentState.GRANTED,
            retrieval_keys=["幸运东西"],
            embedding=[1.0, 0.0],
            embedding_space="experience-test",
            episode_id="episode:heart-leaf",
        )
    ).turn
    assert first is not None and second is not None

    context = service.recall(
        RecallRequest(
            user_id="alice",
            scope=CONVERSATION_SCOPE,
            query="我捡到的那个幸运东西",
            query_embedding=[1.0, 0.0],
            embedding_space="experience-test",
            event_limit=0,
        )
    )

    matching = [
        item for item in context.turn_fallback if item.turn.episode_id == "episode:heart-leaf"
    ]
    assert len(matching) == 1
    assert matching[0].semantic == 1.0
    assert "semantic_match" in matching[0].reasons


def test_retrieval_key_can_find_an_unextracted_turn_without_an_embedding(
    service: CompanionMemoryService,
) -> None:
    turn_id = append_user_turn(
        service,
        "校门口捡到了心形叶子",
        retrieval_keys=["幸运东西"],
    )
    context = service.recall(
        RecallRequest(
            user_id="alice",
            scope=CONVERSATION_SCOPE,
            query="幸运东西",
            event_limit=0,
        )
    )
    item = next(item for item in context.turn_fallback if item.turn.id == turn_id)
    assert "retrieval_key_match" in item.reasons
    assert item.evidence_text == "校门口捡到了心形叶子"
    assert "幸运东西" not in item.evidence_text


def test_wrong_reference_can_target_a_raw_turn_without_a_memory_card(
    service: CompanionMemoryService,
) -> None:
    turn_id = append_user_turn(service, "奶奶送的蓝色杯子")
    correction_id = append_user_turn(service, "我说的不是奶奶送的那个")
    repaired = service.apply_repair(
        ConversationRepairRequest(
            user_id="alice",
            scope=CONVERSATION_SCOPE,
            source_turn_id=correction_id,
            kind=RepairKind.WRONG_REFERENCE,
            evidence_kind=ExperienceEvidenceKind.TURN,
            evidence_id=turn_id,
        )
    )
    assert repaired.reference_feedback is not None
    assert repaired.reference_feedback.evidence_id == turn_id
    assert repaired.reference_feedback.memory_id is None

    plan = service.plan_response(
        ResponsePlanRequest(
            user_id="alice",
            scope=CONVERSATION_SCOPE,
            trigger_turn_id=correction_id,
            goal=ResponseGoal.DIRECT_ANSWER,
            user_asked_memory_question=True,
            recall_request=RecallRequest(
                user_id="alice", scope=CONVERSATION_SCOPE, query="奶奶送的蓝色杯子"
            ),
        )
    )
    decision = next(item for item in plan.memory_use_plan.decisions if item.evidence.id == turn_id)
    assert decision.mode is MemoryReferenceMode.SUPPRESS
    assert all(turn_id not in [ref.id for ref in beat.evidence] for beat in plan.beats)


def test_feedback_on_raw_evidence_also_suppresses_a_derived_memory(
    service: CompanionMemoryService,
) -> None:
    evidence_id = append_user_turn(service, "幸运叶子是在校门口捡到的")
    memory_id = remember_shared_moment(service, evidence_id)
    service.record_reference_feedback(
        MemoryReferenceFeedbackInput(
            user_id="alice",
            scope=CONVERSATION_SCOPE,
            evidence_kind=ExperienceEvidenceKind.TURN,
            evidence_id=evidence_id,
            kind=ReferenceFeedbackKind.DO_NOT_REFERENCE,
        )
    )
    trigger_id = append_user_turn(service, "说说幸运叶子")
    plan = service.plan_response(
        ResponsePlanRequest(
            user_id="alice",
            scope=CONVERSATION_SCOPE,
            trigger_turn_id=trigger_id,
            goal=ResponseGoal.REFLECT,
            user_asked_memory_question=True,
            recall_request=RecallRequest(
                user_id="alice", scope=CONVERSATION_SCOPE, query="幸运叶子"
            ),
        )
    )
    decision = next(
        item for item in plan.memory_use_plan.decisions if item.evidence.id == memory_id
    )
    assert decision.mode is MemoryReferenceMode.SUPPRESS


def test_incidental_ambiguity_does_not_turn_comfort_into_a_confirmation_form(
    service: CompanionMemoryService,
) -> None:
    evidence_id = append_user_turn(service, "我的幸运叶子")
    remember_shared_moment(service, evidence_id)
    trigger_id = append_user_turn(service, "我今天只是想找你聊聊")
    context = service.recall(
        RecallRequest(user_id="alice", scope=CONVERSATION_SCOPE, query="幸运叶子")
    ).model_copy(update={"retrieval_action": RetrievalAction.CLARIFY})
    request = ResponsePlanRequest(
        user_id="alice",
        scope=CONVERSATION_SCOPE,
        trigger_turn_id=trigger_id,
        goal=ResponseGoal.LISTEN,
    )
    use_plan = plan_memory_use(context, request, {}, set(), service.config)
    beats = build_response_beats(request, ResponseDeliveryMode.SEMANTIC_BEATS, use_plan, None)
    assert use_plan.decisions
    assert all(item.mode is not MemoryReferenceMode.CLARIFY for item in use_plan.decisions)
    assert all(beat.kind is not ResponseBeatKind.CLARIFICATION for beat in beats)


def test_missing_memory_gets_an_honest_gap_beat_not_a_made_up_answer(
    service: CompanionMemoryService,
) -> None:
    trigger_id = append_user_turn(service, "那个我没讲过的小事你记得吗？")
    plan = service.plan_response(
        ResponsePlanRequest(
            user_id="alice",
            scope=CONVERSATION_SCOPE,
            trigger_turn_id=trigger_id,
            goal=ResponseGoal.DIRECT_ANSWER,
            user_asked_memory_question=True,
        )
    )
    assert [beat.kind for beat in plan.beats] == [
        ResponseBeatKind.ACKNOWLEDGEMENT,
        ResponseBeatKind.MEMORY_GAP,
    ]
    assert "不能提前声称记得" in plan.beats[0].guidance


def test_current_memory_question_cannot_supply_its_own_historical_evidence(
    service: CompanionMemoryService,
) -> None:
    question = "你记得我说过的紫色星星糖果吗"
    trigger_id = append_user_turn(service, question)
    plan = service.plan_response(
        ResponsePlanRequest(
            user_id="alice",
            scope=CONVERSATION_SCOPE,
            trigger_turn_id=trigger_id,
            goal=ResponseGoal.DIRECT_ANSWER,
            user_asked_memory_question=True,
            recall_request=RecallRequest(user_id="alice", scope=CONVERSATION_SCOPE, query=question),
        )
    )
    assert all(item.evidence.id != trigger_id for item in plan.memory_use_plan.decisions)
    assert any(beat.kind is ResponseBeatKind.MEMORY_GAP for beat in plan.beats)
    assert plan.config_fingerprint == service.config.fingerprint()
    assert plan.policy_bundle.production_eligible is False


def test_idempotent_redelivery_does_not_interrupt_a_reply_to_that_turn(
    service: CompanionMemoryService,
) -> None:
    delivery = ConversationTurnInput(
        user_id="alice",
        scope=CONVERSATION_SCOPE,
        actor_id="alice",
        role=ConversationRole.USER,
        content="今天想慢慢聊",
        consent=ConsentState.GRANTED,
        idempotency_key="same-provider-delivery",
    )
    first = service.append_turn(delivery)
    assert first.turn is not None
    plan = service.plan_response(
        ResponsePlanRequest(
            user_id="alice",
            scope=CONVERSATION_SCOPE,
            trigger_turn_id=first.turn.id,
            goal=ResponseGoal.LISTEN,
        )
    )
    replay = service.append_turn(delivery)
    assert replay.duplicate_of == first.turn.id
    assert replay.cancelled_response_plan_ids == []
    assert service.get_response_plan(plan.id, "alice").status is ResponsePlanStatus.ACTIVE


def test_single_message_channels_receive_one_beat_even_with_afterthought_enabled(
    service: CompanionMemoryService,
) -> None:
    trigger_id = append_user_turn(service, "我有点累，先听我说就好")
    request = ResponsePlanRequest(
        user_id="alice",
        scope=CONVERSATION_SCOPE,
        trigger_turn_id=trigger_id,
        goal=ResponseGoal.LISTEN,
        channel_supports_multiple_beats=False,
        allow_afterthought=True,
    )
    plan = service.plan_response(request)
    assert plan.delivery_mode is ResponseDeliveryMode.SINGLE_MESSAGE
    assert len(plan.beats) == 1
    assert plan.beats[0].kind is ResponseBeatKind.COMPOSED_RESPONSE


def test_optional_afterthought_needs_a_host_signal_and_receipt_is_idempotent(
    service: CompanionMemoryService,
) -> None:
    trigger_id = append_user_turn(service, "今天有点不顺")
    plan = service.plan_response(
        ResponsePlanRequest(
            user_id="alice",
            scope=CONVERSATION_SCOPE,
            trigger_turn_id=trigger_id,
            goal=ResponseGoal.COMFORT,
            allow_afterthought=True,
        )
    )
    plan = service.mark_response_beat_sent(
        plan.id,
        plan.beats[0].id,
        ResponseBeatSentRequest(
            user_id="alice", rendered_text="我在听。", task_policy_version=plan.policy_version
        ),
    )
    afterthought = plan.beats[-1]
    assert afterthought.status is ResponseBeatStatus.PENDING
    receipt = ResponseBeatSentRequest(
        user_id="alice",
        rendered_text="不必急着解释清楚。",
        task_policy_version=plan.policy_version,
    )
    with pytest.raises(ValueError, match="host release signal"):
        service.mark_response_beat_sent(plan.id, afterthought.id, receipt)
    accepted = receipt.model_copy(update={"host_release_signal": True})
    completed = service.mark_response_beat_sent(plan.id, afterthought.id, accepted)
    replayed = service.mark_response_beat_sent(plan.id, afterthought.id, accepted)
    assert completed.status is ResponsePlanStatus.COMPLETED
    assert replayed == completed
    with pytest.raises(ValueError, match="different text"):
        service.mark_response_beat_sent(
            plan.id,
            afterthought.id,
            accepted.model_copy(update={"rendered_text": "另一段话"}),
        )


def test_delayed_planner_cannot_create_a_reply_for_an_outdated_user_turn(
    service: CompanionMemoryService,
) -> None:
    old_trigger = append_user_turn(service, "我想聊聊昨天")
    append_user_turn(service, "先不聊了，说另外一件事")
    with pytest.raises(ValueError, match="newer user turn"):
        service.plan_response(
            ResponsePlanRequest(
                user_id="alice",
                scope=CONVERSATION_SCOPE,
                trigger_turn_id=old_trigger,
                goal=ResponseGoal.REFLECT,
            )
        )


def test_resolved_open_loop_invalidates_an_unsent_follow_up(
    service: CompanionMemoryService,
) -> None:
    trigger_id = append_user_turn(service, "今天面试结束了")
    stored = service.create_open_loop(
        OpenLoopInput(
            user_id="alice",
            scope=RELATIONSHIP_SCOPE,
            kind=OpenLoopKind.EVENT_OUTCOME,
            summary="面试的结果",
            topic_keys=["面试"],
            consent=ConsentState.GRANTED,
            source_turn_id=trigger_id,
        )
    )
    assert stored.open_loop is not None
    plan = service.plan_response(
        ResponsePlanRequest(
            user_id="alice",
            scope=CONVERSATION_SCOPE,
            trigger_turn_id=trigger_id,
            goal=ResponseGoal.CHECK_IN,
            current_topic_keys=["面试"],
        )
    )
    service.mark_response_beat_sent(
        plan.id,
        plan.beats[0].id,
        ResponseBeatSentRequest(
            user_id="alice", rendered_text="辛苦了。", task_policy_version=plan.policy_version
        ),
    )
    service.update_open_loop(
        stored.open_loop.id,
        OpenLoopUpdateRequest(
            user_id="alice",
            transition=OpenLoopTransition.RESOLVE,
            expected_revision=stored.open_loop.revision,
            resolution_summary="用户已说通过了",
        ),
    )
    follow_up_beat = next(beat for beat in plan.beats if beat.kind is ResponseBeatKind.FOLLOW_UP)
    with pytest.raises(ValueError, match="follow-up changed"):
        service.mark_response_beat_sent(
            plan.id,
            follow_up_beat.id,
            ResponseBeatSentRequest(
                user_id="alice",
                rendered_text="面试结果怎么样？",
                task_policy_version=plan.policy_version,
            ),
        )


def test_non_archived_input_can_interrupt_pending_beats(
    service: CompanionMemoryService,
) -> None:
    trigger_id = append_user_turn(service, "听我说就好")
    plan = service.plan_response(
        ResponsePlanRequest(
            user_id="alice",
            scope=CONVERSATION_SCOPE,
            trigger_turn_id=trigger_id,
            goal=ResponseGoal.LISTEN,
        )
    )
    turn_count = len(service.list_turns("alice", CONVERSATION_SCOPE))
    cancelled = service.interrupt_response_plans(
        ResponsePlanInterruptRequest(user_id="alice", scope=CONVERSATION_SCOPE)
    )
    assert cancelled == [plan.id]
    assert len(service.list_turns("alice", CONVERSATION_SCOPE)) == turn_count
    assert service.get_response_plan(plan.id, "alice").status is ResponsePlanStatus.CANCELLED


def test_sent_raw_turn_is_not_repeated_without_a_fresh_memory_question(
    service: CompanionMemoryService,
) -> None:
    evidence_id = append_user_turn(service, "奶奶送给我的蓝色杯子")
    trigger_id = append_user_turn(service, "你还记得那次礼物吗")
    recall = RecallRequest(user_id="alice", scope=CONVERSATION_SCOPE, query="奶奶送给我的蓝色杯子")
    plan = service.plan_response(
        ResponsePlanRequest(
            user_id="alice",
            scope=CONVERSATION_SCOPE,
            trigger_turn_id=trigger_id,
            goal=ResponseGoal.REFLECT,
            user_asked_memory_question=True,
            recall_request=recall,
        )
    )
    assert any(ref.id == evidence_id for beat in plan.beats for ref in beat.evidence)
    for beat in plan.beats:
        service.mark_response_beat_sent(
            plan.id,
            beat.id,
            ResponseBeatSentRequest(
                user_id="alice",
                rendered_text="是奶奶送的那只蓝色杯子。",
                task_policy_version=plan.policy_version,
            ),
        )
    next_id = append_user_turn(service, "嗯，我想继续聊聊奶奶")
    next_plan = service.plan_response(
        ResponsePlanRequest(
            user_id="alice",
            scope=CONVERSATION_SCOPE,
            trigger_turn_id=next_id,
            goal=ResponseGoal.REFLECT,
            recall_request=recall.model_copy(update={"intent": RecallIntent.REFLECT}),
        )
    )
    decision = next(
        item for item in next_plan.memory_use_plan.decisions if item.evidence.id == evidence_id
    )
    assert decision.mode is MemoryReferenceMode.SILENT_INFLUENCE
    assert "already_referenced_in_conversation" in decision.reasons
