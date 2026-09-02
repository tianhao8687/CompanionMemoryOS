from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from companion_memoryos import experience_service, recall_service, state_service
from companion_memoryos.config import CompanionConfig
from companion_memoryos.constants import (
    DEFAULT_ENCODING,
    MEMORY_SCHEMA_VERSION,
    STABLE_KEY_DIGEST_PREFIX_LENGTH,
)
from companion_memoryos.episode_store import EpisodeStore
from companion_memoryos.intent import has_explicit_memory_directive
from companion_memoryos.interpretation_service import (
    apply_interpretation,
    get_interpretation,
    list_interpretations,
)
from companion_memoryos.interpreter import TurnInterpreter, configured_interpreter
from companion_memoryos.policy import decide_storage, retention_expiry
from companion_memoryos.proactivity import decide_proactivity
from companion_memoryos.process_service import process_turn
from companion_memoryos.schemas import (
    AnswerCardinality,
    ChannelWatermark,
    CompanionContext,
    ConsentState,
    ConversationEventInput,
    ConversationEventRecord,
    ConversationRepairRequest,
    ConversationRepairResult,
    ConversationRole,
    ConversationTurnInput,
    ConversationTurnRecord,
    ConversationTurnStorageResult,
    DiscourseInterpretation,
    DiscourseInterpretRequest,
    ElicitationKind,
    EpisodeAttachRequest,
    EpisodeDetachRequest,
    EpisodeInput,
    EpisodeMergeRequest,
    EpisodeRecord,
    EpisodeSplitRequest,
    EpistemicKind,
    EventRecallItem,
    EventStatus,
    EventStorageResult,
    EvidenceActor,
    ExportBundle,
    FollowUpDecision,
    FollowUpRequest,
    InterpretedResponsePlan,
    InterpretedResponsePlanRequest,
    MemoryCorrectionRequest,
    MemoryCorrectionResult,
    MemoryInput,
    MemoryKind,
    MemoryRecord,
    MemoryReferenceFeedbackInput,
    MemoryReferenceFeedbackRecord,
    MemoryScope,
    MemoryStatus,
    MemoryUseInput,
    MemoryUsePlan,
    MemoryUseRecord,
    OpenLoopInput,
    OpenLoopRecord,
    OpenLoopStatus,
    OpenLoopStorageResult,
    OpenLoopUpdateRequest,
    PolicyConstraintInput,
    PolicyConstraintRecord,
    PolicyGateDecision,
    PolicyGateRequest,
    ProactivityDecision,
    ProactivityRequest,
    ProcessingWatermarkInput,
    ProcessTurnRequest,
    ProcessTurnResult,
    ProfileSnapshot,
    RecallItem,
    RecallRequest,
    RecallUseMode,
    ResolutionStatus,
    ResponseBeatRecord,
    ResponseBeatSentRequest,
    ResponsePlanInterruptRequest,
    ResponsePlanRecord,
    ResponsePlanRequest,
    ResponsePlanResolveRequest,
    ResponsePlanStatus,
    RetrievalAction,
    RetrievalOutcome,
    ReviewDecision,
    ScoreBreakdown,
    Sensitivity,
    StateQuery,
    StateQueryResult,
    StorageAction,
    StorageResult,
    TemporalAnchorInput,
    TemporalAnchorRecord,
    TemporalAnchorStatus,
    TemporalAnchorStorageResult,
    TurnInterpretationRecord,
    TurnInterpretationRequest,
    TurnRecallItem,
)
from companion_memoryos.service_rules import (
    STABLE_KINDS,
)
from companion_memoryos.store import (
    EventSearchCandidate,
    MemorySearchCandidate,
    MemoryStore,
    TurnSearchCandidate,
)
from companion_memoryos.temporal import TemporalHint
from companion_memoryos.tokens import TiktokenTokenCounter, TokenCounter


class CompanionMemoryService:
    def __init__(
        self,
        store: MemoryStore,
        config: CompanionConfig,
        *,
        token_counter: TokenCounter | None = None,
        turn_interpreter: TurnInterpreter | None = None,
    ) -> None:
        self.store = store
        self.config = config
        self.turn_interpreter = turn_interpreter or configured_interpreter(config.interpreter)
        self.token_counter = token_counter or TiktokenTokenCounter(config.tokenization.encoding)
        self.tokenizer_name = (
            config.tokenization.encoding
            if token_counter is None
            else type(token_counter).__qualname__
        )

    def remember(self, item: MemoryInput) -> StorageResult:
        directive_detected = has_explicit_memory_directive(item.content)
        directive_reasons: list[str] = []
        directly_attributed = self._is_direct_user_evidence(item)
        if item.explicit_user_request and not directly_attributed:
            item = item.model_copy(
                update={
                    "explicit_user_request": False,
                    "resolution_status": ResolutionStatus.CONTESTED,
                }
            )
            directive_reasons.append("ineligible_explicit_directive_downgraded")
        if (
            directive_detected
            and item.consent is ConsentState.GRANTED
            and not item.explicit_user_request
            and directly_attributed
        ):
            item = item.model_copy(update={"explicit_user_request": True})
        if (
            item.epistemic_kind is EpistemicKind.OBSERVATION
            and item.kind in STABLE_KINDS
            and item.explicit_user_request
            and item.subject_actor_id in {None, item.user_id}
        ):
            item = item.model_copy(update={"epistemic_kind": EpistemicKind.DIRECT_SELF_REPORT})
        item, epistemic_reasons = self._enforce_epistemic_eligibility(item)

        decision = decide_storage(item, self.config)
        if decision.action is StorageAction.DISCARD:
            return StorageResult(
                action=decision.action,
                memory=None,
                reasons=[*decision.reasons, *directive_reasons, *epistemic_reasons],
            )
        stable_key = item.stable_key
        if stable_key is None and item.kind in STABLE_KINDS and item.predicate is not None:
            identity = "\0".join(
                (
                    item.kind.value,
                    item.subject_actor_id or item.user_id,
                    item.predicate,
                    item.reality_layer.value,
                )
            )
            digest = hashlib.sha256(identity.encode(DEFAULT_ENCODING)).hexdigest()
            stable_key = f"{item.kind.value}:{digest[:STABLE_KEY_DIGEST_PREFIX_LENGTH]}"
        promoted_from_candidate: str | None = None
        if self.config.policy.exact_duplicate_detection:
            duplicate = self.store.find_duplicate(
                item,
                stable_key,
                allow_candidate_evidence_upgrade=(decision.action is StorageAction.ACTIVATE),
            )
            if duplicate is not None:
                if (
                    duplicate.status is MemoryStatus.CANDIDATE
                    and decision.action is StorageAction.ACTIVATE
                ):
                    promoted_from_candidate = duplicate.id
                else:
                    return StorageResult(
                        action=decision.action,
                        memory=duplicate,
                        duplicate_of=duplicate.id,
                        reasons=[
                            *decision.reasons,
                            *directive_reasons,
                            *epistemic_reasons,
                            "exact_duplicate",
                        ],
                    )
        metadata = {
            **item.metadata,
            "memory_schema_version": MEMORY_SCHEMA_VERSION,
            "policy_reasons": decision.reasons,
            "natural_directive_detected": directive_detected,
            "epistemic_reasons": [*directive_reasons, *epistemic_reasons],
            "promoted_from_candidate": promoted_from_candidate,
        }
        memory = self.store.create(
            item,
            decision,
            stable_key,
            metadata,
            replace_candidate_id=promoted_from_candidate,
        )
        return StorageResult(
            action=decision.action,
            memory=memory,
            duplicate_of=promoted_from_candidate,
            reasons=[
                *decision.reasons,
                *directive_reasons,
                *epistemic_reasons,
                *(
                    ["candidate_replaced_by_direct_evidence"]
                    if promoted_from_candidate is not None
                    else []
                ),
            ],
        )

    def archive_event(self, item: ConversationEventInput) -> EventStorageResult:
        settings = self.config.event_archive
        if not settings.enabled:
            return EventStorageResult(stored=False, reasons=["event_archive_disabled"])
        if settings.require_granted_consent and item.consent is not ConsentState.GRANTED:
            return EventStorageResult(stored=False, reasons=["capture_consent_missing"])
        if item.role is ConversationRole.ASSISTANT and not settings.allow_assistant_events:
            return EventStorageResult(
                stored=False,
                reasons=["assistant_event_disabled"],
            )
        if item.sensitivity is Sensitivity.HIGHLY_SENSITIVE and not settings.allow_highly_sensitive:
            return EventStorageResult(
                stored=False,
                reasons=["highly_sensitive_event_disabled"],
            )
        retention_days = (
            settings.retention_days
            if item.sensitivity is Sensitivity.NORMAL
            else settings.sensitive_retention_days
        )
        expires_at = datetime.now(UTC) + timedelta(days=retention_days)
        event = self.store.create_event(item, expires_at)
        return EventStorageResult(stored=True, event=event, reasons=["episodic_fallback_archived"])

    def append_turn(self, item: ConversationTurnInput) -> ConversationTurnStorageResult:
        settings = self.config.conversation_ledger
        if not settings.enabled:
            return ConversationTurnStorageResult(
                stored=False, reasons=["conversation_ledger_disabled"]
            )
        if settings.require_granted_consent and item.consent is not ConsentState.GRANTED:
            return ConversationTurnStorageResult(stored=False, reasons=["capture_consent_missing"])
        if item.role is ConversationRole.ASSISTANT and not settings.allow_assistant_turns:
            return ConversationTurnStorageResult(stored=False, reasons=["assistant_turn_disabled"])
        if item.sensitivity is Sensitivity.HIGHLY_SENSITIVE and not settings.allow_highly_sensitive:
            return ConversationTurnStorageResult(
                stored=False, reasons=["highly_sensitive_turn_disabled"]
            )
        turn, duplicate_of, cancelled_plan_ids = self.store.append_turn(item)
        return ConversationTurnStorageResult(
            stored=True,
            turn=turn,
            duplicate_of=duplicate_of,
            cancelled_response_plan_ids=cancelled_plan_ids,
            reasons=(
                ["idempotent_replay"]
                if duplicate_of is not None
                else [
                    "raw_turn_persisted",
                    *(["stale_response_plans_cancelled"] if cancelled_plan_ids else []),
                ]
            ),
        )

    def correct(self, memory_id: str, request: MemoryCorrectionRequest) -> MemoryCorrectionResult:
        current = self.store.get(memory_id, request.user_id)
        if current.status is not MemoryStatus.ACTIVE:
            raise ValueError("only active memories can be corrected")
        if current.stable_key is None:
            raise ValueError("memory has no stable identity and cannot be corrected in place")
        consent = current.consent if request.consent is ConsentState.UNKNOWN else request.consent
        result = self.remember(
            MemoryInput(
                user_id=request.user_id,
                scope=current.scope,
                kind=current.kind,
                title=request.title or current.title,
                content=request.content,
                stable_key=current.stable_key,
                emotions=current.emotions if request.emotions is None else request.emotions,
                needs=current.needs if request.needs is None else request.needs,
                consent=consent,
                explicit_user_request=True,
                sensitivity=current.sensitivity,
                retention=current.retention,
                confidence=current.confidence,
                salience=current.salience,
                event_at=request.event_at,
                valid_time_start=request.valid_time_start or request.event_at,
                valid_time_end=request.valid_time_end,
                source_ref=request.source_ref,
                source_excerpt=request.source_excerpt,
                entities=current.entities if request.entities is None else request.entities,
                embedding=request.embedding,
                embedding_space=request.embedding_space,
                epistemic_kind=current.epistemic_kind,
                resolution_status=ResolutionStatus.RESOLVED,
                reality_layer=current.reality_layer,
                source_actor=EvidenceActor.AUTHENTICATED_USER,
                quote_depth=0,
                elicitation_kind=ElicitationKind.SPONTANEOUS,
                subject_actor_id=current.subject_actor_id,
                predicate=current.predicate,
                evidence_turn_ids=request.evidence_turn_ids,
                metadata={
                    **current.metadata,
                    "correction_of": current.id,
                    "direct_user_correction": True,
                },
            )
        )
        return MemoryCorrectionResult(
            previous_memory_id=current.id,
            action=result.action,
            memory=result.memory,
            duplicate_of=result.duplicate_of,
            reasons=[*result.reasons, "direct_user_correction"],
        )

    def remember_temporal_anchor(self, item: TemporalAnchorInput) -> TemporalAnchorStorageResult:
        settings = self.config.temporal_anchors
        if not settings.enabled:
            return TemporalAnchorStorageResult(stored=False, reasons=["temporal_anchors_disabled"])
        if item.consent is not ConsentState.GRANTED:
            return TemporalAnchorStorageResult(stored=False, reasons=["consent_missing"])
        if item.sensitivity is not Sensitivity.NORMAL and not settings.allow_sensitive:
            return TemporalAnchorStorageResult(stored=False, reasons=["sensitive_anchor_disabled"])
        anchor = self.store.create_temporal_anchor(item)
        return TemporalAnchorStorageResult(
            stored=True,
            anchor=anchor,
            reasons=["explicit_personal_time_anchor"],
        )

    def review(
        self,
        memory_id: str,
        user_id: str,
        decision: ReviewDecision,
    ) -> MemoryRecord:
        confirm = decision is ReviewDecision.CONFIRM
        confirmed_expires_at = None
        if confirm:
            self.store.expire_due(datetime.now(UTC))
            current = self.store.get(memory_id, user_id)
            confirmed_expires_at = retention_expiry(
                current.created_at,
                current.retention,
                current.sensitivity,
                self.config,
            )
        return self.store.review(memory_id, user_id, confirm, confirmed_expires_at)

    def recall(self, request: RecallRequest) -> CompanionContext:
        return recall_service.recall(self, request)

    def profile(self, user_id: str, scope: MemoryScope | None = None) -> ProfileSnapshot:
        return state_service.profile(self, user_id, scope)

    def list_memories(
        self,
        user_id: str,
        statuses: set[MemoryStatus] | None = None,
        limit: int | None = None,
    ) -> list[MemoryRecord]:
        return self.store.list_memories(user_id, statuses, limit)

    def list_events(
        self,
        user_id: str,
        statuses: set[EventStatus] | None = None,
        limit: int | None = None,
    ) -> list[ConversationEventRecord]:
        return self.store.list_events(user_id, statuses, limit)

    def list_turns(
        self,
        user_id: str,
        scope: MemoryScope | None = None,
        limit: int | None = None,
    ) -> list[ConversationTurnRecord]:
        return self.store.list_turns(user_id, scope, limit)

    def list_temporal_anchors(
        self,
        user_id: str,
        statuses: set[TemporalAnchorStatus] | None = None,
        limit: int | None = None,
    ) -> list[TemporalAnchorRecord]:
        return self.store.list_temporal_anchors(user_id, statuses, limit)

    def forget(self, memory_id: str, user_id: str) -> MemoryRecord:
        return self.store.forget(memory_id, user_id)

    def purge(self, memory_id: str, user_id: str) -> None:
        self.store.purge(memory_id, user_id)

    def forget_event(self, event_id: str, user_id: str) -> ConversationEventRecord:
        return self.store.forget_event(event_id, user_id)

    def purge_event(self, event_id: str, user_id: str) -> None:
        self.store.purge_event(event_id, user_id)

    def forget_turn(
        self,
        turn_id: str,
        user_id: str,
        *,
        revoke_source_policies: bool = False,
    ) -> ConversationTurnRecord:
        return self.store.forget_turn(
            turn_id,
            user_id,
            revoke_source_policies=revoke_source_policies,
        )

    def purge_turn(
        self,
        turn_id: str,
        user_id: str,
        *,
        revoke_source_policies: bool = False,
    ) -> None:
        self.store.purge_turn(
            turn_id,
            user_id,
            revoke_source_policies=revoke_source_policies,
        )

    def forget_temporal_anchor(self, anchor_id: str, user_id: str) -> TemporalAnchorRecord:
        return self.store.forget_temporal_anchor(anchor_id, user_id)

    def purge_temporal_anchor(self, anchor_id: str, user_id: str) -> None:
        self.store.purge_temporal_anchor(anchor_id, user_id)

    def export(self, user_id: str) -> ExportBundle:
        return ExportBundle(
            schema_version=MEMORY_SCHEMA_VERSION,
            exported_at=datetime.now(UTC),
            user_id=user_id,
            memories=self.store.list_memories(user_id),
            events=self.store.list_events(user_id),
            temporal_anchors=self.store.list_temporal_anchors(user_id),
            conversation_turns=self.store.list_turns(user_id),
            memory_uses=self.store.list_memory_uses(user_id),
            policy_constraints=self.store.list_policy_constraints(user_id),
            open_loops=self.store.list_open_loops(user_id),
            reference_feedback=self.store.list_reference_feedback(user_id),
            response_plans=self.store.list_response_plans(user_id),
            episodes=self.list_episodes(user_id),
            turn_interpretations=list_interpretations(self.store, user_id),
        )

    def query_state(self, query: StateQuery) -> StateQueryResult:
        return state_service.query_state(self, query)

    def apply_turn_interpretation(
        self,
        turn_id: str,
        request: TurnInterpretationRequest,
        *,
        prior_discourse: DiscourseInterpretation | None = None,
    ) -> TurnInterpretationRecord:
        return apply_interpretation(self, turn_id, request, prior_discourse=prior_discourse)

    def process_turn(self, request: ProcessTurnRequest) -> ProcessTurnResult:
        return process_turn(self, request)

    def get_turn_interpretation(
        self, turn_id: str, user_id: str
    ) -> TurnInterpretationRecord | None:
        return get_interpretation(self.store, turn_id, user_id)

    def create_episode(self, item: EpisodeInput) -> EpisodeRecord:
        return EpisodeStore(self.store).create(item)

    def list_episodes(self, user_id: str, scope: MemoryScope | None = None) -> list[EpisodeRecord]:
        return EpisodeStore(self.store).list_episodes(user_id, scope)

    def episode_turns(
        self, episode_id: str, user_id: str, scope: MemoryScope
    ) -> list[ConversationTurnRecord]:
        return EpisodeStore(self.store).turns(episode_id, user_id, scope)

    def attach_episode_turn(self, episode_id: str, request: EpisodeAttachRequest) -> EpisodeRecord:
        return EpisodeStore(self.store).attach(episode_id, request)

    def merge_episodes(self, episode_id: str, request: EpisodeMergeRequest) -> EpisodeRecord:
        return EpisodeStore(self.store).merge(episode_id, request)

    def detach_episode_turn(self, episode_id: str, request: EpisodeDetachRequest) -> EpisodeRecord:
        return EpisodeStore(self.store).detach(episode_id, request)

    def split_episode(self, episode_id: str, request: EpisodeSplitRequest) -> EpisodeRecord:
        return EpisodeStore(self.store).split(episode_id, request)

    def update_processing_watermark(self, item: ProcessingWatermarkInput) -> ChannelWatermark:
        return self.store.upsert_processing_watermark(item)

    def record_memory_use(self, item: MemoryUseInput) -> MemoryUseRecord:
        if not self.config.memory_use_ledger.enabled:
            raise ValueError("memory use ledger is disabled")
        return self.store.record_memory_use(item)

    def list_memory_uses(
        self, user_id: str, memory_id: str | None = None, limit: int | None = None
    ) -> list[MemoryUseRecord]:
        return self.store.list_memory_uses(user_id, memory_id, limit)

    def create_policy_constraint(self, item: PolicyConstraintInput) -> PolicyConstraintRecord:
        if not self.config.policy_engine.enabled:
            raise ValueError("policy engine is disabled")
        return self.store.create_policy_constraint(item)

    def evaluate_policy(self, request: PolicyGateRequest) -> PolicyGateDecision:
        if not self.config.policy_engine.enabled:
            return PolicyGateDecision(
                allowed=False,
                policy_version=self.store.current_policy_version(request.user_id),
                blocked_actions=request.actions,
                reasons=["policy_engine_disabled"],
            )
        return self.store.evaluate_policy(request, self.config.policy_engine.default_allow)

    def list_policy_constraints(
        self, user_id: str, limit: int | None = None
    ) -> list[PolicyConstraintRecord]:
        return self.store.list_policy_constraints(user_id, limit)

    def revoke_policy_constraint(self, constraint_id: str, user_id: str) -> PolicyConstraintRecord:
        return self.store.revoke_policy_constraint(constraint_id, user_id)

    def purge_policy_constraint(self, constraint_id: str, user_id: str) -> None:
        self.store.purge_policy_constraint(constraint_id, user_id)

    def proactivity(self, request: ProactivityRequest) -> ProactivityDecision:
        decision = decide_proactivity(request, self.config)
        gate = self.evaluate_policy(
            PolicyGateRequest(
                user_id=request.user_id,
                scope=request.scope,
                actions=["proactive_contact"],
                channel=request.channel,
                as_of=request.as_of,
            )
        )
        if gate.allowed:
            return decision
        return decision.model_copy(
            update={
                "should_reach_out": False,
                "reasons": [*decision.reasons, *gate.reasons, "policy_gate_denied"],
                "next_allowed_at": None,
            }
        )

    def create_open_loop(self, item: OpenLoopInput) -> OpenLoopStorageResult:
        return experience_service.create_open_loop(self, item)

    def update_open_loop(self, open_loop_id: str, request: OpenLoopUpdateRequest) -> OpenLoopRecord:
        return experience_service.update_open_loop(self, open_loop_id, request)

    def list_open_loops(
        self,
        user_id: str,
        scope: MemoryScope | None = None,
        statuses: set[OpenLoopStatus] | None = None,
        limit: int | None = None,
    ) -> list[OpenLoopRecord]:
        return experience_service.list_open_loops(self, user_id, scope, statuses, limit)

    def evaluate_follow_up(self, request: FollowUpRequest) -> FollowUpDecision:
        return experience_service.evaluate_follow_up(self, request)

    def record_reference_feedback(
        self, item: MemoryReferenceFeedbackInput
    ) -> MemoryReferenceFeedbackRecord:
        return experience_service.record_reference_feedback(self, item)

    def list_reference_feedback(
        self,
        user_id: str,
        scope: MemoryScope | None = None,
        memory_ids: list[str] | None = None,
        limit: int | None = None,
    ) -> list[MemoryReferenceFeedbackRecord]:
        return experience_service.list_reference_feedback(self, user_id, scope, memory_ids, limit)

    def plan_response(self, request: ResponsePlanRequest) -> ResponsePlanRecord:
        return experience_service.plan_response(self, request)

    def stage_response_plan(self, request: ResponsePlanRequest) -> ResponsePlanRecord:
        return experience_service.stage_response_plan(self, request)

    def resolve_staged_response_plan(
        self, plan_id: str, request: ResponsePlanResolveRequest
    ) -> ResponsePlanRecord:
        return experience_service.resolve_staged_response_plan(self, plan_id, request)

    def _resolved_response_components(
        self, request: ResponsePlanRequest
    ) -> tuple[
        RetrievalAction | None,
        MemoryUsePlan,
        FollowUpDecision | None,
        list[ResponseBeatRecord],
    ]:
        return experience_service._resolved_response_components(self, request)

    def get_response_plan(self, plan_id: str, user_id: str) -> ResponsePlanRecord:
        return experience_service.get_response_plan(self, plan_id, user_id)

    def interrupt_response_plans(self, request: ResponsePlanInterruptRequest) -> list[str]:
        return experience_service.interrupt_response_plans(self, request)

    def list_response_plans(
        self,
        user_id: str,
        scope: MemoryScope | None = None,
        statuses: set[ResponsePlanStatus] | None = None,
        limit: int | None = None,
    ) -> list[ResponsePlanRecord]:
        return experience_service.list_response_plans(self, user_id, scope, statuses, limit)

    def cancel_response_plan(
        self,
        plan_id: str,
        user_id: str,
        reason: str,
        as_of: datetime | None = None,
    ) -> ResponsePlanRecord:
        return experience_service.cancel_response_plan(self, plan_id, user_id, reason, as_of)

    def mark_response_beat_sent(
        self,
        plan_id: str,
        beat_id: str,
        request: ResponseBeatSentRequest,
    ) -> ResponsePlanRecord:
        return experience_service.mark_response_beat_sent(self, plan_id, beat_id, request)

    def apply_repair(self, request: ConversationRepairRequest) -> ConversationRepairResult:
        return experience_service.apply_repair(self, request)

    def interpret_turn(self, request: DiscourseInterpretRequest) -> DiscourseInterpretation:
        return experience_service.interpret_turn(self, request)

    @staticmethod
    def _direct_user_discourse_text(turn: ConversationTurnRecord) -> str:
        return experience_service._direct_user_discourse_text(turn)

    def stage_interpreted_response_plan(
        self, request: InterpretedResponsePlanRequest
    ) -> InterpretedResponsePlan:
        return experience_service.stage_interpreted_response_plan(self, request)

    def _recall_item(
        self,
        candidate: MemorySearchCandidate,
        request: RecallRequest,
        temporal_hint: TemporalHint,
    ) -> RecallItem:
        return recall_service._recall_item(self, candidate, request, temporal_hint)

    def _recall_events(
        self,
        request: RecallRequest,
        temporal_hint: TemporalHint,
        fts_query: str,
        event_after: datetime | None,
        event_before: datetime | None,
        event_limit: int,
        has_cues: bool,
    ) -> list[EventRecallItem]:
        return recall_service._recall_events(
            self,
            request,
            temporal_hint,
            fts_query,
            event_after,
            event_before,
            event_limit,
            has_cues,
        )

    def _event_item(
        self,
        candidate: EventSearchCandidate,
        request: RecallRequest,
        temporal_hint: TemporalHint,
    ) -> EventRecallItem:
        return recall_service._event_item(self, candidate, request, temporal_hint)

    def _recall_turns(
        self,
        request: RecallRequest,
        temporal_hint: TemporalHint,
        fts_query: str,
        event_after: datetime | None,
        event_before: datetime | None,
        turn_limit: int,
        has_cues: bool,
    ) -> list[TurnRecallItem]:
        return recall_service._recall_turns(
            self, request, temporal_hint, fts_query, event_after, event_before, turn_limit, has_cues
        )

    def _turn_item(
        self,
        candidate: TurnSearchCandidate,
        request: RecallRequest,
        temporal_hint: TemporalHint,
    ) -> TurnRecallItem:
        return recall_service._turn_item(self, candidate, request, temporal_hint)

    @staticmethod
    def _direct_utterance_text(turn: ConversationTurnRecord, actor_id: str) -> str:
        return recall_service._direct_utterance_text(turn, actor_id)

    def _use_mode(self, confidence: float) -> RecallUseMode:
        return recall_service._use_mode(self, confidence)

    @staticmethod
    def _can_answer_from_structured(
        item: RecallItem,
        request: RecallRequest,
        temporal_hint: TemporalHint,
    ) -> bool:
        return recall_service._can_answer_from_structured(item, request, temporal_hint)

    def _calibrate_short_query_confidence(
        self,
        confidence: float,
        score: ScoreBreakdown,
        request: RecallRequest,
    ) -> float:
        return recall_service._calibrate_short_query_confidence(self, confidence, score, request)

    @staticmethod
    def _score_confidence(score: ScoreBreakdown) -> float:
        return recall_service._score_confidence(score)

    @staticmethod
    def _temporal_hint(request: RecallRequest) -> TemporalHint:
        return recall_service._temporal_hint(request)

    def _temporal_context(
        self, request: RecallRequest
    ) -> tuple[TemporalHint, TemporalAnchorRecord | None, list[TemporalAnchorRecord]]:
        return recall_service._temporal_context(self, request)

    @staticmethod
    def _has_retrieval_cues(request: RecallRequest, temporal_hint: TemporalHint) -> bool:
        return recall_service._has_retrieval_cues(request, temporal_hint)

    def _is_ambiguous(
        self,
        items: list[RecallItem],
        event_items: list[EventRecallItem],
        request: RecallRequest,
        temporal_hint: TemporalHint,
    ) -> bool:
        return recall_service._is_ambiguous(self, items, event_items, request, temporal_hint)

    def _memory_pair_is_ambiguous(
        self,
        first: RecallItem,
        second: RecallItem,
        request: RecallRequest,
        temporal_hint: TemporalHint,
    ) -> bool:
        return recall_service._memory_pair_is_ambiguous(self, first, second, request, temporal_hint)

    def _turns_are_ambiguous(
        self, items: list[TurnRecallItem], temporal_hint: TemporalHint
    ) -> bool:
        return recall_service._turns_are_ambiguous(self, items, temporal_hint)

    @staticmethod
    def _retrieval_action(
        outcome: RetrievalOutcome,
        cardinality: AnswerCardinality,
        answer_count: int,
    ) -> RetrievalAction:
        return recall_service._retrieval_action(outcome, cardinality, answer_count)

    @staticmethod
    def _append_section(sections: dict[str, list[RecallItem]], item: RecallItem) -> None:
        return recall_service._append_section(sections, item)

    @staticmethod
    def _of_kind(memories: list[MemoryRecord], kind: MemoryKind) -> list[MemoryRecord]:
        return state_service._of_kind(memories, kind)

    @staticmethod
    def _is_direct_user_evidence(item: MemoryInput) -> bool:
        return state_service._is_direct_user_evidence(item)

    def _enforce_epistemic_eligibility(self, item: MemoryInput) -> tuple[MemoryInput, list[str]]:
        return state_service._enforce_epistemic_eligibility(self, item)
