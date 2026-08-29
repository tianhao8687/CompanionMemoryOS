from __future__ import annotations

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


class RecallRequest(StrictModel):
    user_id: str = Field(min_length=1, max_length=128)
    query: str = Field(default="", max_length=4_000)
    intent: RecallIntent = RecallIntent.GENERAL
    emotions: list[EmotionSignal] = Field(default_factory=list, max_length=12)
    needs: list[str] = Field(default_factory=list, max_length=20)
    limit: int | None = None
    max_characters: int | None = None
    as_of: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("needs")
    @classmethod
    def normalize_needs(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip().casefold() for value in values if value.strip()))

    @field_validator("as_of")
    @classmethod
    def require_aware_as_of(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("as_of must include a timezone")
        return value.astimezone(UTC)


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


class CompanionContext(StrictModel):
    user_id: str
    intent: RecallIntent
    sections: dict[str, list[RecallItem]]
    guidance: list[str]
    pending_review_count: int
    config_fingerprint: str
    generated_at: datetime
    character_budget: int
    rendered_characters: int
    safety_budget_exceeded: bool = False


class ProfileSnapshot(StrictModel):
    user_id: str
    identity: list[MemoryRecord]
    preferences: list[MemoryRecord]
    boundaries: list[MemoryRecord]
    support_strategies: list[MemoryRecord]
    rituals: list[MemoryRecord]
    pending_review_count: int


class ExportBundle(StrictModel):
    schema_version: str
    exported_at: datetime
    user_id: str
    memories: list[MemoryRecord]

    @model_validator(mode="after")
    def verify_scope(self) -> ExportBundle:
        if any(memory.user_id != self.user_id for memory in self.memories):
            raise ValueError("export contains a memory from another user")
        return self
