"""Evidence-backed relationship state; no scalar intimacy score."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any

from pydantic import Field, StringConstraints, field_validator, model_validator

from companion_agent.persona.models import PersonaModel, RelationshipStage
from companion_agent.semantics import (
    FamiliarityStage,
    RelationshipDistance,
    RelationshipIdentityType,
)

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=240)]
Description = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
]
Unit = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]


def now_utc() -> datetime:
    return datetime.now(UTC)


class RelationshipData(PersonaModel):
    @field_validator("*", mode="after")
    @classmethod
    def aware_timestamps(cls, value: Any) -> Any:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                raise ValueError("relationship timestamps must include a timezone")
            return value.astimezone(UTC)
        return value


class RelationshipKey(RelationshipData):
    user_id: Name
    companion_id: Name
    relationship_id: Name

    @model_validator(mode="after")
    def distinct_actors(self) -> RelationshipKey:
        if self.user_id == self.companion_id:
            raise ValueError("user and companion must be distinct actors")
        return self

    @property
    def values(self) -> tuple[str, str, str]:
        return self.user_id, self.companion_id, self.relationship_id


class RelationshipEvidenceKind(StrEnum):
    TURN = "turn"
    MEMORY = "memory"
    EVENT = "event"
    OPEN_LOOP = "open_loop"
    USER_CORRECTION = "user_correction"
    RELATIONSHIP_MEMORY = "relationship_memory"
    MILESTONE = "milestone"
    EXPERIENCE = "experience"
    CONFIGURATION = "configuration"
    EPISODE = "episode"


class RelationshipEvidenceRef(RelationshipData):
    kind: RelationshipEvidenceKind
    id: Name

    @property
    def key(self) -> str:
        return f"{self.kind.value}:{self.id}"

    @classmethod
    def parse(cls, value: str) -> RelationshipEvidenceRef:
        kind, separator, identifier = value.partition(":")
        if not separator:
            raise ValueError("evidence must be qualified as kind:id")
        return cls(kind=RelationshipEvidenceKind(kind), id=identifier)


class EvidenceStrength(StrEnum):
    DIRECT = "direct"
    REPEATED = "repeated"
    WEAK = "weak"


class RelationshipPatternCategory(StrEnum):
    COMMUNICATION = "communication"
    HUMOR = "humor"
    SUPPORT = "support"
    CONFLICT = "conflict"
    DECISION_MAKING = "decision_making"
    RITUAL = "ritual"
    TOPIC = "topic"
    BOUNDARY = "boundary"


class RelationshipPatternStatus(StrEnum):
    CANDIDATE = "candidate"
    ESTABLISHED = "established"
    RETIRED = "retired"


class RelationshipMilestoneStatus(StrEnum):
    ACTIVE = "active"
    RETRACTED = "retracted"


class RelationshipThreadStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    DORMANT = "dormant"
    CANCELLED = "cancelled"


class RelationshipFollowUpMode(StrEnum):
    WHEN_RELEVANT = "when_relevant"
    USER_LED = "user_led"
    NEVER = "never"


class RelationshipTone(StrEnum):
    NEUTRAL = "neutral"
    WARM = "warm"
    PLAYFUL = "playful"
    SLIGHTLY_TENSE = "slightly_tense"
    TENSE = "tense"
    REPAIRING = "repairing"


class RelationshipDirection(StrEnum):
    STABLE = "stable"
    INCREASING = "increasing"
    DECREASING = "decreasing"


class RelationshipBoundarySource(StrEnum):
    DIRECT_USER_STATEMENT = "direct_user_statement"
    REPEATED_FEEDBACK = "repeated_feedback"


class RelationshipIdentity(RelationshipData):
    type: RelationshipIdentityType = RelationshipIdentityType.UNDEFINED
    labels: list[Name] = Field(default_factory=list)
    description: Description | None = None
    confirmed_by_user: bool = False
    confirmed_at: datetime | None = None
    romantic: bool | None = None
    evidence_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def confirmed_identity(self) -> RelationshipIdentity:
        if self.type is RelationshipIdentityType.UNDEFINED:
            if self.romantic is True or "恋人" in self.labels:
                self.type = RelationshipIdentityType.ROMANTIC_PARTNER
            elif "好朋友" in self.labels:
                self.type = RelationshipIdentityType.CLOSE_FRIEND
            elif set(self.labels) & {"朋友", "普通朋友"}:
                self.type = RelationshipIdentityType.FRIEND
            elif self.labels:
                self.type = RelationshipIdentityType.CUSTOM
        if self.type is RelationshipIdentityType.ROMANTIC_PARTNER:
            if self.romantic is False:
                raise ValueError("romantic_partner conflicts with romantic=false")
            self.romantic = True
        if (
            self.type is not RelationshipIdentityType.UNDEFINED
            or self.labels
            or self.description
            or self.romantic is not None
        ) and not (self.confirmed_by_user and self.confirmed_at is not None and self.evidence_ids):
            raise ValueError(
                "relationship identity requires explicit user confirmation and evidence"
            )
        return self


class RelationshipStageState(RelationshipData):
    stage: RelationshipStage = RelationshipStage.NEW
    entered_at: datetime = Field(default_factory=now_utc)
    reasons: list[str] = Field(default_factory=lambda: ["尚无足够关系历史，保持初识距离"])
    evidence_ids: list[str] = Field(default_factory=list)


class RelationshipPattern(RelationshipData):
    id: Name
    description: Description
    category: RelationshipPatternCategory
    confidence: Unit
    first_observed_at: datetime
    last_observed_at: datetime
    evidence_ids: list[str] = Field(min_length=1)
    observation_count: int = Field(ge=1)
    status: RelationshipPatternStatus = RelationshipPatternStatus.CANDIDATE
    context_keys: list[Name] = Field(default_factory=list)

    @model_validator(mode="after")
    def ordered_observations(self) -> RelationshipPattern:
        if self.first_observed_at > self.last_observed_at:
            raise ValueError("pattern observation timestamps are reversed")
        if self.observation_count != len(set(self.evidence_ids)):
            raise ValueError("observation_count must count distinct evidence")
        return self


class RelationshipMilestone(RelationshipData):
    id: Name
    title: Description
    summary: Description
    occurred_at: datetime | None = None
    importance: Unit
    topic_keys: list[Name] = Field(default_factory=list)
    evidence_ids: list[str] = Field(min_length=1)
    status: RelationshipMilestoneStatus = RelationshipMilestoneStatus.ACTIVE


class RelationshipThread(RelationshipData):
    id: Name
    topic: Description
    summary: Description
    opened_at: datetime
    last_updated_at: datetime
    status: RelationshipThreadStatus = RelationshipThreadStatus.OPEN
    evidence_ids: list[str] = Field(min_length=1)
    follow_up_mode: RelationshipFollowUpMode = RelationshipFollowUpMode.WHEN_RELEVANT
    topic_keys: list[Name] = Field(default_factory=list)
    open_loop_id: str | None = None

    @model_validator(mode="after")
    def ordered_thread(self) -> RelationshipThread:
        if self.last_updated_at < self.opened_at:
            raise ValueError("thread update predates opening")
        return self


class RelationshipDynamics(RelationshipData):
    interaction_tone: RelationshipTone = RelationshipTone.NEUTRAL
    recent_closeness_change: RelationshipDirection = RelationshipDirection.STABLE
    recent_conflict_level: Unit = 0
    recent_user_initiative: RelationshipDirection = RelationshipDirection.STABLE
    active_topics: list[Name] = Field(default_factory=list)
    summary: Description | None = None
    updated_at: datetime = Field(default_factory=now_utc)
    evidence_ids: list[str] = Field(default_factory=list)


class RelationshipBoundary(RelationshipData):
    id: Name
    description: Description
    source: RelationshipBoundarySource
    confidence: Unit
    evidence_ids: list[str] = Field(min_length=1)
    created_at: datetime
    updated_at: datetime
    active: bool = True


class RelationshipModel(RelationshipKey):
    stage: RelationshipStage = RelationshipStage.NEW
    stage_state: RelationshipStageState = Field(default_factory=RelationshipStageState)
    identity: RelationshipIdentity = Field(default_factory=RelationshipIdentity)
    patterns: list[RelationshipPattern] = Field(default_factory=list)
    milestones: list[RelationshipMilestone] = Field(default_factory=list)
    unresolved_threads: list[RelationshipThread] = Field(default_factory=list)
    recent_dynamics: RelationshipDynamics = Field(default_factory=RelationshipDynamics)
    boundaries: list[RelationshipBoundary] = Field(default_factory=list)
    revision: int = Field(default=0, ge=0)
    updated_at: datetime = Field(default_factory=now_utc)
    started_at: datetime = Field(default_factory=now_utc)
    started_at_evidence_ids: list[str] = Field(default_factory=list)
    last_interaction_at: datetime | None = None
    # Evidence -> observed time, not a scalar relationship score.
    interactions: dict[str, datetime] = Field(default_factory=dict)
    shared_experiences: dict[str, datetime] = Field(default_factory=dict)
    distance_ceiling: RelationshipStage | None = None
    distance_evidence_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def consistent_state(self) -> RelationshipModel:
        if self.stage != self.stage_state.stage:
            raise ValueError("stage and stage_state must agree")
        for values in (self.patterns, self.milestones, self.unresolved_threads, self.boundaries):
            if len({item.id for item in values}) != len(values):
                raise ValueError("duplicate relationship item id")
        if any(at.tzinfo is None for at in self.interactions.values()):
            raise ValueError("interaction timestamps must include a timezone")
        return self

    @property
    def key(self) -> RelationshipKey:
        return RelationshipKey(
            user_id=self.user_id,
            companion_id=self.companion_id,
            relationship_id=self.relationship_id,
        )

    @property
    def familiarity_stage(self) -> FamiliarityStage:
        return self.stage


class RelationshipUpdateKind(StrEnum):
    IDENTITY = "identity"
    PATTERN = "pattern"
    MILESTONE = "milestone"
    THREAD = "thread"
    BOUNDARY = "boundary"
    DYNAMICS = "dynamics"
    TEMPORAL_CORRECTION = "temporal_correction"
    DISTANCE = "distance"
    INTERACTION = "interaction"
    EXPERIENCE = "experience"


class RelationshipAction(StrEnum):
    ADD = "add"
    UPDATE = "update"
    MERGE = "merge"
    RESOLVE = "resolve"
    NO_OP = "no_op"


class RelationshipChangeType(StrEnum):
    IDENTITY_UPDATED = "identity_updated"
    PATTERN_ADDED = "pattern_added"
    PATTERN_UPDATED = "pattern_updated"
    MILESTONE_ADDED = "milestone_added"
    MILESTONE_UPDATED = "milestone_updated"
    THREAD_OPENED = "thread_opened"
    THREAD_UPDATED = "thread_updated"
    THREAD_RESOLVED = "thread_resolved"
    BOUNDARY_UPDATED = "boundary_updated"
    DYNAMICS_UPDATED = "dynamics_updated"
    STAGE_CHANGED = "stage_changed"
    TEMPORAL_CORRECTED = "temporal_corrected"
    DISTANCE_CHANGED = "distance_changed"
    INTERACTION_RECORDED = "interaction_recorded"
    EVIDENCE_INVALIDATED = "evidence_invalidated"
    ITEM_REMOVED = "item_removed"
    EXPERIENCE_LINKED = "experience_linked"


class RelationshipUpdateCandidate(RelationshipData):
    candidate_id: Name
    kind: RelationshipUpdateKind
    description: Description
    confidence: Unit
    evidence_ids: list[str] = Field(min_length=1)
    created_at: datetime = Field(default_factory=now_utc)
    strength: EvidenceStrength = EvidenceStrength.WEAK
    proposed_change: dict[str, Any]

    @field_validator("evidence_ids")
    @classmethod
    def qualified_evidence(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(RelationshipEvidenceRef.parse(value).key for value in values))


class RelationshipRevision(RelationshipData):
    revision: int = Field(ge=1)
    created_at: datetime
    change_type: RelationshipChangeType
    summary: str
    evidence_ids: list[str]
    before: dict[str, Any] | None
    after: dict[str, Any] | None


class RelationshipDecision(RelationshipData):
    candidate_id: str
    action: RelationshipAction
    revision: int
    reason: str


class RelationshipConfig(RelationshipData):
    # Conservative prototype policy; configurable, not empirical intimacy thresholds.
    pattern_observations: int = Field(default=3, ge=2)
    pattern_span_days: int = Field(default=1, ge=0)
    milestone_min_importance: Unit = 0.75
    familiar_days: int = Field(default=7, ge=1)
    familiar_active_days: int = Field(default=3, ge=2)
    familiar_patterns: int = Field(default=1, ge=1)
    familiar_milestones: int = Field(default=2, ge=1)
    familiar_experiences: int = Field(default=2, ge=1)
    established_experiences: int = Field(default=5, ge=1)
    close_days: int = Field(default=60, ge=1)
    close_active_days: int = Field(default=12, ge=2)
    close_patterns: int = Field(default=2, ge=1)
    close_milestones: int = Field(default=3, ge=1)
    continuity_window_days: int = Field(default=30, ge=1)
    close_recent_active_days: int = Field(default=3, ge=2)
    inactivity_days: int = Field(default=45, ge=1)
    dynamics_days: int = Field(default=7, ge=1)
    conflict_downgrade_level: Unit = 0.8
    max_relationship_tokens: int = Field(default=700, ge=1)


class CompiledRelationshipContext(RelationshipKey):
    stage: RelationshipStage
    revision: int
    identity: RelationshipIdentity = Field(default_factory=RelationshipIdentity)
    familiarity_stage: FamiliarityStage = FamiliarityStage.NEW
    relationship_distance: RelationshipDistance = RelationshipDistance.OPEN
    identity_summary: str | None = None
    relevant_patterns: list[str] = Field(default_factory=list)
    relevant_milestones: list[str] = Field(default_factory=list)
    unresolved_threads: list[str] = Field(default_factory=list)
    relevant_thread_updates: list[str] = Field(default_factory=list)
    active_boundaries: list[str] = Field(default_factory=list)
    recent_dynamic_summary: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    text: str
    estimated_tokens: int = Field(ge=0)
    omitted_items: list[str] = Field(default_factory=list)
