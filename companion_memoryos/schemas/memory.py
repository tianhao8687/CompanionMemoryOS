from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator, model_validator

from companion_memoryos.constants import (
    RECALL_QUERY_MAX_CHARACTERS,
    UNIT_INTERVAL_MAX,
    UNIT_INTERVAL_MIN,
)
from companion_memoryos.schemas.core import (
    STATE_ANSWER_SEMANTICS,
    AnswerCardinality,
    AnswerSemantics,
    ConsentState,
    ConversationRole,
    ElicitationKind,
    EmotionSignal,
    EntityRef,
    EpistemicKind,
    EventStatus,
    EvidenceActor,
    MemoryKind,
    MemoryScope,
    MemoryStatus,
    RealityLayer,
    RecallIntent,
    RecallUseMode,
    ResolutionStatus,
    RetentionClass,
    ReviewDecision,
    Sensitivity,
    StorageAction,
    StrictModel,
    TemporalAnchorStatus,
    _validate_embedding,
)


class MemoryInput(StrictModel):
    user_id: str = Field(min_length=1, max_length=128)
    scope: MemoryScope = Field(default_factory=MemoryScope)
    kind: MemoryKind
    title: str = Field(min_length=1, max_length=240)
    content: str = Field(min_length=1, max_length=20_000)
    stable_key: str | None = Field(default=None, max_length=240)
    emotions: list[EmotionSignal] = Field(default_factory=list, max_length=12)
    needs: list[str] = Field(default_factory=list, max_length=20)
    consent: ConsentState = ConsentState.UNKNOWN
    explicit_user_request: bool = False
    sensitivity: Sensitivity = Sensitivity.NORMAL
    retention: RetentionClass | None = None
    confidence: float = Field(default=UNIT_INTERVAL_MAX, ge=UNIT_INTERVAL_MIN, le=UNIT_INTERVAL_MAX)
    salience: float = Field(default=UNIT_INTERVAL_MAX, ge=UNIT_INTERVAL_MIN, le=UNIT_INTERVAL_MAX)
    event_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    valid_time_start: datetime | None = None
    valid_time_end: datetime | None = None
    source_ref: str = Field(default="conversation", min_length=1, max_length=500)
    source_excerpt: str | None = Field(default=None, max_length=2_000)
    entities: list[EntityRef] = Field(default_factory=list, max_length=32)
    embedding: list[float] | None = Field(default=None, min_length=1, max_length=4_096)
    embedding_space: str | None = Field(default=None, min_length=1, max_length=240)
    epistemic_kind: EpistemicKind = EpistemicKind.OBSERVATION
    resolution_status: ResolutionStatus = ResolutionStatus.RESOLVED
    reality_layer: RealityLayer = RealityLayer.REAL_WORLD
    source_actor: EvidenceActor = EvidenceActor.AUTHENTICATED_USER
    quote_depth: int = Field(default=0, ge=0)
    elicitation_kind: ElicitationKind = ElicitationKind.SPONTANEOUS
    subject_actor_id: str | None = Field(default=None, max_length=240)
    predicate: str | None = Field(default=None, max_length=240)
    evidence_turn_ids: list[str] = Field(default_factory=list, max_length=64)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator(
        "user_id",
        "title",
        "content",
        "stable_key",
        "source_ref",
        "source_excerpt",
        "subject_actor_id",
        "predicate",
    )
    @classmethod
    def reject_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("value cannot be blank")
        return value.strip() if value is not None else None

    @field_validator("needs")
    @classmethod
    def normalize_needs(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip().casefold() for value in values if value.strip()))

    @field_validator("event_at", "valid_time_start", "valid_time_end")
    @classmethod
    def require_aware_event_time(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("memory timestamps must include a timezone")
        return value.astimezone(UTC)

    @field_validator("evidence_turn_ids")
    @classmethod
    def normalize_evidence_turn_ids(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip() for value in values if value.strip()))

    @field_validator("predicate")
    @classmethod
    def normalize_predicate(cls, value: str | None) -> str | None:
        return value.casefold() if value is not None else None

    @model_validator(mode="after")
    def valid_embedding(self) -> MemoryInput:
        _validate_embedding(self.embedding, self.embedding_space)
        if (
            self.valid_time_start is not None
            and self.valid_time_end is not None
            and self.valid_time_start >= self.valid_time_end
        ):
            raise ValueError("valid_time_start must be earlier than valid_time_end")
        return self


class MemoryCorrectionRequest(StrictModel):
    user_id: str = Field(min_length=1, max_length=128)
    content: str = Field(min_length=1, max_length=20_000)
    title: str | None = Field(default=None, max_length=240)
    consent: ConsentState = ConsentState.UNKNOWN
    event_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    valid_time_start: datetime | None = None
    valid_time_end: datetime | None = None
    source_ref: str = Field(default="conversation:correction", min_length=1, max_length=500)
    source_excerpt: str | None = Field(default=None, max_length=2_000)
    emotions: list[EmotionSignal] | None = Field(default=None, max_length=12)
    needs: list[str] | None = Field(default=None, max_length=20)
    entities: list[EntityRef] | None = Field(default=None, max_length=32)
    embedding: list[float] | None = Field(default=None, min_length=1, max_length=4_096)
    embedding_space: str | None = Field(default=None, min_length=1, max_length=240)
    evidence_turn_ids: list[str] = Field(default_factory=list, max_length=64)

    @field_validator("user_id", "content", "title", "source_ref", "source_excerpt")
    @classmethod
    def reject_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("value cannot be blank")
        return value.strip() if value is not None else None

    @field_validator("needs")
    @classmethod
    def normalize_needs(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        return list(dict.fromkeys(value.strip().casefold() for value in values if value.strip()))

    @field_validator("evidence_turn_ids")
    @classmethod
    def normalize_evidence_turn_ids(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip() for value in values if value.strip()))

    @field_validator("event_at", "valid_time_start", "valid_time_end")
    @classmethod
    def require_aware_event_time(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("correction timestamps must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def valid_embedding(self) -> MemoryCorrectionRequest:
        _validate_embedding(self.embedding, self.embedding_space)
        if (
            self.valid_time_start is not None
            and self.valid_time_end is not None
            and self.valid_time_start >= self.valid_time_end
        ):
            raise ValueError("valid_time_start must be earlier than valid_time_end")
        return self


class ConversationEventInput(StrictModel):
    user_id: str = Field(min_length=1, max_length=128)
    scope: MemoryScope = Field(default_factory=MemoryScope)
    session_id: str = Field(min_length=1, max_length=240)
    role: ConversationRole
    content: str = Field(min_length=1, max_length=20_000)
    consent: ConsentState = ConsentState.UNKNOWN
    sensitivity: Sensitivity = Sensitivity.NORMAL
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source_ref: str = Field(default="conversation", min_length=1, max_length=500)
    entities: list[EntityRef] = Field(default_factory=list, max_length=32)
    embedding: list[float] | None = Field(default=None, min_length=1, max_length=4_096)
    embedding_space: str | None = Field(default=None, min_length=1, max_length=240)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("user_id", "session_id", "content", "source_ref")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value cannot be blank")
        return value.strip()

    @field_validator("occurred_at")
    @classmethod
    def require_aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("occurred_at must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def valid_embedding(self) -> ConversationEventInput:
        _validate_embedding(self.embedding, self.embedding_space)
        if self.scope.conversation_id is not None and self.scope.conversation_id != self.session_id:
            raise ValueError("scope.conversation_id must match session_id")
        return self


class RecallRequest(StrictModel):
    user_id: str = Field(min_length=1, max_length=128)
    exclude_turn_ids: list[str] = Field(default_factory=list, max_length=128)
    scope: MemoryScope = Field(default_factory=MemoryScope)
    query: str = Field(default="", max_length=RECALL_QUERY_MAX_CHARACTERS)
    intent: RecallIntent = RecallIntent.GENERAL
    emotions: list[EmotionSignal] = Field(default_factory=list, max_length=12)
    needs: list[str] = Field(default_factory=list, max_length=20)
    entity_ids: list[str] = Field(default_factory=list, max_length=32)
    limit: int | None = Field(default=None, gt=0)
    event_limit: int | None = Field(default=None, ge=0)
    turn_limit: int | None = Field(default=None, ge=0)
    max_characters: int | None = Field(default=None, gt=0)
    max_tokens: int | None = Field(default=None, gt=0)
    event_after: datetime | None = None
    event_before: datetime | None = None
    query_embedding: list[float] | None = Field(default=None, min_length=1, max_length=4_096)
    embedding_space: str | None = Field(default=None, min_length=1, max_length=240)
    answer_semantics: AnswerSemantics = AnswerSemantics.EVENT_RECALL
    answer_cardinality: AnswerCardinality = AnswerCardinality.AUTO
    utterance_actor_id: str | None = Field(default=None, max_length=240)
    state_predicate: str | None = Field(default=None, max_length=240)
    state_subject_actor_id: str | None = Field(default=None, min_length=1, max_length=240)
    state_reality_layer: RealityLayer = RealityLayer.REAL_WORLD
    calendar_timezone: str = "UTC"
    valid_at: datetime | None = None
    known_at: datetime | None = None
    as_of: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("needs")
    @classmethod
    def normalize_needs(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip().casefold() for value in values if value.strip()))

    @field_validator("entity_ids")
    @classmethod
    def normalize_entity_ids(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip().casefold() for value in values if value.strip()))

    @field_validator("state_predicate")
    @classmethod
    def normalize_state_predicate(cls, value: str | None) -> str | None:
        return value.casefold() if value is not None else None

    @field_validator("utterance_actor_id", "state_subject_actor_id")
    @classmethod
    def normalize_utterance_actor_id(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("utterance_actor_id cannot be blank")
        return value.strip() if value is not None else None

    @field_validator("calendar_timezone")
    @classmethod
    def validate_calendar_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("calendar_timezone must be an IANA timezone") from exc
        return value

    @field_validator("as_of", "event_after", "event_before", "valid_at", "known_at")
    @classmethod
    def require_aware_as_of(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("recall timestamps must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def valid_filters(self) -> RecallRequest:
        _validate_embedding(self.query_embedding, self.embedding_space)
        if (
            self.event_after is not None
            and self.event_before is not None
            and self.event_after >= self.event_before
        ):
            raise ValueError("event_after must be earlier than event_before")
        if self.answer_semantics in STATE_ANSWER_SEMANTICS and not self.state_predicate:
            raise ValueError("state_predicate is required for state answer semantics")
        if self.state_predicate is not None and self.answer_semantics not in STATE_ANSWER_SEMANTICS:
            raise ValueError("state_predicate requires explicit state answer semantics")
        if self.state_subject_actor_id is not None and self.state_predicate is None:
            raise ValueError("state_subject_actor_id requires a state predicate")
        if (
            self.answer_semantics is AnswerSemantics.UTTERANCE_HISTORY
            and self.utterance_actor_id is None
        ):
            raise ValueError("utterance_actor_id is required for utterance history")
        if (
            self.utterance_actor_id is not None
            and self.answer_semantics is not AnswerSemantics.UTTERANCE_HISTORY
        ):
            raise ValueError("utterance_actor_id requires utterance history semantics")
        return self


class ReviewRequest(StrictModel):
    user_id: str = Field(min_length=1, max_length=128)
    decision: ReviewDecision


class StoragePolicyDecision(StrictModel):
    action: StorageAction
    retention: RetentionClass
    expires_at: datetime | None
    reasons: list[str]


class MemoryRecord(StrictModel):
    id: str
    user_id: str
    scope: MemoryScope = Field(default_factory=MemoryScope)
    kind: MemoryKind
    title: str
    content: str
    stable_key: str | None
    emotions: list[EmotionSignal]
    needs: list[str]
    status: MemoryStatus
    consent: ConsentState
    sensitivity: Sensitivity
    retention: RetentionClass
    confidence: float
    salience: float
    event_at: datetime
    valid_time_start: datetime
    valid_time_end: datetime | None
    valid_from: datetime
    valid_to: datetime | None
    expires_at: datetime | None
    supersedes_id: str | None
    source_ref: str
    content_hash: str
    entities: list[EntityRef]
    epistemic_kind: EpistemicKind
    resolution_status: ResolutionStatus
    reality_layer: RealityLayer
    source_actor: EvidenceActor
    quote_depth: int
    elicitation_kind: ElicitationKind
    subject_actor_id: str | None
    predicate: str | None
    evidence_turn_ids: list[str]
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class StorageResult(StrictModel):
    action: StorageAction
    memory: MemoryRecord | None
    duplicate_of: str | None = None
    reasons: list[str] = Field(default_factory=list)


class MemoryCorrectionResult(StrictModel):
    previous_memory_id: str
    action: StorageAction
    memory: MemoryRecord | None
    duplicate_of: str | None = None
    reasons: list[str] = Field(default_factory=list)


class TemporalAnchorInput(StrictModel):
    user_id: str = Field(min_length=1, max_length=128)
    scope: MemoryScope = Field(default_factory=MemoryScope)
    name: str = Field(min_length=1, max_length=240)
    aliases: list[str] = Field(default_factory=list, max_length=32)
    start_at: datetime
    end_at: datetime
    consent: ConsentState = ConsentState.UNKNOWN
    sensitivity: Sensitivity = Sensitivity.NORMAL
    source_ref: str = Field(default="conversation:time-anchor", min_length=1, max_length=500)
    source_excerpt: str | None = Field(default=None, max_length=2_000)

    @field_validator("user_id", "name", "source_ref", "source_excerpt")
    @classmethod
    def reject_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("value cannot be blank")
        return value.strip() if value is not None else None

    @field_validator("aliases")
    @classmethod
    def normalize_aliases(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip() for value in values if value.strip()))

    @field_validator("start_at", "end_at")
    @classmethod
    def require_aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("temporal anchor timestamps must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def ordered_window(self) -> TemporalAnchorInput:
        if self.start_at >= self.end_at:
            raise ValueError("start_at must be earlier than end_at")
        return self


class TemporalAnchorRecord(StrictModel):
    id: str
    user_id: str
    scope: MemoryScope = Field(default_factory=MemoryScope)
    name: str
    aliases: list[str]
    start_at: datetime
    end_at: datetime
    status: TemporalAnchorStatus
    consent: ConsentState
    sensitivity: Sensitivity
    source_ref: str
    supersedes_id: str | None
    valid_from: datetime
    valid_to: datetime | None
    created_at: datetime
    updated_at: datetime


class TemporalAnchorStorageResult(StrictModel):
    stored: bool
    anchor: TemporalAnchorRecord | None = None
    reasons: list[str] = Field(default_factory=list)


class ScoreBreakdown(StrictModel):
    lexical: float
    semantic: float
    entity: float
    temporal: float
    salience: float
    recency: float
    emotion: float
    need: float
    continuity: float
    total: float


class RecallItem(StrictModel):
    memory: MemoryRecord
    score: ScoreBreakdown
    reasons: list[str]
    pinned: bool = False
    recall_confidence: float
    use_mode: RecallUseMode


class ConversationEventRecord(StrictModel):
    id: str
    user_id: str
    scope: MemoryScope = Field(default_factory=MemoryScope)
    session_id: str
    role: ConversationRole
    content: str
    status: EventStatus
    consent: ConsentState
    sensitivity: Sensitivity
    occurred_at: datetime
    expires_at: datetime
    source_ref: str
    entities: list[EntityRef]
    metadata: dict[str, Any]
    created_at: datetime


class EventStorageResult(StrictModel):
    stored: bool
    event: ConversationEventRecord | None = None
    reasons: list[str] = Field(default_factory=list)


class EventRecallItem(StrictModel):
    event: ConversationEventRecord
    lexical: float
    semantic: float
    entity: float
    temporal: float
    recency: float
    total: float
    recall_confidence: float
    use_mode: RecallUseMode
    reasons: list[str]
