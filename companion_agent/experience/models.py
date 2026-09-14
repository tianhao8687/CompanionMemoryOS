"""Private, sourced user/character/shared lived experiences above MemoryOS episodes."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from companion_agent.relationship.models import (
    Description,
    Name,
    RelationshipData,
    RelationshipKey,
    Unit,
    now_utc,
)
from companion_memoryos.schemas import MemoryReferenceMode, RealityLayer


class ExperienceType(StrEnum):
    USER = "user"
    CHARACTER = "character"
    SHARED = "shared"


class ExperienceStatus(StrEnum):
    CANDIDATE = "candidate"
    OPEN = "open"
    CLOSED = "closed"
    DORMANT = "dormant"
    SUPERSEDED = "superseded"


class ExperienceAction(StrEnum):
    CREATE = "create"
    MERGE = "merge"
    UPDATE = "update"
    CLOSE = "close"
    PROMOTE = "promote"
    NO_OP = "no_op"


class ExperienceEvidenceKind(StrEnum):
    TURN = "turn"
    EPISODE = "episode"
    MEMORY = "memory"
    OPEN_LOOP = "open_loop"


class ExperienceEvidenceRef(RelationshipData):
    kind: ExperienceEvidenceKind
    id: Name
    # Captured membership prevents detached/reassigned turns silently staying in a summary.
    episode_id: str | None = None

    @property
    def key(self) -> str:
        return f"{self.kind.value}:{self.id}"


class ExperienceFact(RelationshipData):
    actor_id: Name
    text: str = Field(min_length=1, max_length=50_000)
    occurred_at: datetime
    evidence_ref: ExperienceEvidenceRef
    # Assistant text is a conversational action, never an independent user-life fact.
    is_assistant_action: bool = False


class ExperienceRecord(RelationshipKey):
    experience_id: Name
    type: ExperienceType
    source: str = "lived"
    title: Description
    summary: str
    participants: list[Name] = Field(min_length=1)
    started_at: datetime
    ended_at: datetime | None = None
    last_event_at: datetime
    topic_keys: list[Name]
    evidence_refs: list[ExperienceEvidenceRef]
    facts: list[ExperienceFact]
    importance: Unit
    emotional_significance: Unit
    relationship_significance: Unit
    explicit_user_importance: bool = False
    status: ExperienceStatus = ExperienceStatus.CANDIDATE
    anchor_id: Name
    revision: int = Field(default=0, ge=0)
    updated_at: datetime = Field(default_factory=now_utc)
    reality_layer: RealityLayer = RealityLayer.REAL_WORLD
    superseded_by: str | None = None

    @model_validator(mode="after")
    def consistent_experience(self) -> ExperienceRecord:
        expected = (
            {self.user_id}
            if self.type is ExperienceType.USER
            else (
                {self.companion_id}
                if self.type is ExperienceType.CHARACTER
                else {self.user_id, self.companion_id}
            )
        )
        if set(self.participants) != expected or self.source != "lived":
            raise ValueError("lived experience participants/source do not match its type")
        if self.ended_at is not None and self.ended_at < self.started_at:
            raise ValueError("experience end precedes start")
        if self.last_event_at < self.started_at:
            raise ValueError("experience last event precedes start")
        if self.reality_layer is not RealityLayer.REAL_WORLD:
            raise ValueError("v0.3 lived experiences require real conversation evidence")
        return self

    @property
    def key(self) -> RelationshipKey:
        return RelationshipKey(
            user_id=self.user_id,
            companion_id=self.companion_id,
            relationship_id=self.relationship_id,
        )


class ExperienceCandidate(RelationshipKey):
    candidate_id: Name
    type: ExperienceType
    title: Description
    topic_keys: list[Name]
    evidence_refs: list[ExperienceEvidenceRef] = Field(min_length=1)
    anchor_id: Name
    target_id: str | None = None
    expected_revision: int | None = Field(default=None, ge=0)
    requested_action: ExperienceAction = ExperienceAction.CREATE
    created_at: datetime = Field(default_factory=now_utc)

    @property
    def key(self) -> RelationshipKey:
        return RelationshipKey(
            user_id=self.user_id,
            companion_id=self.companion_id,
            relationship_id=self.relationship_id,
        )


class ExperienceDecision(RelationshipData):
    candidate_id: str
    action: ExperienceAction
    experience_id: str | None
    revision: int
    reason: str


class ExperienceConfig(RelationshipData):
    shared_user_turns: int = Field(default=2, ge=2)
    merge_gap_days: int = Field(default=30, ge=1)
    dormant_after_days: int = Field(default=30, ge=1)
    max_context_tokens: int = Field(default=800, ge=1)
    recall_limit: int = Field(default=3, ge=1)
    milestone_user_turns: int = Field(default=3, ge=2)
    milestone_active_days: int = Field(default=2, ge=1)
    milestone_importance: Unit = 0.75
    milestone_relationship_significance: Unit = 0.65


class ExperienceRecallItem(RelationshipData):
    experience: ExperienceRecord
    score: float
    use_mode: MemoryReferenceMode


class CompiledExperienceContext(RelationshipKey):
    text: str
    estimated_tokens: int = Field(ge=0)
    experience_ids: list[str] = Field(default_factory=list)
    omitted_count: int = Field(default=0, ge=0)
    covered_evidence_ids: list[str] = Field(default_factory=list)
