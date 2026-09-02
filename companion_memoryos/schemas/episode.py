from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from companion_memoryos.constants import UNIT_INTERVAL_MAX, UNIT_INTERVAL_MIN
from companion_memoryos.schemas.core import EpisodeStatus, MemoryScope, RealityLayer, StrictModel


class EpisodeInput(StrictModel):
    user_id: str = Field(min_length=1, max_length=128)
    scope: MemoryScope
    title: str = Field(min_length=1, max_length=240)
    summary: str = Field(default="", max_length=2_000)
    topic_keys: list[str] = Field(default_factory=list, max_length=64)
    participant_actor_ids: list[str] = Field(default_factory=list, max_length=64)
    reality_layer: RealityLayer = RealityLayer.REAL_WORLD
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("topic_keys")
    @classmethod
    def normalize_topics(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip().casefold() for value in values if value.strip()))

    @field_validator("participant_actor_ids")
    @classmethod
    def normalize_participants(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip() for value in values if value.strip()))

    @field_validator("started_at")
    @classmethod
    def aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("episode timestamps must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def relationship_required(self) -> EpisodeInput:
        if self.scope.relationship_id is None:
            raise ValueError("episodes require a relationship scope")
        return self


class EpisodeRecord(EpisodeInput):
    id: str
    last_event_at: datetime
    status: EpisodeStatus = EpisodeStatus.OPEN
    merged_into_id: str | None = None
    revision: int = Field(default=0, ge=0)
    created_at: datetime
    updated_at: datetime


class EpisodeAttachRequest(StrictModel):
    user_id: str = Field(min_length=1, max_length=128)
    scope: MemoryScope
    turn_id: str = Field(min_length=1, max_length=240)
    expected_episode_id: str | None = None
    expected_revision: int | None = Field(default=None, ge=0)


class EpisodeMergeRequest(StrictModel):
    user_id: str = Field(min_length=1, max_length=128)
    scope: MemoryScope
    source_episode_id: str = Field(min_length=1, max_length=240)
    expected_revision: int | None = Field(default=None, ge=0)


class EpisodeDetachRequest(StrictModel):
    user_id: str = Field(min_length=1, max_length=128)
    scope: MemoryScope
    turn_id: str = Field(min_length=1, max_length=240)
    expected_revision: int | None = Field(default=None, ge=0)


class EpisodeSplitRequest(StrictModel):
    user_id: str = Field(min_length=1, max_length=128)
    scope: MemoryScope
    turn_ids: list[str] = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=240)
    expected_revision: int | None = Field(default=None, ge=0)


class EpisodeHint(StrictModel):
    action: Literal["new", "attach"]
    episode_id: str | None = None
    title: str | None = Field(default=None, min_length=1, max_length=240)
    continuity_turn_id: str | None = None
    participant_actor_ids: list[str] = Field(default_factory=list, max_length=64)
    reality_layer: RealityLayer = RealityLayer.REAL_WORLD
    confidence: float | None = Field(default=None, ge=UNIT_INTERVAL_MIN, le=UNIT_INTERVAL_MAX)

    @model_validator(mode="after")
    def complete_action(self) -> EpisodeHint:
        if self.action == "new" and (self.title is None or self.episode_id is not None):
            raise ValueError("new episode hints require a title, not an existing id")
        if self.action == "attach" and (self.episode_id is None or self.continuity_turn_id is None):
            raise ValueError("attach hints require episode_id and continuity_turn_id")
        return self
