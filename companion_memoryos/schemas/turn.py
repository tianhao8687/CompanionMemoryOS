from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import Field, field_validator, model_validator

from companion_memoryos.constants import UNIT_INTERVAL_MAX, UNIT_INTERVAL_MIN
from companion_memoryos.schemas.core import (
    ChannelStatus,
    ConsentState,
    ConversationRole,
    MemoryScope,
    RealityLayer,
    RecallUseMode,
    Sensitivity,
    SpeechAct,
    StrictModel,
    TurnDeletionState,
    TurnModality,
    _validate_embedding,
)


class SpeechSpan(StrictModel):
    start_offset: int = Field(ge=0)
    end_offset: int = Field(gt=0)
    quote_depth: int = Field(default=0, ge=0)
    attributed_speaker_id: str | None = Field(default=None, max_length=240)
    target_actor_id: str | None = Field(default=None, max_length=240)
    reality_layer: RealityLayer = RealityLayer.REAL_WORLD
    speech_act: SpeechAct = SpeechAct.OTHER
    machine_generated: bool = True
    model_fingerprint: str | None = Field(default=None, min_length=1, max_length=500)
    confidence: float = Field(
        default=UNIT_INTERVAL_MAX,
        ge=UNIT_INTERVAL_MIN,
        le=UNIT_INTERVAL_MAX,
    )

    @model_validator(mode="after")
    def ordered_offsets(self) -> SpeechSpan:
        if self.start_offset >= self.end_offset:
            raise ValueError("start_offset must be earlier than end_offset")
        if self.machine_generated and self.model_fingerprint is None:
            raise ValueError("machine-generated speech spans require a model fingerprint")
        return self


class ConversationTurnInput(StrictModel):
    user_id: str = Field(min_length=1, max_length=128)
    scope: MemoryScope
    actor_id: str = Field(min_length=1, max_length=240)
    role: ConversationRole
    content: str = Field(min_length=1, max_length=50_000)
    consent: ConsentState = ConsentState.UNKNOWN
    sensitivity: Sensitivity = Sensitivity.NORMAL
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    modality: TurnModality = TurnModality.TEXT
    language: str | None = Field(default=None, max_length=64)
    reply_to_turn_id: str | None = Field(default=None, max_length=240)
    supersedes_turn_id: str | None = Field(default=None, max_length=240)
    episode_id: str | None = Field(default=None, max_length=240)
    source_ref: str = Field(default="conversation:turn", min_length=1, max_length=500)
    idempotency_key: str | None = Field(default=None, max_length=500)
    speech_spans: list[SpeechSpan] = Field(default_factory=list, max_length=128)
    retrieval_keys: list[str] = Field(default_factory=list, max_length=128)
    embedding: list[float] | None = Field(default=None, min_length=1, max_length=4_096)
    embedding_space: str | None = Field(default=None, min_length=1, max_length=240)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator(
        "user_id",
        "actor_id",
        "content",
        "language",
        "reply_to_turn_id",
        "supersedes_turn_id",
        "episode_id",
        "source_ref",
        "idempotency_key",
    )
    @classmethod
    def reject_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("value cannot be blank")
        return value.strip() if value is not None else None

    @field_validator("occurred_at")
    @classmethod
    def require_aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("occurred_at must include a timezone")
        return value.astimezone(UTC)

    @field_validator("retrieval_keys")
    @classmethod
    def normalize_retrieval_keys(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip() for value in values if value.strip()))

    @model_validator(mode="after")
    def requires_conversation_scope(self) -> ConversationTurnInput:
        if self.scope.conversation_id is None:
            raise ValueError("conversation turns require scope.conversation_id")
        if any(span.end_offset > len(self.content) for span in self.speech_spans):
            raise ValueError("speech span exceeds content length")
        _validate_embedding(self.embedding, self.embedding_space)
        return self


class ConversationTurnRecord(StrictModel):
    id: str
    server_sequence: int
    user_id: str
    scope: MemoryScope
    actor_id: str
    role: ConversationRole
    content: str
    consent: ConsentState
    sensitivity: Sensitivity
    occurred_at: datetime
    ingested_at: datetime
    modality: TurnModality
    language: str | None
    reply_to_turn_id: str | None
    supersedes_turn_id: str | None
    episode_id: str | None = None
    source_ref: str
    idempotency_key: str | None
    speech_spans: list[SpeechSpan]
    retrieval_keys: list[str] = Field(default_factory=list)
    embedding_space: str | None = None
    content_hash: str
    deletion_state: TurnDeletionState
    metadata: dict[str, Any]


class ConversationTurnStorageResult(StrictModel):
    stored: bool
    turn: ConversationTurnRecord | None = None
    duplicate_of: str | None = None
    cancelled_response_plan_ids: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class TurnRecallItem(StrictModel):
    turn: ConversationTurnRecord
    evidence_text: str
    lexical: float
    semantic: float = UNIT_INTERVAL_MIN
    temporal: float
    recency: float
    total: float
    recall_confidence: float
    use_mode: RecallUseMode
    reasons: list[str]


class ChannelWatermark(StrictModel):
    channel: str
    status: ChannelStatus
    durable_sequence: int | None = Field(default=None, ge=0)
    indexed_sequence: int | None = Field(default=None, ge=0)
    model_fingerprint: str | None = None
    updated_at: datetime | None = None


class RetrievalIntegrityManifest(StrictModel):
    channels: list[ChannelWatermark] = Field(default_factory=list)
    negative_claim_safe: bool = False
    reasons: list[str] = Field(default_factory=list)


class ProcessingWatermarkInput(StrictModel):
    user_id: str = Field(min_length=1, max_length=128)
    scope: MemoryScope = Field(default_factory=MemoryScope)
    channel: str = Field(min_length=1, max_length=128)
    status: ChannelStatus
    durable_sequence: int | None = Field(default=None, ge=0)
    indexed_sequence: int | None = Field(default=None, ge=0)
    model_fingerprint: str | None = Field(default=None, max_length=500)

    @field_validator("channel")
    @classmethod
    def normalize_channel(cls, value: str) -> str:
        return value.casefold()

    @model_validator(mode="after")
    def ordered_sequences(self) -> ProcessingWatermarkInput:
        if (
            self.durable_sequence is not None
            and self.indexed_sequence is not None
            and self.indexed_sequence > self.durable_sequence
        ):
            raise ValueError("indexed_sequence cannot exceed durable_sequence")
        return self
