from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from companion_memoryos.constants import DEFAULT_ENCODING
from companion_memoryos.discourse import interpret_discourse_signals, interpret_explicit_discourse
from companion_memoryos.experience import (
    build_initial_response_beat,
    build_response_beats,
    decide_follow_up,
    plan_memory_use,
)
from companion_memoryos.schemas import (
    AutomaticActionStatus,
    ConsentState,
    ConversationRepairRequest,
    ConversationRepairResult,
    ConversationRole,
    ConversationTurnRecord,
    DiscourseInterpretation,
    DiscourseInterpretationStatus,
    DiscourseInterpretRequest,
    DiscourseSignal,
    ExperienceEvidenceKind,
    ExperienceEvidenceRef,
    FollowUpAction,
    FollowUpDecision,
    FollowUpRequest,
    InterpretedResponsePlan,
    InterpretedResponsePlanRequest,
    MemoryCorrectionRequest,
    MemoryReferenceFeedbackInput,
    MemoryReferenceFeedbackRecord,
    MemoryScope,
    MemoryUsePlan,
    OpenLoopInput,
    OpenLoopRecord,
    OpenLoopStatus,
    OpenLoopStorageResult,
    OpenLoopTransition,
    OpenLoopUpdateRequest,
    PolicyBundleManifest,
    PolicyGateRequest,
    RealityLayer,
    RecallRequest,
    ReferenceFeedbackKind,
    RepairKind,
    ResponseBeatKind,
    ResponseBeatRecord,
    ResponseBeatSentRequest,
    ResponseBeatStatus,
    ResponseDeliveryMode,
    ResponsePlanInterruptRequest,
    ResponsePlanRecord,
    ResponsePlanRequest,
    ResponsePlanResolutionStatus,
    ResponsePlanResolveRequest,
    ResponsePlanStatus,
    RetrievalAction,
    Sensitivity,
    TurnDeletionState,
)

if TYPE_CHECKING:
    from companion_memoryos.service import CompanionMemoryService


def create_open_loop(self: CompanionMemoryService, item: OpenLoopInput) -> OpenLoopStorageResult:
    if not self.config.open_loops.enabled:
        return OpenLoopStorageResult(stored=False, reasons=["open_loops_disabled"])
    if self.config.open_loops.require_granted_consent and item.consent is not ConsentState.GRANTED:
        return OpenLoopStorageResult(stored=False, reasons=["capture_consent_missing"])
    if item.sensitivity is Sensitivity.HIGHLY_SENSITIVE and (
        not self.config.open_loops.allow_highly_sensitive
    ):
        return OpenLoopStorageResult(stored=False, reasons=["highly_sensitive_open_loop_disabled"])
    return OpenLoopStorageResult(
        stored=True,
        open_loop=self.store.create_open_loop(item),
        reasons=["continuity_open_loop_created"],
    )


def update_open_loop(
    self: CompanionMemoryService, open_loop_id: str, request: OpenLoopUpdateRequest
) -> OpenLoopRecord:
    if not self.config.open_loops.enabled:
        raise ValueError("open loops are disabled")
    return self.store.update_open_loop(open_loop_id, request)


def list_open_loops(
    self: CompanionMemoryService,
    user_id: str,
    scope: MemoryScope | None = None,
    statuses: set[OpenLoopStatus] | None = None,
    limit: int | None = None,
) -> list[OpenLoopRecord]:
    return self.store.list_open_loops(user_id, scope, statuses, limit)


def evaluate_follow_up(self: CompanionMemoryService, request: FollowUpRequest) -> FollowUpDecision:
    if not self.config.open_loops.enabled:
        return FollowUpDecision(action=FollowUpAction.NONE, reasons=["open_loops_disabled"])
    candidates = self.store.list_open_loops(
        request.user_id,
        request.scope,
        {OpenLoopStatus.OPEN, OpenLoopStatus.SNOOZED, OpenLoopStatus.WAITING_FOR_REPLY},
    )
    return decide_follow_up(candidates, request)


def record_reference_feedback(
    self: CompanionMemoryService, item: MemoryReferenceFeedbackInput
) -> MemoryReferenceFeedbackRecord:
    if not self.config.experience.enabled:
        raise ValueError("companion experience layer is disabled")
    return self.store.record_reference_feedback(item)


def list_reference_feedback(
    self: CompanionMemoryService,
    user_id: str,
    scope: MemoryScope | None = None,
    memory_ids: list[str] | None = None,
    limit: int | None = None,
) -> list[MemoryReferenceFeedbackRecord]:
    return self.store.list_reference_feedback(user_id, scope, memory_ids, limit)


def plan_response(self: CompanionMemoryService, request: ResponsePlanRequest) -> ResponsePlanRecord:
    if not self.config.experience.enabled:
        raise ValueError("companion experience layer is disabled")
    trigger = self.store.get_turn(request.trigger_turn_id, request.user_id)
    if trigger.scope != request.scope or trigger.role is not ConversationRole.USER:
        raise ValueError("response plans require a user-authored trigger in the exact scope")
    context = None
    if request.recall_request is not None:
        recall_request = request.recall_request.model_copy(
            update={
                "exclude_turn_ids": list(
                    dict.fromkeys(
                        [*request.recall_request.exclude_turn_ids, request.trigger_turn_id]
                    )
                )
            }
        )
        context = self.recall(recall_request)
    memory_ids: list[str] = []
    evidence_refs: list[ExperienceEvidenceRef] = []
    if context is not None:
        memory_ids.extend(item.memory.id for values in context.sections.values() for item in values)
        if context.state_result is not None:
            memory_ids.extend(memory.id for memory in context.state_result.memories)
        evidence_refs.extend(
            ExperienceEvidenceRef(kind=ExperienceEvidenceKind.EVENT, id=item.event.id)
            for item in context.event_fallback
        )
        evidence_refs.extend(
            ExperienceEvidenceRef(kind=ExperienceEvidenceKind.TURN, id=item.turn.id)
            for item in context.turn_fallback
        )
        recalled_memories = [item.memory for values in context.sections.values() for item in values]
        if context.state_result is not None:
            recalled_memories.extend(context.state_result.memories)
        evidence_refs.extend(
            ExperienceEvidenceRef(kind=ExperienceEvidenceKind.TURN, id=turn_id)
            for memory in recalled_memories
            for turn_id in memory.evidence_turn_ids
        )
    memory_ids = list(dict.fromkeys(memory_ids))
    evidence_refs.extend(
        ExperienceEvidenceRef(kind=ExperienceEvidenceKind.MEMORY, id=memory_id)
        for memory_id in memory_ids
    )
    evidence_refs = list({(ref.kind, ref.id): ref for ref in evidence_refs}.values())
    feedback = self.store.latest_reference_feedback(
        request.user_id, request.scope, evidence_refs, request.as_of
    )
    repeated = self.store.used_experience_evidence_since(
        request.user_id,
        request.scope,
        evidence_refs,
        request.conversation_started_at,
        request.as_of,
    )
    repeated_memory_ids = self.store.used_memory_ids_since(
        request.user_id, request.scope, memory_ids, request.conversation_started_at, request.as_of
    )
    repeated.update((ExperienceEvidenceKind.MEMORY, memory_id) for memory_id in repeated_memory_ids)
    effective_request = request.model_copy(
        update={
            "allow_afterthought": self.config.experience.afterthought_enabled_by_default
            if request.allow_afterthought is None
            else request.allow_afterthought
        }
    )
    memory_use_plan = plan_memory_use(context, effective_request, feedback, repeated, self.config)
    follow_up = None
    if request.allow_follow_up:
        follow_up = self.evaluate_follow_up(
            FollowUpRequest(
                user_id=request.user_id,
                scope=request.scope,
                current_topic_keys=request.current_topic_keys,
                user_reopened_topic=request.user_reopened_topic,
                reopened_open_loop_id=request.reopened_open_loop_id,
                current_turn_requires_full_attention=request.current_turn_requires_full_attention,
                allow_due_topic_switch=request.allow_due_topic_switch,
                as_of=request.as_of,
            )
        )
    delivery_mode = (
        ResponseDeliveryMode.SEMANTIC_BEATS
        if request.channel_supports_multiple_beats
        and self.config.experience.semantic_beats_enabled_by_default
        else ResponseDeliveryMode.SINGLE_MESSAGE
    )
    recall_action = context.retrieval_action if context is not None else None
    beats = build_response_beats(effective_request, delivery_mode, memory_use_plan, follow_up)
    plan_id = str(uuid4())
    plan = ResponsePlanRecord(
        id=plan_id,
        response_group_id=plan_id,
        user_id=request.user_id,
        scope=request.scope,
        trigger_turn_id=request.trigger_turn_id,
        goal=request.goal,
        delivery_mode=delivery_mode,
        status=ResponsePlanStatus.ACTIVE,
        revision=1,
        resolution_status=ResponsePlanResolutionStatus.RESOLVED,
        policy_version=self.store.current_policy_version(request.user_id),
        config_fingerprint=self.config.fingerprint(),
        policy_bundle=PolicyBundleManifest.model_validate(
            self.config.policy_bundle.model_dump(mode="python")
        ),
        cancel_on_new_user_turn=self.config.experience.default_cancel_on_new_user_turn
        if request.cancel_on_new_user_turn is None
        else request.cancel_on_new_user_turn,
        recall_action=recall_action,
        memory_use_plan=memory_use_plan,
        follow_up=follow_up,
        beats=beats,
        created_at=request.as_of,
        updated_at=request.as_of,
        resolved_at=request.as_of,
    )
    return self.store.create_response_plan(plan)


def stage_response_plan(
    self: CompanionMemoryService, request: ResponsePlanRequest
) -> ResponsePlanRecord:
    if not self.config.experience.enabled:
        raise ValueError("companion experience layer is disabled")
    if not request.channel_supports_multiple_beats:
        raise ValueError("staged response plans require a multi-beat channel")
    trigger = self.store.get_turn(request.trigger_turn_id, request.user_id)
    if trigger.scope != request.scope or trigger.role is not ConversationRole.USER:
        raise ValueError("response plans require a user-authored trigger in the exact scope")
    effective_request = request.model_copy(
        update={
            "allow_afterthought": self.config.experience.afterthought_enabled_by_default
            if request.allow_afterthought is None
            else request.allow_afterthought
        }
    )
    plan_id = str(uuid4())
    plan = ResponsePlanRecord(
        id=plan_id,
        response_group_id=plan_id,
        user_id=request.user_id,
        scope=request.scope,
        trigger_turn_id=request.trigger_turn_id,
        goal=request.goal,
        delivery_mode=ResponseDeliveryMode.SEMANTIC_BEATS,
        status=ResponsePlanStatus.ACTIVE,
        revision=0,
        resolution_status=ResponsePlanResolutionStatus.PENDING,
        policy_version=self.store.current_policy_version(request.user_id),
        config_fingerprint=self.config.fingerprint(),
        policy_bundle=PolicyBundleManifest.model_validate(
            self.config.policy_bundle.model_dump(mode="python")
        ),
        cancel_on_new_user_turn=self.config.experience.default_cancel_on_new_user_turn
        if request.cancel_on_new_user_turn is None
        else request.cancel_on_new_user_turn,
        memory_use_plan=MemoryUsePlan(guidance=["历史检索尚未完成；首拍只能依据当前用户话语。"]),
        beats=[build_initial_response_beat(effective_request)],
        created_at=request.as_of,
        updated_at=request.as_of,
    )
    return self.store.create_response_plan(plan, effective_request)


def resolve_staged_response_plan(
    self: CompanionMemoryService, plan_id: str, request: ResponsePlanResolveRequest
) -> ResponsePlanRecord:
    current = self.store.get_response_plan(plan_id, request.user_id)
    if current.resolution_status is ResponsePlanResolutionStatus.RESOLVED:
        return self.store.resolve_response_plan(
            plan_id,
            request.user_id,
            request.expected_revision,
            request.resolution_key,
            current.recall_action.value if current.recall_action is not None else None,
            current.memory_use_plan,
            current.follow_up,
            [],
            request.as_of,
        )
    if current.status is not ResponsePlanStatus.ACTIVE:
        raise ValueError("cancelled or completed response plans cannot be resolved")
    if current.revision != request.expected_revision:
        raise ValueError("response plan revision changed; discard stale retrieval")
    stored_request = self.store.get_response_resolution_request(plan_id, request.user_id)
    recall_action, memory_use_plan, follow_up, beats = self._resolved_response_components(
        stored_request
    )
    return self.store.resolve_response_plan(
        plan_id,
        request.user_id,
        request.expected_revision,
        request.resolution_key,
        recall_action.value if recall_action is not None else None,
        memory_use_plan,
        follow_up,
        beats[1:],
        request.as_of,
    )


def _resolved_response_components(
    self: CompanionMemoryService, request: ResponsePlanRequest
) -> tuple[
    RetrievalAction | None, MemoryUsePlan, FollowUpDecision | None, list[ResponseBeatRecord]
]:
    context = None
    if request.recall_request is not None:
        recall_request = request.recall_request.model_copy(
            update={
                "exclude_turn_ids": list(
                    dict.fromkeys(
                        [*request.recall_request.exclude_turn_ids, request.trigger_turn_id]
                    )
                )
            }
        )
        context = self.recall(recall_request)
    memory_ids: list[str] = []
    evidence_refs: list[ExperienceEvidenceRef] = []
    if context is not None:
        memory_ids.extend(item.memory.id for values in context.sections.values() for item in values)
        if context.state_result is not None:
            memory_ids.extend(memory.id for memory in context.state_result.memories)
        evidence_refs.extend(
            ExperienceEvidenceRef(kind=ExperienceEvidenceKind.EVENT, id=item.event.id)
            for item in context.event_fallback
        )
        evidence_refs.extend(
            ExperienceEvidenceRef(kind=ExperienceEvidenceKind.TURN, id=item.turn.id)
            for item in context.turn_fallback
        )
        recalled_memories = [item.memory for values in context.sections.values() for item in values]
        if context.state_result is not None:
            recalled_memories.extend(context.state_result.memories)
        evidence_refs.extend(
            ExperienceEvidenceRef(kind=ExperienceEvidenceKind.TURN, id=turn_id)
            for memory in recalled_memories
            for turn_id in memory.evidence_turn_ids
        )
    memory_ids = list(dict.fromkeys(memory_ids))
    evidence_refs.extend(
        ExperienceEvidenceRef(kind=ExperienceEvidenceKind.MEMORY, id=memory_id)
        for memory_id in memory_ids
    )
    evidence_refs = list({(ref.kind, ref.id): ref for ref in evidence_refs}.values())
    feedback = self.store.latest_reference_feedback(
        request.user_id, request.scope, evidence_refs, request.as_of
    )
    repeated = self.store.used_experience_evidence_since(
        request.user_id,
        request.scope,
        evidence_refs,
        request.conversation_started_at,
        request.as_of,
    )
    repeated.update(
        (ExperienceEvidenceKind.MEMORY, memory_id)
        for memory_id in self.store.used_memory_ids_since(
            request.user_id,
            request.scope,
            memory_ids,
            request.conversation_started_at,
            request.as_of,
        )
    )
    memory_use_plan = plan_memory_use(context, request, feedback, repeated, self.config)
    follow_up = None
    if request.allow_follow_up:
        follow_up = self.evaluate_follow_up(
            FollowUpRequest(
                user_id=request.user_id,
                scope=request.scope,
                current_topic_keys=request.current_topic_keys,
                user_reopened_topic=request.user_reopened_topic,
                reopened_open_loop_id=request.reopened_open_loop_id,
                current_turn_requires_full_attention=request.current_turn_requires_full_attention,
                allow_due_topic_switch=request.allow_due_topic_switch,
                as_of=request.as_of,
            )
        )
    beats = build_response_beats(
        request, ResponseDeliveryMode.SEMANTIC_BEATS, memory_use_plan, follow_up
    )
    return (
        context.retrieval_action if context is not None else None,
        memory_use_plan,
        follow_up,
        beats,
    )


def get_response_plan(
    self: CompanionMemoryService, plan_id: str, user_id: str
) -> ResponsePlanRecord:
    return self.store.get_response_plan(plan_id, user_id)


def interrupt_response_plans(
    self: CompanionMemoryService, request: ResponsePlanInterruptRequest
) -> list[str]:
    return self.store.interrupt_response_plans(request)


def list_response_plans(
    self: CompanionMemoryService,
    user_id: str,
    scope: MemoryScope | None = None,
    statuses: set[ResponsePlanStatus] | None = None,
    limit: int | None = None,
) -> list[ResponsePlanRecord]:
    return self.store.list_response_plans(user_id, scope, statuses, limit)


def cancel_response_plan(
    self: CompanionMemoryService,
    plan_id: str,
    user_id: str,
    reason: str,
    as_of: datetime | None = None,
) -> ResponsePlanRecord:
    return self.store.cancel_response_plan(plan_id, user_id, reason, as_of or datetime.now(UTC))


def mark_response_beat_sent(
    self: CompanionMemoryService, plan_id: str, beat_id: str, request: ResponseBeatSentRequest
) -> ResponsePlanRecord:
    plan = self.store.get_response_plan(plan_id, request.user_id)
    beat = next((item for item in plan.beats if item.id == beat_id), None)
    if beat is None:
        raise KeyError(beat_id)
    if request.silently_used_memory_ids and (
        plan.resolution_status is not ResponsePlanResolutionStatus.RESOLVED
        or beat.kind
        not in {
            ResponseBeatKind.DIRECT_RESPONSE,
            ResponseBeatKind.COMPOSED_RESPONSE,
            ResponseBeatKind.MEMORY_REFERENCE,
            ResponseBeatKind.MEMORY_GAP,
            ResponseBeatKind.CLARIFICATION,
        }
    ):
        raise ValueError("silent memory use requires a resolved memory answer beat")
    output_hash = hashlib.sha256(request.rendered_text.encode(DEFAULT_ENCODING)).hexdigest()
    if beat.status is ResponseBeatStatus.SENT:
        if beat.output_hash != output_hash:
            raise ValueError("a sent beat cannot be acknowledged with different text")
        return plan
    actions = ["send_message"]
    if beat.evidence or request.silently_used_memory_ids:
        actions.append("use_relationship_context")
    gate = self.evaluate_policy(
        PolicyGateRequest(
            user_id=request.user_id,
            scope=plan.scope,
            actions=actions,
            task_policy_version=request.task_policy_version,
            as_of=request.sent_at,
        )
    )
    if not gate.allowed:
        raise ValueError("response beat is blocked by the current outbound policy")
    return self.store.mark_response_beat_sent(
        plan_id,
        beat_id,
        request.user_id,
        output_hash,
        request.task_policy_version,
        request.sent_at,
        request.host_release_signal,
        request.silently_used_memory_ids,
    )


def apply_repair(
    self: CompanionMemoryService, request: ConversationRepairRequest
) -> ConversationRepairResult:
    acknowledgement = "简短承认并立即按纠正继续聊天；不要展示内部记录，也不要要求用户再次确认。"
    if request.kind is RepairKind.CORRECT_MEMORY:
        assert request.memory_id is not None
        assert request.replacement_content is not None
        corrected = self.correct(
            request.memory_id,
            MemoryCorrectionRequest(
                user_id=request.user_id,
                content=request.replacement_content,
                title=request.replacement_title,
                event_at=request.as_of,
                source_ref="conversation:natural-repair",
                evidence_turn_ids=[request.source_turn_id]
                if request.source_turn_id is not None
                else [],
            ),
        )
        return ConversationRepairResult(
            applied=True,
            kind=request.kind,
            corrected_memory=corrected,
            acknowledgement_guidance=acknowledgement,
            reasons=["memory_corrected_in_one_conversation_action"],
        )
    if request.kind in {RepairKind.WRONG_REFERENCE, RepairKind.STOP_REFERENCING}:
        feedback = self.record_reference_feedback(
            MemoryReferenceFeedbackInput(
                user_id=request.user_id,
                scope=request.scope,
                memory_id=request.memory_id,
                evidence_kind=request.evidence_kind,
                evidence_id=request.evidence_id,
                kind=ReferenceFeedbackKind.WRONG_MATCH
                if request.kind is RepairKind.WRONG_REFERENCE
                else ReferenceFeedbackKind.DO_NOT_REFERENCE,
                source_turn_id=request.source_turn_id,
                recorded_at=request.as_of,
            )
        )
        return ConversationRepairResult(
            applied=True,
            kind=request.kind,
            reference_feedback=feedback,
            acknowledgement_guidance=acknowledgement,
            reasons=["future_reference_suppressed_in_scope"],
        )
    assert request.open_loop_id is not None
    open_loop = self.update_open_loop(
        request.open_loop_id,
        OpenLoopUpdateRequest(
            user_id=request.user_id,
            transition=OpenLoopTransition.RESOLVE
            if request.kind is RepairKind.RESOLVE_OPEN_LOOP
            else OpenLoopTransition.CANCEL,
            source_turn_id=request.source_turn_id,
            resolution_summary=request.resolution_summary,
            as_of=request.as_of,
        ),
    )
    return ConversationRepairResult(
        applied=True,
        kind=request.kind,
        open_loop=open_loop,
        acknowledgement_guidance=acknowledgement,
        reasons=["open_loop_closed_without_extra_confirmation"],
    )


def interpret_turn(
    self: CompanionMemoryService, request: DiscourseInterpretRequest
) -> DiscourseInterpretation:
    turn = self.store.get_turn(request.turn_id, request.user_id)
    if (
        turn.scope != request.scope
        or turn.role is not ConversationRole.USER
        or turn.deletion_state is not TurnDeletionState.ACTIVE
    ):
        raise ValueError("discourse interpretation requires an active user turn in exact scope")
    result = interpret_explicit_discourse(
        user_id=request.user_id,
        scope=request.scope,
        turn_id=request.turn_id,
        content=self._direct_user_discourse_text(turn),
        config=self.config,
    )
    if result.status is DiscourseInterpretationStatus.UNKNOWN:
        proposed = self.get_turn_interpretation(turn.id, turn.user_id)
        if proposed is not None:
            spans = proposed.model_output.speech_spans
            direct = not spans or any(
                span.quote_depth == 0
                and span.reality_layer is RealityLayer.REAL_WORLD
                and (span.attributed_speaker_id in {None, turn.actor_id})
                for span in spans
            )
            if direct:
                result = interpret_discourse_signals(
                    user_id=turn.user_id,
                    scope=turn.scope,
                    turn_id=turn.id,
                    signals=proposed.model_output.discourse_signals,
                )
    cancelled: list[str] = []
    repair = None
    action_status = AutomaticActionStatus.NOT_REQUESTED
    if request.apply_low_risk_actions and result.interrupt_pending_response:
        cancelled = self.interrupt_response_plans(
            ResponsePlanInterruptRequest(
                user_id=request.user_id,
                scope=request.scope,
                reason="explicit_topic_switch",
                as_of=request.as_of,
            )
        )
    repair_signal = None
    if DiscourseSignal.STOP_REFERENCING in result.signals:
        repair_signal = RepairKind.STOP_REFERENCING
    elif DiscourseSignal.WRONG_REFERENCE in result.signals:
        repair_signal = RepairKind.WRONG_REFERENCE
    if request.apply_low_risk_actions and repair_signal is not None:
        evidence_candidates = [
            item
            for item in self.store.latest_used_experience_evidence(request.user_id, request.scope)
            if item.kind
            in {
                ExperienceEvidenceKind.MEMORY,
                ExperienceEvidenceKind.EVENT,
                ExperienceEvidenceKind.TURN,
            }
        ]
        if len(evidence_candidates) == 1:
            target = evidence_candidates[0]
            repair = self.apply_repair(
                ConversationRepairRequest(
                    user_id=request.user_id,
                    scope=request.scope,
                    kind=repair_signal,
                    source_turn_id=request.turn_id,
                    evidence_kind=target.kind,
                    evidence_id=target.id,
                    as_of=request.as_of,
                )
            )
            action_status = AutomaticActionStatus.APPLIED
        else:
            action_status = AutomaticActionStatus.NEEDS_TARGET
    elif request.apply_low_risk_actions and DiscourseSignal.OUTCOME_REPORTED in result.signals:
        topics = set(request.current_topic_keys)
        open_loops = self.list_open_loops(
            request.user_id,
            request.scope,
            {OpenLoopStatus.OPEN, OpenLoopStatus.SNOOZED, OpenLoopStatus.WAITING_FOR_REPLY},
        )
        open_loop_candidates = [item for item in open_loops if topics & set(item.topic_keys)]
        if len(open_loop_candidates) == 1:
            repair = self.apply_repair(
                ConversationRepairRequest(
                    user_id=request.user_id,
                    scope=request.scope,
                    kind=RepairKind.RESOLVE_OPEN_LOOP,
                    source_turn_id=request.turn_id,
                    open_loop_id=open_loop_candidates[0].id,
                    resolution_summary=turn.content,
                    as_of=request.as_of,
                )
            )
            action_status = AutomaticActionStatus.APPLIED
        else:
            action_status = AutomaticActionStatus.NEEDS_TARGET
    return result.model_copy(
        update={
            "automatic_action_status": action_status,
            "repair": repair,
            "cancelled_response_plan_ids": cancelled,
        }
    )


def _direct_user_discourse_text(turn: ConversationTurnRecord) -> str:
    if not turn.speech_spans:
        return turn.content
    direct_spans = [
        span
        for span in turn.speech_spans
        if span.quote_depth == 0
        and span.reality_layer is RealityLayer.REAL_WORLD
        and (span.attributed_speaker_id in {None, turn.actor_id})
    ]
    return "\n".join(turn.content[span.start_offset : span.end_offset] for span in direct_spans)


def stage_interpreted_response_plan(
    self: CompanionMemoryService, request: InterpretedResponsePlanRequest
) -> InterpretedResponsePlan:
    interpretation = self.interpret_turn(
        DiscourseInterpretRequest(
            user_id=request.user_id,
            scope=request.scope,
            turn_id=request.turn_id,
            current_topic_keys=request.current_topic_keys,
            apply_low_risk_actions=True,
            as_of=request.as_of,
        )
    )
    turn = self.store.get_turn(request.turn_id, request.user_id)
    should_recall = request.enable_recall and (
        interpretation.user_asked_memory_question
        or not interpretation.current_turn_requires_full_attention
    )
    recall_request = (
        RecallRequest(
            user_id=request.user_id,
            scope=request.scope,
            query=turn.content,
            intent=request.recall_intent,
            calendar_timezone=request.calendar_timezone,
            as_of=request.as_of,
        )
        if should_recall
        else None
    )
    plan = self.stage_response_plan(
        ResponsePlanRequest(
            user_id=request.user_id,
            scope=request.scope,
            trigger_turn_id=request.turn_id,
            goal=interpretation.suggested_goal or request.fallback_goal,
            recall_request=recall_request,
            user_asked_memory_question=interpretation.user_asked_memory_question,
            current_turn_requires_full_attention=interpretation.current_turn_requires_full_attention,
            current_topic_keys=request.current_topic_keys,
            allow_follow_up=request.allow_follow_up,
            allow_afterthought=request.allow_afterthought,
            channel_supports_multiple_beats=True,
            conversation_started_at=request.conversation_started_at,
            as_of=request.as_of,
        )
    )
    return InterpretedResponsePlan(interpretation=interpretation, plan=plan)
