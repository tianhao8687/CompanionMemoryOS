from __future__ import annotations

from collections.abc import Iterable
from uuid import uuid4

from companion_memoryos.config import CompanionConfig
from companion_memoryos.schemas import (
    BeatReleaseCondition,
    CompanionContext,
    ExperienceEvidenceKind,
    ExperienceEvidenceRef,
    FollowUpAction,
    FollowUpDecision,
    FollowUpMode,
    FollowUpRequest,
    MemoryKind,
    MemoryReferenceFeedbackRecord,
    MemoryReferenceMode,
    MemoryUseDecision,
    MemoryUsePlan,
    OpenLoopRecord,
    OpenLoopStatus,
    RecallIntent,
    RecallUseMode,
    ReferenceFeedbackKind,
    ResolutionStatus,
    ResponseBeatKind,
    ResponseBeatRecord,
    ResponseBeatSource,
    ResponseBeatStatus,
    ResponseDeliveryMode,
    ResponseGoal,
    ResponsePlanRequest,
    RetrievalAction,
)

SILENT_MEMORY_KINDS = {
    MemoryKind.IDENTITY,
    MemoryKind.PREFERENCE,
    MemoryKind.BOUNDARY,
    MemoryKind.SUPPORT_STRATEGY,
    MemoryKind.RITUAL,
    MemoryKind.WELLBEING_SIGNAL,
    MemoryKind.RELATIONSHIP,
}

NATURAL_CALLBACK_INTENTS = {
    RecallIntent.CELEBRATE,
    RecallIntent.REFLECT,
    RecallIntent.CHECK_IN,
}

SUPPRESSING_FEEDBACK = {
    ReferenceFeedbackKind.WRONG_MATCH,
    ReferenceFeedbackKind.BAD_TIMING,
    ReferenceFeedbackKind.TOO_REPETITIVE,
    ReferenceFeedbackKind.DO_NOT_REFERENCE,
}

GOAL_GUIDANCE: dict[ResponseGoal, str] = {
    ResponseGoal.DIRECT_ANSWER: "直接回应用户当前的问题；不要先展示记忆检索过程。",
    ResponseGoal.LISTEN: "先接住用户刚说的话，给对方继续表达的空间，不急着总结或建议。",
    ResponseGoal.COMFORT: "先回应此刻的感受，再决定旧经历是否有必要出现。",
    ResponseGoal.CELEBRATE: "先分享用户此刻的高兴，历史只能自然增加连续感。",
    ResponseGoal.REFLECT: "跟随用户一起梳理，不用旧记忆替用户下结论。",
    ResponseGoal.PROBLEM_SOLVE: "先处理眼前最需要解决的部分，记忆只补充真正相关的约束。",
    ResponseGoal.CHECK_IN: "用简短、具体且容易拒绝的方式询问后续，不连续追问。",
}


def decide_follow_up(
    open_loops: Iterable[OpenLoopRecord], request: FollowUpRequest
) -> FollowUpDecision:
    considered: list[str] = []
    held: OpenLoopRecord | None = None
    topics = set(request.current_topic_keys)
    for open_loop in open_loops:
        if open_loop.status in {OpenLoopStatus.RESOLVED, OpenLoopStatus.CANCELLED}:
            continue
        if open_loop.opened_at > request.as_of:
            continue
        considered.append(open_loop.id)
        if open_loop.expires_at is not None and open_loop.expires_at <= request.as_of:
            continue
        if open_loop.status is OpenLoopStatus.WAITING_FOR_REPLY:
            held = held or open_loop
            continue
        due = open_loop.follow_up_after is None or open_loop.follow_up_after <= request.as_of
        if not due:
            held = held or open_loop
            continue
        topic_match = bool(topics & set(open_loop.topic_keys))
        user_led = request.reopened_open_loop_id == open_loop.id or (
            request.user_reopened_topic and topic_match
        )
        relevant = user_led or topic_match
        if open_loop.follow_up_mode is FollowUpMode.NEVER:
            continue
        if open_loop.follow_up_mode is FollowUpMode.USER_LED and not user_led:
            held = held or open_loop
            continue
        if open_loop.follow_up_mode is FollowUpMode.WHEN_RELEVANT and not relevant:
            held = held or open_loop
            continue
        if (
            open_loop.follow_up_mode is FollowUpMode.AT_OR_AFTER_TIME
            and not request.allow_due_topic_switch
            and not relevant
        ):
            held = held or open_loop
            continue
        if request.current_turn_requires_full_attention:
            return FollowUpDecision(
                action=FollowUpAction.HOLD,
                candidate=open_loop,
                considered_open_loop_ids=considered,
                reasons=["current_turn_has_priority"],
                response_guidance="先完整回应当前话题，本轮不要切换到旧事项。",
            )
        return FollowUpDecision(
            action=FollowUpAction.ASK_NOW,
            candidate=open_loop,
            considered_open_loop_ids=considered,
            reasons=["due_and_contextually_relevant"],
            response_guidance=(
                "用一句自然、具体且允许用户不回答的话询问后续；不要说明它来自任务队列。"
            ),
        )
    if held is not None:
        return FollowUpDecision(
            action=FollowUpAction.HOLD,
            candidate=held,
            considered_open_loop_ids=considered,
            reasons=["open_loop_exists_but_not_right_now"],
            response_guidance="保留这条未完成事项，本轮不主动提起。",
        )
    return FollowUpDecision(
        action=FollowUpAction.NONE,
        considered_open_loop_ids=considered,
        reasons=["no_eligible_open_loop"],
    )


def plan_memory_use(
    context: CompanionContext | None,
    request: ResponsePlanRequest,
    feedback_by_evidence: dict[tuple[ExperienceEvidenceKind, str], MemoryReferenceFeedbackRecord],
    repeated_evidence: set[tuple[ExperienceEvidenceKind, str]],
    config: CompanionConfig,
) -> MemoryUsePlan:
    if context is None:
        return MemoryUsePlan(guidance=["本轮没有请求历史证据，只根据当前对话回应。"])

    decisions: list[MemoryUseDecision] = []
    blocked_source_turn_ids = {
        evidence_id
        for (kind, evidence_id), feedback in feedback_by_evidence.items()
        if kind is ExperienceEvidenceKind.TURN and feedback.kind in SUPPRESSING_FEEDBACK
    }
    for items in context.sections.values():
        for memory_item in items:
            memory = memory_item.memory
            mode, reasons = _memory_mode(
                memory_item.use_mode,
                memory.kind,
                memory.id,
                context,
                request,
                feedback_by_evidence,
                repeated_evidence,
                config,
            )
            if blocked_source_turn_ids.intersection(memory.evidence_turn_ids):
                mode, reasons = MemoryReferenceMode.SUPPRESS, ["user_feedback_on_source_turn"]
            decisions.append(
                MemoryUseDecision(
                    evidence=ExperienceEvidenceRef(
                        kind=ExperienceEvidenceKind.MEMORY,
                        id=memory.id,
                    ),
                    mode=mode,
                    reasons=reasons,
                )
            )

    decided_memory_ids = {
        item.evidence.id
        for item in decisions
        if item.evidence.kind is ExperienceEvidenceKind.MEMORY
    }
    if context.state_result is not None:
        state_mode = (
            RecallUseMode.NATURAL
            if context.state_result.resolution_status is ResolutionStatus.RESOLVED
            else RecallUseMode.DO_NOT_ASSERT
        )
        for memory in context.state_result.memories:
            if memory.id in decided_memory_ids:
                continue
            mode, reasons = _memory_mode(
                state_mode,
                memory.kind,
                memory.id,
                context,
                request,
                feedback_by_evidence,
                repeated_evidence,
                config,
            )
            if blocked_source_turn_ids.intersection(memory.evidence_turn_ids):
                mode, reasons = MemoryReferenceMode.SUPPRESS, ["user_feedback_on_source_turn"]
            decisions.append(
                MemoryUseDecision(
                    evidence=ExperienceEvidenceRef(
                        kind=ExperienceEvidenceKind.MEMORY,
                        id=memory.id,
                    ),
                    mode=mode,
                    reasons=[*reasons, "structured_state_evidence"],
                )
            )

    rejected_memory_ids = {
        decision.evidence.id
        for decision in decisions
        if decision.evidence.kind is ExperienceEvidenceKind.MEMORY
        and any(reason.startswith("user_feedback") for reason in decision.reasons)
    }
    recalled_memories = [item.memory for values in context.sections.values() for item in values]
    if context.state_result is not None:
        recalled_memories.extend(context.state_result.memories)
    for memory in recalled_memories:
        if memory.id in rejected_memory_ids:
            blocked_source_turn_ids.update(memory.evidence_turn_ids)

    blocked_episode_ids = {
        item.turn.episode_id
        for item in context.turn_fallback
        if item.turn.id in blocked_source_turn_ids and item.turn.episode_id is not None
    }
    for event_item in context.event_fallback:
        mode, reasons = _fallback_history_mode(
            ExperienceEvidenceKind.EVENT,
            event_item.event.id,
            _fallback_mode(event_item.use_mode, context, request),
            request,
            feedback_by_evidence,
            repeated_evidence,
            config,
        )
        decisions.append(
            MemoryUseDecision(
                evidence=ExperienceEvidenceRef(
                    kind=ExperienceEvidenceKind.EVENT,
                    id=event_item.event.id,
                ),
                mode=mode,
                reasons=["episodic_evidence", *reasons],
            )
        )
    for turn_item in context.turn_fallback:
        mode, reasons = _fallback_history_mode(
            ExperienceEvidenceKind.TURN,
            turn_item.turn.id,
            _fallback_mode(turn_item.use_mode, context, request),
            request,
            feedback_by_evidence,
            repeated_evidence,
            config,
        )
        if turn_item.turn.id in blocked_source_turn_ids or (
            turn_item.turn.episode_id is not None
            and turn_item.turn.episode_id in blocked_episode_ids
        ):
            mode, reasons = MemoryReferenceMode.SUPPRESS, ["user_feedback_on_evidence_lineage"]
        decisions.append(
            MemoryUseDecision(
                evidence=ExperienceEvidenceRef(
                    kind=ExperienceEvidenceKind.TURN,
                    id=turn_item.turn.id,
                ),
                mode=mode,
                reasons=["raw_turn_evidence", *reasons],
            )
        )

    guidance = [
        "先回应当前话语，再决定是否带入历史。",
        "silent_influence 只用于调整理解、语气或建议，不得说成“你以前告诉过我”。",
        (
            "soft_reference 要像自然延续，不复述数据库字段；"
            "explicit_recall 只用于用户确实在问往事或证据高度明确时。"
        ),
    ]
    if any(item.mode is MemoryReferenceMode.CLARIFY for item in decisions):
        guidance.append("候选不唯一时只问一个最容易区分的自然线索，不列出检索候选表。")
    if repeated_evidence:
        guidance.append("本会话已经明确提过的记忆默认退回无声影响，避免重复翻旧账。")
    return MemoryUsePlan(decisions=decisions, guidance=guidance)


def build_initial_response_beat(request: ResponsePlanRequest) -> ResponseBeatRecord:
    kind = (
        ResponseBeatKind.DIRECT_RESPONSE
        if request.goal in {ResponseGoal.DIRECT_ANSWER, ResponseGoal.PROBLEM_SOLVE}
        else ResponseBeatKind.ACKNOWLEDGEMENT
    )
    guidance = GOAL_GUIDANCE[request.goal]
    if request.user_asked_memory_question:
        kind = ResponseBeatKind.ACKNOWLEDGEMENT
        guidance = (
            "简短接住用户的回忆问题；这一拍只依据当前话语，不能提前声称记得、"
            "猜出细节或断言用户没有说过。"
        )
    return ResponseBeatRecord(
        id=str(uuid4()),
        ordinal=0,
        kind=kind,
        source=ResponseBeatSource.CURRENT_TURN,
        release_condition=BeatReleaseCondition.IMMEDIATE,
        status=ResponseBeatStatus.READY,
        guidance=guidance,
    )


def build_response_beats(
    request: ResponsePlanRequest,
    delivery_mode: ResponseDeliveryMode,
    memory_use_plan: MemoryUsePlan,
    follow_up: FollowUpDecision | None,
) -> list[ResponseBeatRecord]:
    drafts: list[
        tuple[
            ResponseBeatKind,
            ResponseBeatSource,
            str,
            list[ExperienceEvidenceRef],
            BeatReleaseCondition,
        ]
    ] = []
    first = build_initial_response_beat(request)
    drafts.append(
        (
            first.kind,
            first.source,
            first.guidance,
            first.evidence,
            first.release_condition,
        )
    )

    if any(item.mode is MemoryReferenceMode.CLARIFY for item in memory_use_plan.decisions):
        evidence = [
            item.evidence
            for item in memory_use_plan.decisions
            if item.mode is MemoryReferenceMode.CLARIFY
        ]
        drafts.append(
            (
                ResponseBeatKind.CLARIFICATION,
                ResponseBeatSource.RETRIEVAL,
                "线索尚未对齐，只问一个容易区分的日常线索；不重新提起用户已经否定的候选。",
                evidence,
                BeatReleaseCondition.PREVIOUS_BEAT_SENT,
            )
        )
    else:
        reference_evidence = [
            item.evidence
            for item in memory_use_plan.decisions
            if item.mode
            in {MemoryReferenceMode.SOFT_REFERENCE, MemoryReferenceMode.EXPLICIT_RECALL}
        ]
        if reference_evidence:
            drafts.append(
                (
                    ResponseBeatKind.MEMORY_REFERENCE,
                    ResponseBeatSource.RETRIEVAL,
                    "只带入能增加理解或连续感的最小历史证据，不重复解释记忆机制。",
                    reference_evidence,
                    BeatReleaseCondition.PREVIOUS_BEAT_SENT,
                )
            )
        elif request.user_asked_memory_question:
            drafts.append(
                (
                    ResponseBeatKind.MEMORY_GAP,
                    ResponseBeatSource.RETRIEVAL,
                    "目前的证据不足以确认是哪件事。自然说明还没对上，不说“你没讲过”；"
                    "必要时只邀请一个地点、人物或时间线索，不编造共同经历。",
                    [],
                    BeatReleaseCondition.PREVIOUS_BEAT_SENT,
                )
            )

    if (
        follow_up is not None
        and follow_up.action is FollowUpAction.ASK_NOW
        and not request.user_asked_memory_question
        and not any(item.mode is MemoryReferenceMode.CLARIFY for item in memory_use_plan.decisions)
    ):
        evidence = (
            [
                ExperienceEvidenceRef(
                    kind=ExperienceEvidenceKind.OPEN_LOOP,
                    id=follow_up.candidate.id,
                )
            ]
            if follow_up.candidate is not None
            else []
        )
        drafts.append(
            (
                ResponseBeatKind.FOLLOW_UP,
                ResponseBeatSource.OPEN_LOOP,
                follow_up.response_guidance or "自然询问未完成事项的后续。",
                evidence,
                BeatReleaseCondition.PREVIOUS_BEAT_SENT,
            )
        )

    if request.allow_afterthought and delivery_mode is ResponseDeliveryMode.SEMANTIC_BEATS:
        drafts.append(
            (
                ResponseBeatKind.AFTERTHOUGHT,
                ResponseBeatSource.PLANNER,
                "只有在用户尚未回复且确实增加新价值时才发送；不能只是换句话重复。",
                [],
                BeatReleaseCondition.HOST_SIGNAL,
            )
        )

    if delivery_mode is ResponseDeliveryMode.SINGLE_MESSAGE:
        return [
            ResponseBeatRecord(
                id=str(uuid4()),
                ordinal=0,
                kind=ResponseBeatKind.COMPOSED_RESPONSE,
                source=ResponseBeatSource.PLANNER,
                release_condition=BeatReleaseCondition.IMMEDIATE,
                status=ResponseBeatStatus.READY,
                guidance="在一条消息里自然衔接以下语义，不拆成多个通知：\n"
                + "\n".join(guidance for _, _, guidance, _, _ in drafts),
                evidence=[item for _, _, _, evidence, _ in drafts for item in evidence],
            )
        ]

    beats: list[ResponseBeatRecord] = []
    for ordinal, (kind, source, guidance, evidence, release_condition) in enumerate(drafts):
        status = ResponseBeatStatus.READY if not beats else ResponseBeatStatus.PENDING
        beats.append(
            ResponseBeatRecord(
                id=str(uuid4()),
                ordinal=ordinal,
                kind=kind,
                source=source,
                release_condition=release_condition,
                status=status,
                guidance=guidance,
                evidence=evidence,
            )
        )
    return beats


def _memory_mode(
    recall_mode: RecallUseMode,
    kind: MemoryKind,
    memory_id: str,
    context: CompanionContext,
    request: ResponsePlanRequest,
    feedback_by_evidence: dict[tuple[ExperienceEvidenceKind, str], MemoryReferenceFeedbackRecord],
    repeated_evidence: set[tuple[ExperienceEvidenceKind, str]],
    config: CompanionConfig,
) -> tuple[MemoryReferenceMode, list[str]]:
    feedback = feedback_by_evidence.get((ExperienceEvidenceKind.MEMORY, memory_id))
    if feedback is not None and feedback.kind in SUPPRESSING_FEEDBACK:
        return MemoryReferenceMode.SUPPRESS, [f"user_feedback:{feedback.kind.value}"]
    if kind is MemoryKind.BOUNDARY:
        return MemoryReferenceMode.SILENT_INFLUENCE, ["boundary_shapes_response_silently"]
    if context.retrieval_action is RetrievalAction.ABSTAIN:
        return MemoryReferenceMode.SUPPRESS, ["recall_action_abstain"]
    if context.retrieval_action is RetrievalAction.CLARIFY:
        if request.user_asked_memory_question:
            return MemoryReferenceMode.CLARIFY, ["recall_candidates_ambiguous"]
        return MemoryReferenceMode.SUPPRESS, ["incidental_ambiguity_should_not_interrupt"]
    if recall_mode is RecallUseMode.DO_NOT_ASSERT:
        return MemoryReferenceMode.SUPPRESS, ["evidence_not_assertable"]
    if request.current_turn_requires_full_attention and not request.user_asked_memory_question:
        return MemoryReferenceMode.SILENT_INFLUENCE, ["current_turn_has_priority"]
    if (
        config.experience.avoid_repeat_within_conversation
        and (ExperienceEvidenceKind.MEMORY, memory_id) in repeated_evidence
        and not request.user_asked_memory_question
    ):
        return MemoryReferenceMode.SILENT_INFLUENCE, ["already_referenced_in_conversation"]
    if request.user_asked_memory_question:
        if recall_mode is RecallUseMode.NATURAL:
            return MemoryReferenceMode.EXPLICIT_RECALL, ["user_requested_memory_and_evidence_clear"]
        if recall_mode is RecallUseMode.HEDGE:
            return MemoryReferenceMode.SOFT_REFERENCE, [
                "user_requested_memory_but_evidence_uncertain"
            ]
        return MemoryReferenceMode.SUPPRESS, ["evidence_not_assertable"]
    if kind in SILENT_MEMORY_KINDS:
        return MemoryReferenceMode.SILENT_INFLUENCE, [
            "relationship_context_should_not_be_announced"
        ]
    if recall_mode is RecallUseMode.NATURAL and context.intent in NATURAL_CALLBACK_INTENTS:
        return MemoryReferenceMode.SOFT_REFERENCE, ["callback_adds_contextual_continuity"]
    return MemoryReferenceMode.SILENT_INFLUENCE, [
        "memory_is_relevant_but_explicit_callback_not_needed"
    ]


def _fallback_mode(
    recall_mode: RecallUseMode,
    context: CompanionContext,
    request: ResponsePlanRequest,
) -> MemoryReferenceMode:
    if context.retrieval_action is RetrievalAction.ABSTAIN:
        return MemoryReferenceMode.SUPPRESS
    if context.retrieval_action is RetrievalAction.CLARIFY:
        return (
            MemoryReferenceMode.CLARIFY
            if request.user_asked_memory_question
            else MemoryReferenceMode.SUPPRESS
        )
    if recall_mode is RecallUseMode.DO_NOT_ASSERT:
        return MemoryReferenceMode.SUPPRESS
    if request.user_asked_memory_question:
        return (
            MemoryReferenceMode.EXPLICIT_RECALL
            if recall_mode is RecallUseMode.NATURAL
            else MemoryReferenceMode.SOFT_REFERENCE
        )
    if request.current_turn_requires_full_attention:
        return MemoryReferenceMode.SILENT_INFLUENCE
    if recall_mode is RecallUseMode.NATURAL and context.intent in NATURAL_CALLBACK_INTENTS:
        return MemoryReferenceMode.SOFT_REFERENCE
    return MemoryReferenceMode.SILENT_INFLUENCE


def _fallback_history_mode(
    kind: ExperienceEvidenceKind,
    evidence_id: str,
    mode: MemoryReferenceMode,
    request: ResponsePlanRequest,
    feedback_by_evidence: dict[tuple[ExperienceEvidenceKind, str], MemoryReferenceFeedbackRecord],
    repeated_evidence: set[tuple[ExperienceEvidenceKind, str]],
    config: CompanionConfig,
) -> tuple[MemoryReferenceMode, list[str]]:
    key = (kind, evidence_id)
    feedback = feedback_by_evidence.get(key)
    if feedback is not None and feedback.kind in SUPPRESSING_FEEDBACK:
        return MemoryReferenceMode.SUPPRESS, [f"user_feedback:{feedback.kind.value}"]
    if (
        config.experience.avoid_repeat_within_conversation
        and key in repeated_evidence
        and not request.user_asked_memory_question
        and mode is not MemoryReferenceMode.SUPPRESS
    ):
        return MemoryReferenceMode.SILENT_INFLUENCE, ["already_referenced_in_conversation"]
    return mode, []
