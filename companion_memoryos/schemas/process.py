from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from companion_memoryos.schemas.context import CompanionContext
from companion_memoryos.schemas.core import (
    ConsentState,
    ConversationRole,
    EntityRef,
    MemoryScope,
    RealityLayer,
    Sensitivity,
    StrictModel,
)
from companion_memoryos.schemas.experience import DiscourseInterpretation
from companion_memoryos.schemas.interpretation import TurnInterpretation, TurnInterpretationRecord
from companion_memoryos.schemas.memory import RecallRequest
from companion_memoryos.schemas.turn import ConversationTurnStorageResult, SpeechSpan


class ProcessTurnRequest(StrictModel):
    user_id: str = Field(min_length=1, max_length=128)
    scope: MemoryScope
    content: str = Field(min_length=1, max_length=50_000)
    idempotency_key: str = Field(min_length=1, max_length=500)
    actor_id: str | None = Field(default=None, min_length=1, max_length=240)
    role: ConversationRole = ConversationRole.USER
    occurred_at: datetime | None = None
    consent: ConsentState = ConsentState.UNKNOWN
    sensitivity: Sensitivity = Sensitivity.NORMAL
    model_consent: ConsentState = ConsentState.UNKNOWN
    allow_sensitive_model_input: bool = False
    calendar_timezone: str = "UTC"
    reality_layer: RealityLayer = RealityLayer.REAL_WORLD
    reply_to_turn_id: str | None = None
    speech_spans: list[SpeechSpan] = Field(default_factory=list, max_length=128)
    apply_low_risk_actions: bool = True
    enable_recall: bool = True
    recall_request: RecallRequest | None = None
    episode_max_gap_seconds: float | None = Field(default=None, gt=0)

    @field_validator("user_id", "content", "idempotency_key", "actor_id")
    @classmethod
    def nonblank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("process turn fields cannot be blank")
        return value.strip() if value is not None else None

    @field_validator("occurred_at")
    @classmethod
    def aware_time(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("occurred_at must include a timezone")
        return value.astimezone(UTC) if value is not None else None

    @field_validator("calendar_timezone")
    @classmethod
    def calendar_zone(cls, value: str) -> str:
        return RecallRequest.validate_calendar_timezone(value)

    @model_validator(mode="after")
    def request_scope(self) -> ProcessTurnRequest:
        if self.scope.conversation_id is None or self.scope.relationship_id is None:
            raise ValueError("process_turn requires conversation and relationship scopes")
        if self.actor_id is None:
            if self.role is ConversationRole.USER:
                self.actor_id = self.user_id
            elif self.role is ConversationRole.ASSISTANT and self.scope.companion_id is not None:
                self.actor_id = self.scope.companion_id
            else:
                raise ValueError("non-user turns require an actor_id")
        if self.recall_request is not None and (
            self.recall_request.user_id != self.user_id or self.recall_request.scope != self.scope
        ):
            raise ValueError("recall request must use the same user and scope")
        if any(span.end_offset > len(self.content) for span in self.speech_spans):
            raise ValueError("speech span exceeds current content")
        if self.reality_layer is not RealityLayer.REAL_WORLD and any(
            span.reality_layer is RealityLayer.REAL_WORLD for span in self.speech_spans
        ):
            raise ValueError("non-real turns cannot contain real-world speech spans")
        return self


class InterpreterTurn(StrictModel):
    id: str
    actor_id: str
    role: ConversationRole
    content: str
    occurred_at: datetime
    speech_spans: list[SpeechSpan] = Field(default_factory=list)


class InterpreterEpisode(StrictModel):
    id: str
    title: str
    topic_keys: list[str]
    participant_actor_ids: list[str]
    reality_layer: RealityLayer
    continuity_turn_id: str


class InterpreterContext(StrictModel):
    user_id: str
    companion_id: str | None
    current_turn: InterpreterTurn
    calendar_timezone: str
    reality_layer: RealityLayer
    recent_turns: list[InterpreterTurn] = Field(default_factory=list)
    known_entities: list[EntityRef] = Field(default_factory=list)
    episodes: list[InterpreterEpisode] = Field(default_factory=list)


class InterpreterUsage(StrictModel):
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


class InterpreterOutput(StrictModel):
    interpretation: TurnInterpretation
    model_fingerprint: str = Field(min_length=1, max_length=500)
    usage: InterpreterUsage | None = None


class ProcessTurnResult(StrictModel):
    storage: ConversationTurnStorageResult
    interpretation_status: Literal[
        "completed",
        "cached",
        "rules_only",
        "not_configured",
        "not_authorized",
        "not_stored",
        "budget_exceeded",
        "failed",
        "source_invalidated",
    ]
    interpretation: TurnInterpretationRecord | None = None
    discourse: DiscourseInterpretation | None = None
    response_context: CompanionContext | None = None
    response_stale: bool = False
    model_calls: int = Field(default=0, ge=0, le=1)
    estimated_input_tokens: int | None = Field(default=None, ge=0)
    model_usage: InterpreterUsage | None = None
    reasons: list[str] = Field(default_factory=list)
