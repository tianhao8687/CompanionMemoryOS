from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import Field, field_validator, model_validator

from companion_memoryos.constants import UNIT_INTERVAL_MAX, UNIT_INTERVAL_MIN
from companion_memoryos.schemas.core import (
    DiscourseSignal,
    EpistemicKind,
    MemoryKind,
    MemoryScope,
    OpenLoopKind,
    RealityLayer,
    SpeechAct,
    StrictModel,
)
from companion_memoryos.schemas.entity import EntityProposal, EntityResolution
from companion_memoryos.schemas.episode import EpisodeHint
from companion_memoryos.schemas.experience import DiscourseInterpretation


class SpeechSpanProposal(StrictModel):
    start_offset: int = Field(ge=0)
    end_offset: int = Field(gt=0)
    quote_depth: int = Field(default=0, ge=0)
    attributed_speaker_id: str | None = None
    target_actor_id: str | None = None
    reality_layer: RealityLayer = RealityLayer.REAL_WORLD
    speech_act: SpeechAct = SpeechAct.OTHER
    confidence: float = Field(default=UNIT_INTERVAL_MIN, ge=UNIT_INTERVAL_MIN, le=UNIT_INTERVAL_MAX)

    @model_validator(mode="after")
    def ordered_offsets(self) -> SpeechSpanProposal:
        if self.end_offset <= self.start_offset:
            raise ValueError("speech span end must follow start")
        return self


class MemoryCandidate(StrictModel):
    """An untrusted proposal: identity, consent and activation are not model fields."""

    kind: MemoryKind
    title: str = Field(min_length=1, max_length=240)
    content: str = Field(min_length=1, max_length=20_000)
    subject_actor_id: str | None = Field(default=None, min_length=1, max_length=240)
    predicate: str | None = Field(default=None, min_length=1, max_length=240)
    epistemic_kind: EpistemicKind = EpistemicKind.OBSERVATION
    reality_layer: RealityLayer = RealityLayer.REAL_WORLD
    evidence_span_indices: list[int] = Field(default_factory=list, max_length=128)
    confidence: float = Field(default=UNIT_INTERVAL_MIN, ge=UNIT_INTERVAL_MIN, le=UNIT_INTERVAL_MAX)
    valid_time_start: datetime | None = None
    valid_time_end: datetime | None = None
    entity_refs: list[str] = Field(default_factory=list, max_length=32)

    @field_validator("evidence_span_indices")
    @classmethod
    def nonnegative_indices(cls, values: list[int]) -> list[int]:
        if any(value < 0 for value in values):
            raise ValueError("span indices cannot be negative")
        return list(dict.fromkeys(values))

    @field_validator("valid_time_start", "valid_time_end")
    @classmethod
    def aware_time(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("state timestamps must include a timezone")
        return value.astimezone(UTC) if value is not None else None

    @model_validator(mode="after")
    def state_requires_subject(self) -> MemoryCandidate:
        if self.predicate is not None and self.subject_actor_id is None:
            raise ValueError("state proposals require an explicit subject_actor_id")
        return self


class StateClaim(MemoryCandidate):
    kind: MemoryKind = MemoryKind.PREFERENCE
    predicate: str = Field(min_length=1, max_length=240)
    subject_actor_id: str = Field(min_length=1, max_length=240)


class OpenLoopCandidate(StrictModel):
    kind: OpenLoopKind
    summary: str = Field(min_length=1, max_length=2_000)
    topic_keys: list[str] = Field(default_factory=list, max_length=64)


class TurnInterpretation(StrictModel):
    speech_spans: list[SpeechSpanProposal] = Field(default_factory=list, max_length=128)
    topics: list[str] = Field(default_factory=list, max_length=64)
    state_claims: list[StateClaim] = Field(default_factory=list, max_length=64)
    memory_candidates: list[MemoryCandidate] = Field(default_factory=list, max_length=64)
    open_loop_candidates: list[OpenLoopCandidate] = Field(default_factory=list, max_length=64)
    discourse_signals: list[DiscourseSignal] = Field(default_factory=list, max_length=64)
    episode_hint: EpisodeHint | None = None
    entities: list[EntityProposal] = Field(default_factory=list, max_length=32)

    @field_validator("entities")
    @classmethod
    def unique_entity_refs(cls, values: list[EntityProposal]) -> list[EntityProposal]:
        if len({value.ref for value in values}) != len(values):
            raise ValueError("entity refs must be unique within a turn")
        return values

    @field_validator("topics")
    @classmethod
    def normalize_topics(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip().casefold() for value in values if value.strip()))


class TurnInterpretationRequest(StrictModel):
    user_id: str = Field(min_length=1, max_length=128)
    scope: MemoryScope
    model_output: TurnInterpretation
    model_fingerprint: str = Field(min_length=1, max_length=500)
    idempotency_key: str = Field(min_length=1, max_length=240)
    apply_low_risk_actions: bool = True
    episode_max_gap_seconds: float | None = Field(default=None, gt=0)
    processing_metadata: dict[str, Any] = Field(default_factory=dict)


class TurnInterpretationRecord(StrictModel):
    id: str
    user_id: str
    scope: MemoryScope
    turn_id: str
    model_fingerprint: str
    episode_max_gap_seconds: float | None = Field(default=None, gt=0)
    idempotency_key: str
    model_output: TurnInterpretation
    memory_ids: list[str] = Field(default_factory=list)
    open_loop_ids: list[str] = Field(default_factory=list)
    episode_id: str | None = None
    discourse: DiscourseInterpretation | None = None
    reasons: list[str] = Field(default_factory=list)
    created_at: datetime
    entity_resolutions: list[EntityResolution] = Field(default_factory=list)
    processing_metadata: dict[str, Any] = Field(default_factory=dict)
