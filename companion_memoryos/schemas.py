from __future__ import annotations

import math
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from companion_memoryos.constants import (
    SIGNED_INTERVAL_MAX,
    SIGNED_INTERVAL_MIN,
    UNIT_INTERVAL_MAX,
    UNIT_INTERVAL_MIN,
)


class MemoryKind(StrEnum):
    IDENTITY = "identity"
    PREFERENCE = "preference"
    BOUNDARY = "boundary"
    SUPPORT_STRATEGY = "support_strategy"
    COMMITMENT = "commitment"
    RITUAL = "ritual"
    EMOTION_EPISODE = "emotion_episode"
    SHARED_MOMENT = "shared_moment"
    WELLBEING_SIGNAL = "wellbeing_signal"
    RELATIONSHIP = "relationship"


class MemoryStatus(StrEnum):
    CANDIDATE = "candidate"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    FORGOTTEN = "forgotten"
    REJECTED = "rejected"
    EXPIRED = "expired"


class ConsentState(StrEnum):
    UNKNOWN = "unknown"
    GRANTED = "granted"
    DENIED = "denied"


class Sensitivity(StrEnum):
    NORMAL = "normal"
    SENSITIVE = "sensitive"
    HIGHLY_SENSITIVE = "highly_sensitive"


class RetentionClass(StrEnum):
    EPHEMERAL = "ephemeral"
    SHORT_TERM = "short_term"
    LONG_TERM = "long_term"
    DURABLE = "durable"


class RecallIntent(StrEnum):
    GENERAL = "general"
    COMFORT = "comfort"
    CELEBRATE = "celebrate"
    REFLECT = "reflect"
    PLAN = "plan"
    CHECK_IN = "check_in"


class ReviewDecision(StrEnum):
    CONFIRM = "confirm"
    REJECT = "reject"


class StorageAction(StrEnum):
    ACTIVATE = "activate"
    CANDIDATE = "candidate"
    DISCARD = "discard"


class ConversationRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class EventStatus(StrEnum):
    ACTIVE = "active"
    FORGOTTEN = "forgotten"
    EXPIRED = "expired"


class RecallUseMode(StrEnum):
    NATURAL = "natural"
    HEDGE = "hedge"
    DO_NOT_ASSERT = "do_not_assert"


class RetrievalOutcome(StrEnum):
    MATCH = "match"
    AMBIGUOUS = "ambiguous"
    NO_MATCH = "no_match"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class EmotionSignal(StrictModel):
    label: str = Field(min_length=1, max_length=64)
    valence: float = Field(
        default=UNIT_INTERVAL_MIN, ge=SIGNED_INTERVAL_MIN, le=SIGNED_INTERVAL_MAX
    )
    arousal: float = Field(default=UNIT_INTERVAL_MIN, ge=UNIT_INTERVAL_MIN, le=UNIT_INTERVAL_MAX)
    intensity: float = Field(default=UNIT_INTERVAL_MAX, ge=UNIT_INTERVAL_MIN, le=UNIT_INTERVAL_MAX)

    @field_validator("label")
    @classmethod
    def normalize_label(cls, value: str) -> str:
        return value.casefold()


class EntityRef(StrictModel):
    id: str = Field(min_length=1, max_length=240)
    kind: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=240)
    aliases: list[str] = Field(default_factory=list, max_length=32)

    @field_validator("id", "kind")
    @classmethod
    def normalize_identifier(cls, value: str) -> str:
        return value.casefold()

    @field_validator("aliases")
    @classmethod
    def normalize_aliases(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip() for value in values if value.strip()))


class MemoryInput(StrictModel):
    user_id: str = Field(min_length=1, max_length=128)
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
    source_ref: str = Field(default="conversation", min_length=1, max_length=500)
    source_excerpt: str | None = Field(default=None, max_length=2_000)
    entities: list[EntityRef] = Field(default_factory=list, max_length=32)
    embedding: list[float] | None = Field(default=None, min_length=1, max_length=4_096)
    embedding_space: str | None = Field(default=None, min_length=1, max_length=240)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("user_id", "title", "content", "stable_key", "source_ref", "source_excerpt")
    @classmethod
    def reject_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("value cannot be blank")
        return value.strip() if value is not None else None

    @field_validator("needs")
    @classmethod
    def normalize_needs(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip().casefold() for value in values if value.strip()))

    @field_validator("event_at")
    @classmethod
    def require_aware_event_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("event_at must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def valid_embedding(self) -> MemoryInput:
        _validate_embedding(self.embedding, self.embedding_space)
        return self


class ConversationEventInput(StrictModel):
    user_id: str = Field(min_length=1, max_length=128)
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
        return self


class RecallRequest(StrictModel):
    user_id: str = Field(min_length=1, max_length=128)
    query: str = Field(default="", max_length=4_000)
    intent: RecallIntent = RecallIntent.GENERAL
    emotions: list[EmotionSignal] = Field(default_factory=list, max_length=12)
    needs: list[str] = Field(default_factory=list, max_length=20)
    entity_ids: list[str] = Field(default_factory=list, max_length=32)
    limit: int | None = Field(default=None, gt=0)
    event_limit: int | None = Field(default=None, ge=0)
    max_characters: int | None = Field(default=None, gt=0)
    max_tokens: int | None = Field(default=None, gt=0)
    event_after: datetime | None = None
    event_before: datetime | None = None
    query_embedding: list[float] | None = Field(default=None, min_length=1, max_length=4_096)
    embedding_space: str | None = Field(default=None, min_length=1, max_length=240)
    as_of: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("needs")
    @classmethod
    def normalize_needs(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip().casefold() for value in values if value.strip()))

    @field_validator("entity_ids")
    @classmethod
    def normalize_entity_ids(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip().casefold() for value in values if value.strip()))

    @field_validator("as_of", "event_after", "event_before")
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
    valid_from: datetime
    valid_to: datetime | None
    expires_at: datetime | None
    supersedes_id: str | None
    source_ref: str
    content_hash: str
    entities: list[EntityRef]
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class StorageResult(StrictModel):
    action: StorageAction
    memory: MemoryRecord | None
    duplicate_of: str | None = None
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


class CompanionContext(StrictModel):
    user_id: str
    intent: RecallIntent
    sections: dict[str, list[RecallItem]]
    event_fallback: list[EventRecallItem]
    guidance: list[str]
    pending_review_count: int
    config_fingerprint: str
    generated_at: datetime
    character_budget: int
    rendered_characters: int
    token_budget: int
    rendered_tokens: int
    tokenizer: str
    prompt_text: str
    retrieval_outcome: RetrievalOutcome
    ambiguity_detected: bool = False
    clarification_guidance: str | None = None
    safety_budget_exceeded: bool = False
    budget_exhausted: bool = False
    budget_omitted_count: int = Field(default=0, ge=0)


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

    @model_validator(mode="after")
    def verify_scope(self) -> ExportBundle:
        if any(memory.user_id != self.user_id for memory in self.memories):
            raise ValueError("export contains a memory from another user")
        if any(event.user_id != self.user_id for event in self.events):
            raise ValueError("export contains an event from another user")
        return self


class ProactivityRequest(StrictModel):
    user_id: str = Field(min_length=1, max_length=128)
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


def _validate_embedding(embedding: list[float] | None, space: str | None) -> None:
    if (embedding is None) != (space is None):
        raise ValueError("embedding and embedding_space must be supplied together")
    if embedding is not None and any(not math.isfinite(value) for value in embedding):
        raise ValueError("embedding values must be finite")
