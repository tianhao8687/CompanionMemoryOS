from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import Field, field_validator, model_validator

from companion_memoryos.schemas.core import (
    AutomaticActionStatus,
    BeatReleaseCondition,
    ConsentState,
    DiscourseInterpretationStatus,
    DiscourseSignal,
    ExperienceEvidenceKind,
    FollowUpAction,
    FollowUpMode,
    MemoryReferenceMode,
    MemoryScope,
    MemoryUseType,
    OpenLoopKind,
    OpenLoopStatus,
    OpenLoopTransition,
    RecallIntent,
    RecallUseMode,
    ReferenceFeedbackKind,
    RepairKind,
    ResponseBeatKind,
    ResponseBeatSource,
    ResponseBeatStatus,
    ResponseDeliveryMode,
    ResponseGoal,
    ResponsePlanResolutionStatus,
    ResponsePlanStatus,
    RetrievalAction,
    Sensitivity,
    StrictModel,
)
from companion_memoryos.schemas.memory import MemoryCorrectionResult, RecallRequest
from companion_memoryos.schemas.policy import PolicyBundleManifest


class MemoryUseInput(StrictModel):
    user_id: str = Field(min_length=1, max_length=128)
    scope: MemoryScope = Field(default_factory=MemoryScope)
    memory_id: str = Field(min_length=1, max_length=240)
    response_group_id: str = Field(min_length=1, max_length=240)
    use_mode: RecallUseMode
    use_type: MemoryUseType | None = None
    purpose: str = Field(min_length=1, max_length=240)
    rendered_excerpt: str | None = Field(default=None, max_length=2_000)
    used_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def infer_legacy_type(self) -> MemoryUseInput:
        if self.use_type is None:
            self.use_type = {
                RecallUseMode.NATURAL: MemoryUseType.EXPLICIT_REFERENCE,
                RecallUseMode.HEDGE: MemoryUseType.SOFT_REFERENCE,
                RecallUseMode.DO_NOT_ASSERT: MemoryUseType.CLARIFICATION,
            }[self.use_mode]
        if self.use_type is MemoryUseType.SILENT_INFLUENCE:
            self.rendered_excerpt = None
        return self

    @field_validator("used_at")
    @classmethod
    def require_aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("used_at must include a timezone")
        return value.astimezone(UTC)


class MemoryUseRecord(StrictModel):
    id: str
    user_id: str
    scope: MemoryScope
    memory_id: str
    response_group_id: str
    use_mode: RecallUseMode
    use_type: MemoryUseType = MemoryUseType.EXPLICIT_REFERENCE
    purpose: str
    output_hash: str | None
    used_at: datetime
    created_at: datetime


class MemoryUseSummary(StrictModel):
    memory_id: str
    use_count: int = Field(ge=0)
    last_used_at: datetime | None = None


class OpenLoopInput(StrictModel):
    user_id: str = Field(min_length=1, max_length=128)
    scope: MemoryScope
    kind: OpenLoopKind
    summary: str = Field(min_length=1, max_length=2_000)
    topic_keys: list[str] = Field(default_factory=list, max_length=64)
    follow_up_mode: FollowUpMode = FollowUpMode.WHEN_RELEVANT
    follow_up_after: datetime | None = None
    expires_at: datetime | None = None
    source_turn_id: str | None = Field(default=None, min_length=1, max_length=240)
    consent: ConsentState = ConsentState.UNKNOWN
    sensitivity: Sensitivity = Sensitivity.NORMAL
    opened_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("topic_keys")
    @classmethod
    def normalize_topic_keys(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip().casefold() for value in values if value.strip()))

    @field_validator("follow_up_after", "expires_at", "opened_at")
    @classmethod
    def require_aware_time(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("open-loop timestamps must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def valid_open_loop(self) -> OpenLoopInput:
        if self.scope.relationship_id is None:
            raise ValueError("open loops require scope.relationship_id")
        if self.follow_up_mode is FollowUpMode.AT_OR_AFTER_TIME and self.follow_up_after is None:
            raise ValueError("time-based follow-up requires follow_up_after")
        if self.expires_at is not None and self.expires_at <= self.opened_at:
            raise ValueError("expires_at must be later than opened_at")
        if (
            self.expires_at is not None
            and self.follow_up_after is not None
            and self.follow_up_after >= self.expires_at
        ):
            raise ValueError("follow_up_after must be earlier than expires_at")
        return self


class OpenLoopRecord(StrictModel):
    id: str
    user_id: str
    scope: MemoryScope
    kind: OpenLoopKind
    summary: str
    topic_keys: list[str]
    follow_up_mode: FollowUpMode
    status: OpenLoopStatus
    follow_up_after: datetime | None
    expires_at: datetime | None
    source_turn_id: str | None
    consent: ConsentState
    sensitivity: Sensitivity
    resolution_summary: str | None = None
    last_followed_up_at: datetime | None = None
    follow_up_count: int = Field(default=0, ge=0)
    last_response_group_id: str | None = None
    revision: int = Field(ge=1)
    opened_at: datetime
    updated_at: datetime
    resolved_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class OpenLoopStorageResult(StrictModel):
    stored: bool
    open_loop: OpenLoopRecord | None = None
    reasons: list[str] = Field(default_factory=list)


class OpenLoopUpdateRequest(StrictModel):
    user_id: str = Field(min_length=1, max_length=128)
    transition: OpenLoopTransition
    source_turn_id: str | None = Field(default=None, min_length=1, max_length=240)
    resolution_summary: str | None = Field(default=None, max_length=2_000)
    next_follow_up_at: datetime | None = None
    response_group_id: str | None = Field(default=None, min_length=1, max_length=240)
    expected_revision: int | None = Field(default=None, ge=1)
    as_of: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("next_follow_up_at", "as_of")
    @classmethod
    def require_aware_time(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("open-loop update timestamps must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def transition_payload(self) -> OpenLoopUpdateRequest:
        if self.transition is OpenLoopTransition.SNOOZE and self.next_follow_up_at is None:
            raise ValueError("snooze requires next_follow_up_at")
        if self.next_follow_up_at is not None and self.next_follow_up_at <= self.as_of:
            raise ValueError("next_follow_up_at must be later than as_of")
        if (
            self.transition is OpenLoopTransition.MARK_FOLLOWED_UP
            and self.response_group_id is None
        ):
            raise ValueError("mark_followed_up requires response_group_id")
        return self


class FollowUpRequest(StrictModel):
    user_id: str = Field(min_length=1, max_length=128)
    scope: MemoryScope
    current_topic_keys: list[str] = Field(default_factory=list, max_length=64)
    current_turn_requires_full_attention: bool = False
    user_reopened_topic: bool = False
    reopened_open_loop_id: str | None = Field(default=None, min_length=1, max_length=240)
    allow_due_topic_switch: bool = False
    as_of: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("current_topic_keys")
    @classmethod
    def normalize_topic_keys(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip().casefold() for value in values if value.strip()))

    @field_validator("as_of")
    @classmethod
    def require_aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("follow-up timestamps must include a timezone")
        return value.astimezone(UTC)


class FollowUpDecision(StrictModel):
    action: FollowUpAction
    candidate: OpenLoopRecord | None = None
    considered_open_loop_ids: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    response_guidance: str | None = None


class MemoryReferenceFeedbackInput(StrictModel):
    user_id: str = Field(min_length=1, max_length=128)
    scope: MemoryScope = Field(default_factory=MemoryScope)
    memory_id: str | None = Field(default=None, min_length=1, max_length=240)
    evidence_kind: ExperienceEvidenceKind = ExperienceEvidenceKind.MEMORY
    evidence_id: str | None = Field(default=None, min_length=1, max_length=240)
    kind: ReferenceFeedbackKind
    source_turn_id: str | None = Field(default=None, min_length=1, max_length=240)
    note: str | None = Field(default=None, max_length=1_000)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("recorded_at")
    @classmethod
    def require_aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("reference-feedback timestamps must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def normalize_evidence_target(self) -> MemoryReferenceFeedbackInput:
        if self.evidence_kind is ExperienceEvidenceKind.OPEN_LOOP:
            raise ValueError("use an open-loop transition for follow-up feedback")
        if self.evidence_kind is ExperienceEvidenceKind.MEMORY:
            self.evidence_id = self.evidence_id or self.memory_id
            self.memory_id = self.memory_id or self.evidence_id
            if self.memory_id != self.evidence_id:
                raise ValueError("memory_id and evidence_id must identify the same memory")
        elif self.memory_id is not None:
            raise ValueError("memory_id is only valid for memory evidence")
        if self.evidence_id is None:
            raise ValueError("reference feedback requires an evidence target")
        return self


class MemoryReferenceFeedbackRecord(StrictModel):
    id: str
    user_id: str
    scope: MemoryScope
    memory_id: str | None
    evidence_kind: ExperienceEvidenceKind
    evidence_id: str
    kind: ReferenceFeedbackKind
    source_turn_id: str | None
    note: str | None
    recorded_at: datetime
    created_at: datetime


class ExperienceEvidenceRef(StrictModel):
    kind: ExperienceEvidenceKind
    id: str = Field(min_length=1, max_length=240)


class MemoryUseDecision(StrictModel):
    evidence: ExperienceEvidenceRef
    mode: MemoryReferenceMode
    reasons: list[str] = Field(default_factory=list)


class MemoryUsePlan(StrictModel):
    decisions: list[MemoryUseDecision] = Field(default_factory=list)
    guidance: list[str] = Field(default_factory=list)


class ResponsePlanRequest(StrictModel):
    user_id: str = Field(min_length=1, max_length=128)
    scope: MemoryScope
    trigger_turn_id: str = Field(min_length=1, max_length=240)
    goal: ResponseGoal
    recall_request: RecallRequest | None = None
    user_asked_memory_question: bool = False
    current_turn_requires_full_attention: bool = False
    current_topic_keys: list[str] = Field(default_factory=list, max_length=64)
    user_reopened_topic: bool = False
    reopened_open_loop_id: str | None = Field(default=None, min_length=1, max_length=240)
    allow_follow_up: bool = True
    allow_due_topic_switch: bool = False
    allow_afterthought: bool | None = None
    channel_supports_multiple_beats: bool = True
    conversation_started_at: datetime | None = None
    cancel_on_new_user_turn: bool | None = None
    as_of: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("current_topic_keys")
    @classmethod
    def normalize_topic_keys(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip().casefold() for value in values if value.strip()))

    @field_validator("conversation_started_at", "as_of")
    @classmethod
    def require_aware_time(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("response-plan timestamps must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def aligned_recall_request(self) -> ResponsePlanRequest:
        if self.scope.conversation_id is None:
            raise ValueError("response plans require scope.conversation_id")
        if self.recall_request is not None and (
            self.recall_request.user_id != self.user_id or self.recall_request.scope != self.scope
        ):
            raise ValueError("recall_request must use the response plan user and exact scope")
        return self


class ResponseBeatRecord(StrictModel):
    id: str
    ordinal: int = Field(ge=0)
    kind: ResponseBeatKind
    source: ResponseBeatSource
    release_condition: BeatReleaseCondition
    status: ResponseBeatStatus
    guidance: str
    evidence: list[ExperienceEvidenceRef] = Field(default_factory=list)
    output_hash: str | None = None
    sent_at: datetime | None = None
    cancelled_at: datetime | None = None


class ResponsePlanRecord(StrictModel):
    id: str
    response_group_id: str
    user_id: str
    scope: MemoryScope
    trigger_turn_id: str
    goal: ResponseGoal
    delivery_mode: ResponseDeliveryMode
    status: ResponsePlanStatus
    revision: int = Field(ge=0)
    resolution_status: ResponsePlanResolutionStatus
    policy_version: int = Field(ge=0)
    config_fingerprint: str
    policy_bundle: PolicyBundleManifest
    cancel_on_new_user_turn: bool
    recall_action: RetrievalAction | None = None
    memory_use_plan: MemoryUsePlan
    follow_up: FollowUpDecision | None = None
    beats: list[ResponseBeatRecord] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None = None
    cancelled_at: datetime | None = None
    cancellation_reason: str | None = None


class ResponsePlanResolveRequest(StrictModel):
    user_id: str = Field(min_length=1, max_length=128)
    expected_revision: int = Field(ge=0)
    resolution_key: str = Field(min_length=1, max_length=240)
    as_of: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("as_of")
    @classmethod
    def require_aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("resolution timestamps must include a timezone")
        return value.astimezone(UTC)


class ResponsePlanInterruptRequest(StrictModel):
    user_id: str = Field(min_length=1, max_length=128)
    scope: MemoryScope
    reason: str = Field(default="new_user_input", min_length=1, max_length=240)
    as_of: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("as_of")
    @classmethod
    def require_aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("interrupt timestamps must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def require_conversation(self) -> ResponsePlanInterruptRequest:
        if self.scope.conversation_id is None:
            raise ValueError("interrupts require an exact conversation scope")
        return self


class ResponseBeatSentRequest(StrictModel):
    user_id: str = Field(min_length=1, max_length=128)
    rendered_text: str = Field(min_length=1, max_length=50_000)
    task_policy_version: int = Field(ge=0)
    host_release_signal: bool = False
    silently_used_memory_ids: list[str] = Field(default_factory=list, max_length=128)
    sent_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("sent_at")
    @classmethod
    def require_aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("sent_at must include a timezone")
        return value.astimezone(UTC)


class ConversationRepairRequest(StrictModel):
    user_id: str = Field(min_length=1, max_length=128)
    scope: MemoryScope = Field(default_factory=MemoryScope)
    kind: RepairKind
    source_turn_id: str | None = Field(default=None, min_length=1, max_length=240)
    memory_id: str | None = Field(default=None, min_length=1, max_length=240)
    evidence_kind: ExperienceEvidenceKind = ExperienceEvidenceKind.MEMORY
    evidence_id: str | None = Field(default=None, min_length=1, max_length=240)
    open_loop_id: str | None = Field(default=None, min_length=1, max_length=240)
    replacement_content: str | None = Field(default=None, max_length=20_000)
    replacement_title: str | None = Field(default=None, max_length=240)
    resolution_summary: str | None = Field(default=None, max_length=2_000)
    as_of: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("as_of")
    @classmethod
    def require_aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("repair timestamps must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def valid_target(self) -> ConversationRepairRequest:
        loop_actions = {RepairKind.RESOLVE_OPEN_LOOP, RepairKind.CANCEL_OPEN_LOOP}
        if self.kind is RepairKind.CORRECT_MEMORY and self.memory_id is None:
            raise ValueError("memory repair requires memory_id")
        if self.kind in {RepairKind.WRONG_REFERENCE, RepairKind.STOP_REFERENCING}:
            target = MemoryReferenceFeedbackInput(
                user_id=self.user_id,
                scope=self.scope,
                memory_id=self.memory_id,
                evidence_kind=self.evidence_kind,
                evidence_id=self.evidence_id,
                kind=ReferenceFeedbackKind.WRONG_MATCH,
            )
            self.memory_id = target.memory_id
            self.evidence_id = target.evidence_id
        if self.kind in loop_actions and self.open_loop_id is None:
            raise ValueError("open-loop repair requires open_loop_id")
        if self.kind is RepairKind.CORRECT_MEMORY and not self.replacement_content:
            raise ValueError("correct_memory requires replacement_content")
        return self


class ConversationRepairResult(StrictModel):
    applied: bool
    kind: RepairKind
    corrected_memory: MemoryCorrectionResult | None = None
    reference_feedback: MemoryReferenceFeedbackRecord | None = None
    open_loop: OpenLoopRecord | None = None
    acknowledgement_guidance: str
    reasons: list[str] = Field(default_factory=list)


class DiscourseInterpretRequest(StrictModel):
    user_id: str = Field(min_length=1, max_length=128)
    scope: MemoryScope
    turn_id: str = Field(min_length=1, max_length=240)
    current_topic_keys: list[str] = Field(default_factory=list, max_length=64)
    apply_low_risk_actions: bool = True
    as_of: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("as_of")
    @classmethod
    def require_aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("interpretation timestamps must include a timezone")
        return value.astimezone(UTC)

    @field_validator("current_topic_keys")
    @classmethod
    def normalize_topic_keys(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip().casefold() for value in values if value.strip()))

    @model_validator(mode="after")
    def require_conversation(self) -> DiscourseInterpretRequest:
        if self.scope.conversation_id is None:
            raise ValueError("discourse interpretation requires an exact conversation")
        return self


class DiscourseInterpretation(StrictModel):
    user_id: str
    scope: MemoryScope
    turn_id: str
    status: DiscourseInterpretationStatus
    signals: list[DiscourseSignal] = Field(default_factory=list)
    matched_phrases: dict[DiscourseSignal, list[str]] = Field(default_factory=dict)
    suggested_goal: ResponseGoal | None = None
    user_asked_memory_question: bool = False
    current_turn_requires_full_attention: bool = False
    interrupt_pending_response: bool = False
    automatic_action_status: AutomaticActionStatus = AutomaticActionStatus.NOT_REQUESTED
    repair: ConversationRepairResult | None = None
    cancelled_response_plan_ids: list[str] = Field(default_factory=list)
    response_guidance: list[str] = Field(default_factory=list)


class InterpretedResponsePlanRequest(StrictModel):
    user_id: str = Field(min_length=1, max_length=128)
    scope: MemoryScope
    turn_id: str = Field(min_length=1, max_length=240)
    fallback_goal: ResponseGoal = ResponseGoal.COMFORT
    recall_intent: RecallIntent = RecallIntent.GENERAL
    calendar_timezone: str = "UTC"
    enable_recall: bool = True
    current_topic_keys: list[str] = Field(default_factory=list, max_length=64)
    allow_follow_up: bool = True
    allow_afterthought: bool | None = None
    conversation_started_at: datetime | None = None
    as_of: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("calendar_timezone")
    @classmethod
    def valid_calendar_timezone(cls, value: str) -> str:
        return RecallRequest.validate_calendar_timezone(value)

    @field_validator("current_topic_keys")
    @classmethod
    def normalize_topic_keys(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip().casefold() for value in values if value.strip()))

    @field_validator("conversation_started_at", "as_of")
    @classmethod
    def require_aware_time(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("interpreted plan timestamps must include a timezone")
        return value.astimezone(UTC) if value is not None else None

    @model_validator(mode="after")
    def require_conversation(self) -> InterpretedResponsePlanRequest:
        if self.scope.conversation_id is None:
            raise ValueError("interpreted response plans require an exact conversation")
        return self


class InterpretedResponsePlan(StrictModel):
    interpretation: DiscourseInterpretation
    plan: ResponsePlanRecord
