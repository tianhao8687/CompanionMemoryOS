from __future__ import annotations

from datetime import UTC, datetime

from pydantic import Field, field_validator, model_validator

from companion_memoryos.schemas.core import (
    AnswerCardinality,
    AnswerSemantics,
    MemoryScope,
    RecallIntent,
    RetrievalAction,
    RetrievalOutcome,
    StrictModel,
)
from companion_memoryos.schemas.episode import EpisodeRecord
from companion_memoryos.schemas.experience import (
    MemoryReferenceFeedbackRecord,
    MemoryUseRecord,
    MemoryUseSummary,
    OpenLoopRecord,
    ResponsePlanRecord,
)
from companion_memoryos.schemas.interpretation import TurnInterpretationRecord
from companion_memoryos.schemas.memory import (
    ConversationEventRecord,
    EventRecallItem,
    MemoryRecord,
    RecallItem,
    TemporalAnchorRecord,
)
from companion_memoryos.schemas.policy import PolicyBundleManifest, PolicyConstraintRecord
from companion_memoryos.schemas.state import StateQueryResult
from companion_memoryos.schemas.turn import (
    ConversationTurnRecord,
    RetrievalIntegrityManifest,
    TurnRecallItem,
)


class CompanionContext(StrictModel):
    user_id: str
    scope: MemoryScope = Field(default_factory=MemoryScope)
    intent: RecallIntent
    sections: dict[str, list[RecallItem]]
    event_fallback: list[EventRecallItem]
    turn_fallback: list[TurnRecallItem] = Field(default_factory=list)
    guidance: list[str]
    pending_review_count: int
    config_fingerprint: str
    policy_bundle: PolicyBundleManifest
    generated_at: datetime
    character_budget: int
    rendered_characters: int
    token_budget: int
    rendered_tokens: int
    tokenizer: str
    prompt_text: str
    retrieval_outcome: RetrievalOutcome
    retrieval_action: RetrievalAction = RetrievalAction.ABSTAIN
    answer_semantics: AnswerSemantics = AnswerSemantics.EVENT_RECALL
    answer_cardinality: AnswerCardinality = AnswerCardinality.AUTO
    ambiguity_detected: bool = False
    clarification_guidance: str | None = None
    safety_budget_exceeded: bool = False
    budget_exhausted: bool = False
    budget_omitted_count: int = Field(default=0, ge=0)
    state_evidence_omitted_count: int = Field(default=0, ge=0)
    resolved_temporal_anchor: TemporalAnchorRecord | None = None
    temporal_anchor_candidates: list[TemporalAnchorRecord] = Field(default_factory=list)
    temporal_anchor_ambiguity: bool = False
    integrity_manifest: RetrievalIntegrityManifest = Field(
        default_factory=RetrievalIntegrityManifest
    )
    memory_use_summaries: list[MemoryUseSummary] = Field(default_factory=list)
    policy_version: int = Field(default=0, ge=0)
    state_result: StateQueryResult | None = None


class ProfileSnapshot(StrictModel):
    user_id: str
    identity: list[MemoryRecord]
    preferences: list[MemoryRecord]
    boundaries: list[MemoryRecord]
    support_strategies: list[MemoryRecord]
    rituals: list[MemoryRecord]
    relationships: list[MemoryRecord]
    pending_review_count: int


class ExportBundle(StrictModel):
    schema_version: str
    exported_at: datetime
    user_id: str
    memories: list[MemoryRecord]
    events: list[ConversationEventRecord] = Field(default_factory=list)
    temporal_anchors: list[TemporalAnchorRecord] = Field(default_factory=list)
    conversation_turns: list[ConversationTurnRecord] = Field(default_factory=list)
    memory_uses: list[MemoryUseRecord] = Field(default_factory=list)
    policy_constraints: list[PolicyConstraintRecord] = Field(default_factory=list)
    open_loops: list[OpenLoopRecord] = Field(default_factory=list)
    reference_feedback: list[MemoryReferenceFeedbackRecord] = Field(default_factory=list)
    response_plans: list[ResponsePlanRecord] = Field(default_factory=list)
    episodes: list[EpisodeRecord] = Field(default_factory=list)
    turn_interpretations: list[TurnInterpretationRecord] = Field(default_factory=list)

    @model_validator(mode="after")
    def verify_scope(self) -> ExportBundle:
        if any(item.user_id != self.user_id for item in self.episodes) or any(
            item.user_id != self.user_id for item in self.turn_interpretations
        ):
            raise ValueError("export contains interpretation or episode data from another user")
        if any(memory.user_id != self.user_id for memory in self.memories):
            raise ValueError("export contains a memory from another user")
        if any(event.user_id != self.user_id for event in self.events):
            raise ValueError("export contains an event from another user")
        if any(anchor.user_id != self.user_id for anchor in self.temporal_anchors):
            raise ValueError("export contains a temporal anchor from another user")
        if any(turn.user_id != self.user_id for turn in self.conversation_turns):
            raise ValueError("export contains a conversation turn from another user")
        if any(use.user_id != self.user_id for use in self.memory_uses):
            raise ValueError("export contains a memory use from another user")
        if any(constraint.user_id != self.user_id for constraint in self.policy_constraints):
            raise ValueError("export contains a policy constraint from another user")
        if any(open_loop.user_id != self.user_id for open_loop in self.open_loops):
            raise ValueError("export contains an open loop from another user")
        if any(feedback.user_id != self.user_id for feedback in self.reference_feedback):
            raise ValueError("export contains reference feedback from another user")
        if any(plan.user_id != self.user_id for plan in self.response_plans):
            raise ValueError("export contains a response plan from another user")
        return self


class ProactivityRequest(StrictModel):
    user_id: str = Field(min_length=1, max_length=128)
    scope: MemoryScope = Field(default_factory=MemoryScope)
    channel: str = Field(default="chat", min_length=1, max_length=128)
    permission_granted: bool | None = None
    quiet_mode: bool = False
    last_user_message_at: datetime
    last_outreach_at: datetime | None = None
    outreaches_today: int = Field(default=0, ge=0)
    has_relevant_reason: bool = False
    recent_negative_signal_at: datetime | None = None
    as_of: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator(
        "last_user_message_at", "last_outreach_at", "recent_negative_signal_at", "as_of"
    )
    @classmethod
    def require_aware_time(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("proactivity timestamps must include a timezone")
        return value.astimezone(UTC)


class ProactivityDecision(StrictModel):
    should_reach_out: bool
    reasons: list[str]
    next_allowed_at: datetime | None = None
