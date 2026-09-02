from __future__ import annotations

from datetime import UTC, datetime

from pydantic import Field, field_validator, model_validator

from companion_memoryos.schemas.core import (
    STATE_ANSWER_SEMANTICS,
    AnswerSemantics,
    MemoryScope,
    RealityLayer,
    ResolutionStatus,
    StrictModel,
)
from companion_memoryos.schemas.memory import MemoryRecord


class StateQuery(StrictModel):
    user_id: str = Field(min_length=1, max_length=128)
    scope: MemoryScope = Field(default_factory=MemoryScope)
    predicate: str = Field(min_length=1, max_length=240)
    subject_actor_id: str | None = Field(default=None, min_length=1, max_length=240)
    valid_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    known_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    semantics: AnswerSemantics = AnswerSemantics.STATE_AT_VALID_TIME
    reality_layer: RealityLayer = RealityLayer.REAL_WORLD

    @field_validator("subject_actor_id")
    @classmethod
    def validate_subject(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("subject_actor_id cannot be blank")
        return value.strip() if value is not None else None

    @field_validator("predicate")
    @classmethod
    def normalize_predicate(cls, value: str) -> str:
        return value.casefold()

    @field_validator("valid_at", "known_at")
    @classmethod
    def require_aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("state query timestamps must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def require_state_semantics(self) -> StateQuery:
        if self.semantics not in STATE_ANSWER_SEMANTICS:
            raise ValueError("StateQuery requires state answer semantics")
        return self


class StateQueryResult(StrictModel):
    query: StateQuery
    resolution_status: ResolutionStatus
    memories: list[MemoryRecord] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
