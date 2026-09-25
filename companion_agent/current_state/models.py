"""Short-lived user overlays; never relationship identity or permanent preferences."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from companion_agent.relationship.models import Name, RelationshipData, RelationshipKey
from companion_memoryos.schemas import ResponseGoal


class StateKind(StrEnum):
    CONDITION = "condition"
    COMMUNICATION = "communication"
    STYLE = "style"


class StateStatus(StrEnum):
    ACTIVE = "active"
    ENDED = "ended"
    RETRACTED = "retracted"
    SUPPRESSED = "suppressed"
    EXPIRED = "expired"
    INVALIDATED = "invalidated"


class StateObservation(RelationshipData):
    kind: StateKind
    slot: Name
    value: Name
    topic: str | None = None
    status: StateStatus = StateStatus.ACTIVE
    applies_today: bool = False
    reason: str = "direct_current_statement"


class CurrentStateRecord(RelationshipKey):
    state_id: str
    kind: StateKind
    slot: str
    value: str
    topic: str | None
    conversation_id: str | None
    actor_id: str
    source_turn_id: str
    source_sequence: int
    observed_at: datetime
    expires_at: datetime
    status: StateStatus
    reason: str
    revision: int = Field(ge=1)
    open_loop_id: str | None = None

    @model_validator(mode="after")
    def consistent_overlay(self) -> CurrentStateRecord:
        allowed = {
            StateKind.CONDITION: {"fatigue", "sleep_loss", "sadness", "pressure"},
            StateKind.COMMUNICATION: {"listen", "problem_solve", "none"},
            StateKind.STYLE: {"reduce", "normal", "hold"},
        }
        if (
            self.actor_id != self.user_id
            or not self.slot.startswith(self.kind.value + ":")
            or self.value not in allowed[self.kind]
            or self.expires_at <= self.observed_at
        ):
            raise ValueError("invalid current state actor, value, slot or lifetime")
        if (
            self.kind is StateKind.COMMUNICATION
            and self.value == "none"
            and self.status is StateStatus.ACTIVE
        ):
            raise ValueError("empty communication request cannot be active")
        return self


class CurrentStateConfig(RelationshipData):
    enabled: bool = True
    communication_hours: float = Field(default=8, gt=0, le=168)
    fatigue_hours: float = Field(default=12, gt=0, le=72)
    emotion_hours: float = Field(default=6, gt=0, le=48)
    pressure_hours: float = Field(default=72, gt=0, le=336)
    max_context_tokens: int = Field(default=450, ge=100)


class CurrentStateAnalysis(RelationshipData):
    observations: list[StateObservation] = Field(default_factory=list)
    explicit_goal: ResponseGoal | None = None
    concrete_task: bool = False
    topic_switch: bool = False
    topics: list[str] = Field(default_factory=list)
    completed_topics: list[str] = Field(default_factory=list)
    stop_reference: bool = False
    conflict: bool = False
    repair: bool = False
    repair_requires_context: bool = False
    conflict_correction: bool = False
    reopened_topics: list[str] = Field(default_factory=list)
    reopen_unscoped: bool = False
    permanent_address_boundary: bool = False
    rejected_address_text: str | None = None
    celebrating: bool = False
    recalling_history: bool = False
    continuing: bool = False


class CompiledCurrentState(RelationshipKey):
    effective_goal: ResponseGoal
    text: str
    estimated_tokens: int
    state_ids: list[str] = Field(default_factory=list)
    source_turn_ids: list[str] = Field(default_factory=list)
    degraded: bool = False
    has_explicit_requests: bool = False
    omitted_states: dict[str, str] = Field(default_factory=dict)


class StatePreparation(RelationshipData):
    analysis: CurrentStateAnalysis
    records: list[CurrentStateRecord] = Field(default_factory=list)
    degraded: bool = False
    interaction_tone: str | None = None
    interaction_guidance: str | None = None
    current_turn_id: str | None = None
