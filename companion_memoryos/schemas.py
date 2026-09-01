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
    THIRD_PARTY = "third_party"
    SYSTEM = "system"


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


class TemporalAnchorStatus(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    FORGOTTEN = "forgotten"


class EpistemicKind(StrEnum):
    DIRECT_SELF_REPORT = "direct_self_report"
    OBSERVATION = "observation"
    INTERPRETATION_HYPOTHESIS = "interpretation_hypothesis"
    RELATIONSHIP_CONTRACT = "relationship_contract"
    WORLD_SETTING = "world_setting"
    ASSISTANT_INTERNAL = "assistant_internal"


class ResolutionStatus(StrEnum):
    RESOLVED = "resolved"
    CONTESTED = "contested"
    UNKNOWN = "unknown"


class RealityLayer(StrEnum):
    REAL_WORLD = "real_world"
    ROLEPLAY = "roleplay"
    QUOTE = "quote"
    FICTION = "fiction"


class EvidenceActor(StrEnum):
    AUTHENTICATED_USER = "authenticated_user"
    ASSISTANT = "assistant"
    THIRD_PARTY = "third_party"
    MACHINE = "machine"


class ElicitationKind(StrEnum):
    SPONTANEOUS = "spontaneous"
    OPEN_QUESTION = "open_question"
    NEUTRAL_CONFIRMATION = "neutral_confirmation"
    LEADING_QUESTION = "leading_question"
    FORCED_CHOICE = "forced_choice"
    ASSISTANT_ASSERTION_CONFIRMATION = "assistant_assertion_confirmation"


class AnswerSemantics(StrEnum):
    EVENT_RECALL = "event_recall"
    UTTERANCE_HISTORY = "utterance_history"
    STATE_AT_VALID_TIME = "state_at_valid_time"
    LATEST_SELF_REPORT_ABOUT_TIME = "latest_self_report_about_time"
    CONTRACT_AT_TIME = "contract_at_time"
    BELIEF_AS_KNOWN_AT = "belief_as_known_at"
    CHANGE_TRAJECTORY = "change_trajectory"


class AnswerCardinality(StrEnum):
    AUTO = "auto"
    SINGLE = "single"
    MULTI = "multi"
    OPEN = "open"


STATE_ANSWER_SEMANTICS = frozenset(
    {
        AnswerSemantics.STATE_AT_VALID_TIME,
        AnswerSemantics.LATEST_SELF_REPORT_ABOUT_TIME,
        AnswerSemantics.CONTRACT_AT_TIME,
        AnswerSemantics.BELIEF_AS_KNOWN_AT,
        AnswerSemantics.CHANGE_TRAJECTORY,
    }
)


class RetrievalAction(StrEnum):
    ANSWER_SINGLE = "answer_single"
    ANSWER_MULTI = "answer_multi"
    CLARIFY = "clarify"
    ABSTAIN = "abstain"


class TurnModality(StrEnum):
    TEXT = "text"
    AUDIO = "audio"
    IMAGE = "image"
    VIDEO = "video"
    LOCATION = "location"


class TurnDeletionState(StrEnum):
    ACTIVE = "active"
    FORGOTTEN = "forgotten"


class SpeechAct(StrEnum):
    ASSERTION = "assertion"
    SELF_REPORT = "self_report"
    QUOTE = "quote"
    QUESTION = "question"
    COMMAND = "command"
    CORRECTION = "correction"
    WITHDRAWAL = "withdrawal"
    OTHER = "other"


class ChannelStatus(StrEnum):
    READY = "ready"
    LAGGING = "lagging"
    DISABLED = "disabled"
    UNKNOWN = "unknown"


class PolicyEffect(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    FREEZE = "freeze"


class PolicyConstraintStatus(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    REVOKED = "revoked"


class OpenLoopKind(StrEnum):
    EVENT_OUTCOME = "event_outcome"
    SHARE_LATER = "share_later"
    DECISION = "decision"
    USER_COMMITMENT = "user_commitment"
    ASSISTANT_COMMITMENT = "assistant_commitment"
    ONGOING_CONCERN = "ongoing_concern"


class FollowUpMode(StrEnum):
    WHEN_RELEVANT = "when_relevant"
    AT_OR_AFTER_TIME = "at_or_after_time"
    USER_LED = "user_led"
    NEVER = "never"


class OpenLoopStatus(StrEnum):
    OPEN = "open"
    SNOOZED = "snoozed"
    WAITING_FOR_REPLY = "waiting_for_reply"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"


class OpenLoopTransition(StrEnum):
    MARK_FOLLOWED_UP = "mark_followed_up"
    SNOOZE = "snooze"
    RESOLVE = "resolve"
    CANCEL = "cancel"
    REOPEN = "reopen"


class FollowUpAction(StrEnum):
    ASK_NOW = "ask_now"
    HOLD = "hold"
    NONE = "none"


class MemoryReferenceMode(StrEnum):
    SILENT_INFLUENCE = "silent_influence"
    SOFT_REFERENCE = "soft_reference"
    EXPLICIT_RECALL = "explicit_recall"
    CLARIFY = "clarify"
    SUPPRESS = "suppress"


class ReferenceFeedbackKind(StrEnum):
    WRONG_MATCH = "wrong_match"
    BAD_TIMING = "bad_timing"
    TOO_REPETITIVE = "too_repetitive"
    DO_NOT_REFERENCE = "do_not_reference"
    WELCOME_REFERENCE = "welcome_reference"


class ExperienceEvidenceKind(StrEnum):
    MEMORY = "memory"
    EVENT = "event"
    TURN = "turn"
    OPEN_LOOP = "open_loop"


class ResponseGoal(StrEnum):
    DIRECT_ANSWER = "direct_answer"
    LISTEN = "listen"
    COMFORT = "comfort"
    CELEBRATE = "celebrate"
    REFLECT = "reflect"
    PROBLEM_SOLVE = "problem_solve"
    CHECK_IN = "check_in"


class ResponseDeliveryMode(StrEnum):
    SINGLE_MESSAGE = "single_message"
    SEMANTIC_BEATS = "semantic_beats"


class ResponsePlanStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ResponsePlanResolutionStatus(StrEnum):
    PENDING = "pending"
    RESOLVED = "resolved"


class ResponseBeatKind(StrEnum):
    ACKNOWLEDGEMENT = "acknowledgement"
    DIRECT_RESPONSE = "direct_response"
    COMPOSED_RESPONSE = "composed_response"
    MEMORY_REFERENCE = "memory_reference"
    MEMORY_GAP = "memory_gap"
    CLARIFICATION = "clarification"
    FOLLOW_UP = "follow_up"
    AFTERTHOUGHT = "afterthought"


class ResponseBeatSource(StrEnum):
    CURRENT_TURN = "current_turn"
    RETRIEVAL = "retrieval"
    OPEN_LOOP = "open_loop"
    PLANNER = "planner"


class ResponseBeatStatus(StrEnum):
    READY = "ready"
    PENDING = "pending"
    SENT = "sent"
    CANCELLED = "cancelled"


class BeatReleaseCondition(StrEnum):
    IMMEDIATE = "immediate"
    EVIDENCE_READY = "evidence_ready"
    PREVIOUS_BEAT_SENT = "previous_beat_sent"
    HOST_SIGNAL = "host_signal"


class RepairKind(StrEnum):
    CORRECT_MEMORY = "correct_memory"
    WRONG_REFERENCE = "wrong_reference"
    STOP_REFERENCING = "stop_referencing"
    RESOLVE_OPEN_LOOP = "resolve_open_loop"
    CANCEL_OPEN_LOOP = "cancel_open_loop"


class DiscourseSignal(StrEnum):
    LISTEN_ONLY = "listen_only"
    ADVICE_REQUESTED = "advice_requested"
    MEMORY_QUESTION = "memory_question"
    WRONG_REFERENCE = "wrong_reference"
    STOP_REFERENCING = "stop_referencing"
    TOPIC_SWITCH = "topic_switch"
    OUTCOME_REPORTED = "outcome_reported"


class DiscourseInterpretationStatus(StrEnum):
    RECOGNIZED = "recognized"
    CONFLICTING = "conflicting"
    UNKNOWN = "unknown"


class AutomaticActionStatus(StrEnum):
    APPLIED = "applied"
    NEEDS_TARGET = "needs_target"
    NOT_REQUESTED = "not_requested"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class MemoryScope(StrictModel):
    companion_id: str | None = Field(default=None, max_length=240)
    relationship_id: str | None = Field(default=None, max_length=240)
    conversation_id: str | None = Field(default=None, max_length=240)
    group_id: str | None = Field(default=None, max_length=240)

    @field_validator("companion_id", "relationship_id", "conversation_id", "group_id")
    @classmethod
    def reject_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("scope identifiers cannot be blank")
        return value.strip() if value is not None else None

    @property
    def is_global(self) -> bool:
        return not any(self.model_dump().values())


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
    scope: MemoryScope = Field(default_factory=MemoryScope)
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
    valid_time_start: datetime | None = None
    valid_time_end: datetime | None = None
    source_ref: str = Field(default="conversation", min_length=1, max_length=500)
    source_excerpt: str | None = Field(default=None, max_length=2_000)
    entities: list[EntityRef] = Field(default_factory=list, max_length=32)
    embedding: list[float] | None = Field(default=None, min_length=1, max_length=4_096)
    embedding_space: str | None = Field(default=None, min_length=1, max_length=240)
    epistemic_kind: EpistemicKind = EpistemicKind.OBSERVATION
    resolution_status: ResolutionStatus = ResolutionStatus.RESOLVED
    reality_layer: RealityLayer = RealityLayer.REAL_WORLD
    source_actor: EvidenceActor = EvidenceActor.AUTHENTICATED_USER
    quote_depth: int = Field(default=0, ge=0)
    elicitation_kind: ElicitationKind = ElicitationKind.SPONTANEOUS
    subject_actor_id: str | None = Field(default=None, max_length=240)
    predicate: str | None = Field(default=None, max_length=240)
    evidence_turn_ids: list[str] = Field(default_factory=list, max_length=64)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator(
        "user_id",
        "title",
        "content",
        "stable_key",
        "source_ref",
        "source_excerpt",
        "subject_actor_id",
        "predicate",
    )
    @classmethod
    def reject_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("value cannot be blank")
        return value.strip() if value is not None else None

    @field_validator("needs")
    @classmethod
    def normalize_needs(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip().casefold() for value in values if value.strip()))

    @field_validator("event_at", "valid_time_start", "valid_time_end")
    @classmethod
    def require_aware_event_time(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("memory timestamps must include a timezone")
        return value.astimezone(UTC)

    @field_validator("evidence_turn_ids")
    @classmethod
    def normalize_evidence_turn_ids(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip() for value in values if value.strip()))

    @field_validator("predicate")
    @classmethod
    def normalize_predicate(cls, value: str | None) -> str | None:
        return value.casefold() if value is not None else None

    @model_validator(mode="after")
    def valid_embedding(self) -> MemoryInput:
        _validate_embedding(self.embedding, self.embedding_space)
        if (
            self.valid_time_start is not None
            and self.valid_time_end is not None
            and self.valid_time_start >= self.valid_time_end
        ):
            raise ValueError("valid_time_start must be earlier than valid_time_end")
        return self


class MemoryCorrectionRequest(StrictModel):
    user_id: str = Field(min_length=1, max_length=128)
    content: str = Field(min_length=1, max_length=20_000)
    title: str | None = Field(default=None, max_length=240)
    consent: ConsentState = ConsentState.UNKNOWN
    event_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    valid_time_start: datetime | None = None
    valid_time_end: datetime | None = None
    source_ref: str = Field(default="conversation:correction", min_length=1, max_length=500)
    source_excerpt: str | None = Field(default=None, max_length=2_000)
    emotions: list[EmotionSignal] | None = Field(default=None, max_length=12)
    needs: list[str] | None = Field(default=None, max_length=20)
    entities: list[EntityRef] | None = Field(default=None, max_length=32)
    embedding: list[float] | None = Field(default=None, min_length=1, max_length=4_096)
    embedding_space: str | None = Field(default=None, min_length=1, max_length=240)
    evidence_turn_ids: list[str] = Field(default_factory=list, max_length=64)

    @field_validator("user_id", "content", "title", "source_ref", "source_excerpt")
    @classmethod
    def reject_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("value cannot be blank")
        return value.strip() if value is not None else None

    @field_validator("needs")
    @classmethod
    def normalize_needs(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        return list(dict.fromkeys(value.strip().casefold() for value in values if value.strip()))

    @field_validator("evidence_turn_ids")
    @classmethod
    def normalize_evidence_turn_ids(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip() for value in values if value.strip()))

    @field_validator("event_at", "valid_time_start", "valid_time_end")
    @classmethod
    def require_aware_event_time(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("correction timestamps must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def valid_embedding(self) -> MemoryCorrectionRequest:
        _validate_embedding(self.embedding, self.embedding_space)
        if (
            self.valid_time_start is not None
            and self.valid_time_end is not None
            and self.valid_time_start >= self.valid_time_end
        ):
            raise ValueError("valid_time_start must be earlier than valid_time_end")
        return self


class ConversationEventInput(StrictModel):
    user_id: str = Field(min_length=1, max_length=128)
    scope: MemoryScope = Field(default_factory=MemoryScope)
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
        if self.scope.conversation_id is not None and self.scope.conversation_id != self.session_id:
            raise ValueError("scope.conversation_id must match session_id")
        return self


class RecallRequest(StrictModel):
    user_id: str = Field(min_length=1, max_length=128)
    exclude_turn_ids: list[str] = Field(default_factory=list, max_length=128)
    scope: MemoryScope = Field(default_factory=MemoryScope)
    query: str = Field(default="", max_length=4_000)
    intent: RecallIntent = RecallIntent.GENERAL
    emotions: list[EmotionSignal] = Field(default_factory=list, max_length=12)
    needs: list[str] = Field(default_factory=list, max_length=20)
    entity_ids: list[str] = Field(default_factory=list, max_length=32)
    limit: int | None = Field(default=None, gt=0)
    event_limit: int | None = Field(default=None, ge=0)
    turn_limit: int | None = Field(default=None, ge=0)
    max_characters: int | None = Field(default=None, gt=0)
    max_tokens: int | None = Field(default=None, gt=0)
    event_after: datetime | None = None
    event_before: datetime | None = None
    query_embedding: list[float] | None = Field(default=None, min_length=1, max_length=4_096)
    embedding_space: str | None = Field(default=None, min_length=1, max_length=240)
    answer_semantics: AnswerSemantics = AnswerSemantics.EVENT_RECALL
    answer_cardinality: AnswerCardinality = AnswerCardinality.AUTO
    utterance_actor_id: str | None = Field(default=None, max_length=240)
    state_predicate: str | None = Field(default=None, max_length=240)
    state_reality_layer: RealityLayer = RealityLayer.REAL_WORLD
    valid_at: datetime | None = None
    known_at: datetime | None = None
    as_of: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("needs")
    @classmethod
    def normalize_needs(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip().casefold() for value in values if value.strip()))

    @field_validator("entity_ids")
    @classmethod
    def normalize_entity_ids(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip().casefold() for value in values if value.strip()))

    @field_validator("state_predicate")
    @classmethod
    def normalize_state_predicate(cls, value: str | None) -> str | None:
        return value.casefold() if value is not None else None

    @field_validator("utterance_actor_id")
    @classmethod
    def normalize_utterance_actor_id(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("utterance_actor_id cannot be blank")
        return value.strip() if value is not None else None

    @field_validator("as_of", "event_after", "event_before", "valid_at", "known_at")
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
        if self.answer_semantics in STATE_ANSWER_SEMANTICS and not self.state_predicate:
            raise ValueError("state_predicate is required for state answer semantics")
        if self.state_predicate is not None and self.answer_semantics not in STATE_ANSWER_SEMANTICS:
            raise ValueError("state_predicate requires explicit state answer semantics")
        if (
            self.answer_semantics is AnswerSemantics.UTTERANCE_HISTORY
            and self.utterance_actor_id is None
        ):
            raise ValueError("utterance_actor_id is required for utterance history")
        if (
            self.utterance_actor_id is not None
            and self.answer_semantics is not AnswerSemantics.UTTERANCE_HISTORY
        ):
            raise ValueError("utterance_actor_id requires utterance history semantics")
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
    scope: MemoryScope = Field(default_factory=MemoryScope)
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
    valid_time_start: datetime
    valid_time_end: datetime | None
    valid_from: datetime
    valid_to: datetime | None
    expires_at: datetime | None
    supersedes_id: str | None
    source_ref: str
    content_hash: str
    entities: list[EntityRef]
    epistemic_kind: EpistemicKind
    resolution_status: ResolutionStatus
    reality_layer: RealityLayer
    source_actor: EvidenceActor
    quote_depth: int
    elicitation_kind: ElicitationKind
    subject_actor_id: str | None
    predicate: str | None
    evidence_turn_ids: list[str]
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class StorageResult(StrictModel):
    action: StorageAction
    memory: MemoryRecord | None
    duplicate_of: str | None = None
    reasons: list[str] = Field(default_factory=list)


class MemoryCorrectionResult(StrictModel):
    previous_memory_id: str
    action: StorageAction
    memory: MemoryRecord | None
    duplicate_of: str | None = None
    reasons: list[str] = Field(default_factory=list)


class TemporalAnchorInput(StrictModel):
    user_id: str = Field(min_length=1, max_length=128)
    scope: MemoryScope = Field(default_factory=MemoryScope)
    name: str = Field(min_length=1, max_length=240)
    aliases: list[str] = Field(default_factory=list, max_length=32)
    start_at: datetime
    end_at: datetime
    consent: ConsentState = ConsentState.UNKNOWN
    sensitivity: Sensitivity = Sensitivity.NORMAL
    source_ref: str = Field(default="conversation:time-anchor", min_length=1, max_length=500)
    source_excerpt: str | None = Field(default=None, max_length=2_000)

    @field_validator("user_id", "name", "source_ref", "source_excerpt")
    @classmethod
    def reject_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("value cannot be blank")
        return value.strip() if value is not None else None

    @field_validator("aliases")
    @classmethod
    def normalize_aliases(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip() for value in values if value.strip()))

    @field_validator("start_at", "end_at")
    @classmethod
    def require_aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("temporal anchor timestamps must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def ordered_window(self) -> TemporalAnchorInput:
        if self.start_at >= self.end_at:
            raise ValueError("start_at must be earlier than end_at")
        return self


class TemporalAnchorRecord(StrictModel):
    id: str
    user_id: str
    scope: MemoryScope = Field(default_factory=MemoryScope)
    name: str
    aliases: list[str]
    start_at: datetime
    end_at: datetime
    status: TemporalAnchorStatus
    consent: ConsentState
    sensitivity: Sensitivity
    source_ref: str
    supersedes_id: str | None
    valid_from: datetime
    valid_to: datetime | None
    created_at: datetime
    updated_at: datetime


class TemporalAnchorStorageResult(StrictModel):
    stored: bool
    anchor: TemporalAnchorRecord | None = None
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
    scope: MemoryScope = Field(default_factory=MemoryScope)
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


class StateQuery(StrictModel):
    user_id: str = Field(min_length=1, max_length=128)
    scope: MemoryScope = Field(default_factory=MemoryScope)
    predicate: str = Field(min_length=1, max_length=240)
    valid_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    known_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    semantics: AnswerSemantics = AnswerSemantics.STATE_AT_VALID_TIME
    reality_layer: RealityLayer = RealityLayer.REAL_WORLD

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


class MemoryUseInput(StrictModel):
    user_id: str = Field(min_length=1, max_length=128)
    scope: MemoryScope = Field(default_factory=MemoryScope)
    memory_id: str = Field(min_length=1, max_length=240)
    response_group_id: str = Field(min_length=1, max_length=240)
    use_mode: RecallUseMode
    purpose: str = Field(min_length=1, max_length=240)
    rendered_excerpt: str | None = Field(default=None, max_length=2_000)
    used_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("used_at")
    @classmethod
    def require_aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("used_at must include a timezone")
        return value.astimezone(UTC)


class MemoryUseRecord(StrictModel):
    id: str
    user_id: str
    scope: MemoryScope
    memory_id: str
    response_group_id: str
    use_mode: RecallUseMode
    purpose: str
    output_hash: str | None
    used_at: datetime
    created_at: datetime


class MemoryUseSummary(StrictModel):
    memory_id: str
    use_count: int = Field(ge=0)
    last_used_at: datetime | None = None


class PolicyConstraintInput(StrictModel):
    user_id: str = Field(min_length=1, max_length=128)
    scope: MemoryScope = Field(default_factory=MemoryScope)
    action: str = Field(min_length=1, max_length=240)
    channel: str = Field(default="all", min_length=1, max_length=128)
    effect: PolicyEffect
    valid_from: datetime = Field(default_factory=lambda: datetime.now(UTC))
    valid_until: datetime | None = None
    source_turn_id: str | None = Field(default=None, min_length=1, max_length=240)
    source_direct_user_instruction: bool = False
    reason_code: str = Field(min_length=1, max_length=240)

    @field_validator("valid_from", "valid_until")
    @classmethod
    def require_aware_time(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("policy timestamps must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def ordered_window(self) -> PolicyConstraintInput:
        if self.valid_until is not None and self.valid_from >= self.valid_until:
            raise ValueError("valid_from must be earlier than valid_until")
        if self.source_turn_id is not None and not self.source_direct_user_instruction:
            raise ValueError(
                "source-backed policy constraints require trusted direct-user attestation"
            )
        if self.source_turn_id is None and self.source_direct_user_instruction:
            raise ValueError("direct-user source attestation requires source_turn_id")
        return self


class PolicyConstraintRecord(StrictModel):
    id: str
    user_id: str
    scope: MemoryScope
    action: str
    channel: str
    effect: PolicyEffect
    status: PolicyConstraintStatus
    version: int
    valid_from: datetime
    valid_until: datetime | None
    source_turn_id: str | None
    reason_code: str
    supersedes_id: str | None
    created_at: datetime


class PolicyGateRequest(StrictModel):
    user_id: str = Field(min_length=1, max_length=128)
    scope: MemoryScope = Field(default_factory=MemoryScope)
    actions: list[str] = Field(min_length=1, max_length=32)
    channel: str = Field(default="chat", min_length=1, max_length=128)
    task_policy_version: int | None = Field(default=None, ge=0)
    as_of: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("actions")
    @classmethod
    def normalize_actions(cls, values: list[str]) -> list[str]:
        normalized = list(
            dict.fromkeys(value.strip().casefold() for value in values if value.strip())
        )
        if not normalized:
            raise ValueError("at least one action is required")
        return normalized

    @field_validator("as_of")
    @classmethod
    def require_aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("as_of must include a timezone")
        return value.astimezone(UTC)


class PolicyGateDecision(StrictModel):
    allowed: bool
    policy_version: int = Field(ge=0)
    blocked_actions: list[str] = Field(default_factory=list)
    applied_constraints: list[PolicyConstraintRecord] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class PolicyBundleManifest(StrictModel):
    profile_id: str
    profile_version: str
    operating_point: str
    calibrated: bool
    production_eligible: bool
    feature_schema_sha256: str | None = None
    training_dataset_sha256: str | None = None
    validation_dataset_sha256: str | None = None
    promotion_report_sha256: str | None = None
    model_fingerprints: list[str] = Field(default_factory=list)


class OpenLoopInput(StrictModel):
    user_id: str = Field(min_length=1, max_length=128)
    scope: MemoryScope
    kind: OpenLoopKind
    summary: str = Field(min_length=1, max_length=2_000)
    topic_keys: list[str] = Field(default_factory=list, max_length=64)
    follow_up_mode: FollowUpMode = FollowUpMode.WHEN_RELEVANT
    follow_up_after: datetime | None = None
    expires_at: datetime | None = None
    source_turn_id: str | None = Field(default=None, min_length=1, max_length=240)
    consent: ConsentState = ConsentState.UNKNOWN
    sensitivity: Sensitivity = Sensitivity.NORMAL
    opened_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("topic_keys")
    @classmethod
    def normalize_topic_keys(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip().casefold() for value in values if value.strip()))

    @field_validator("follow_up_after", "expires_at", "opened_at")
    @classmethod
    def require_aware_time(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("open-loop timestamps must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def valid_open_loop(self) -> OpenLoopInput:
        if self.scope.relationship_id is None:
            raise ValueError("open loops require scope.relationship_id")
        if self.follow_up_mode is FollowUpMode.AT_OR_AFTER_TIME and self.follow_up_after is None:
            raise ValueError("time-based follow-up requires follow_up_after")
        if self.expires_at is not None and self.expires_at <= self.opened_at:
            raise ValueError("expires_at must be later than opened_at")
        if (
            self.expires_at is not None
            and self.follow_up_after is not None
            and self.follow_up_after >= self.expires_at
        ):
            raise ValueError("follow_up_after must be earlier than expires_at")
        return self


class OpenLoopRecord(StrictModel):
    id: str
    user_id: str
    scope: MemoryScope
    kind: OpenLoopKind
    summary: str
    topic_keys: list[str]
    follow_up_mode: FollowUpMode
    status: OpenLoopStatus
    follow_up_after: datetime | None
    expires_at: datetime | None
    source_turn_id: str | None
    consent: ConsentState
    sensitivity: Sensitivity
    resolution_summary: str | None = None
    last_followed_up_at: datetime | None = None
    follow_up_count: int = Field(default=0, ge=0)
    last_response_group_id: str | None = None
    revision: int = Field(ge=1)
    opened_at: datetime
    updated_at: datetime
    resolved_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class OpenLoopStorageResult(StrictModel):
    stored: bool
    open_loop: OpenLoopRecord | None = None
    reasons: list[str] = Field(default_factory=list)


class OpenLoopUpdateRequest(StrictModel):
    user_id: str = Field(min_length=1, max_length=128)
    transition: OpenLoopTransition
    source_turn_id: str | None = Field(default=None, min_length=1, max_length=240)
    resolution_summary: str | None = Field(default=None, max_length=2_000)
    next_follow_up_at: datetime | None = None
    response_group_id: str | None = Field(default=None, min_length=1, max_length=240)
    expected_revision: int | None = Field(default=None, ge=1)
    as_of: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("next_follow_up_at", "as_of")
    @classmethod
    def require_aware_time(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("open-loop update timestamps must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def transition_payload(self) -> OpenLoopUpdateRequest:
        if self.transition is OpenLoopTransition.SNOOZE and self.next_follow_up_at is None:
            raise ValueError("snooze requires next_follow_up_at")
        if self.next_follow_up_at is not None and self.next_follow_up_at <= self.as_of:
            raise ValueError("next_follow_up_at must be later than as_of")
        if (
            self.transition is OpenLoopTransition.MARK_FOLLOWED_UP
            and self.response_group_id is None
        ):
            raise ValueError("mark_followed_up requires response_group_id")
        return self


class FollowUpRequest(StrictModel):
    user_id: str = Field(min_length=1, max_length=128)
    scope: MemoryScope
    current_topic_keys: list[str] = Field(default_factory=list, max_length=64)
    current_turn_requires_full_attention: bool = False
    user_reopened_topic: bool = False
    reopened_open_loop_id: str | None = Field(default=None, min_length=1, max_length=240)
    allow_due_topic_switch: bool = False
    as_of: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("current_topic_keys")
    @classmethod
    def normalize_topic_keys(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip().casefold() for value in values if value.strip()))

    @field_validator("as_of")
    @classmethod
    def require_aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("follow-up timestamps must include a timezone")
        return value.astimezone(UTC)


class FollowUpDecision(StrictModel):
    action: FollowUpAction
    candidate: OpenLoopRecord | None = None
    considered_open_loop_ids: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    response_guidance: str | None = None


class MemoryReferenceFeedbackInput(StrictModel):
    user_id: str = Field(min_length=1, max_length=128)
    scope: MemoryScope = Field(default_factory=MemoryScope)
    memory_id: str | None = Field(default=None, min_length=1, max_length=240)
    evidence_kind: ExperienceEvidenceKind = ExperienceEvidenceKind.MEMORY
    evidence_id: str | None = Field(default=None, min_length=1, max_length=240)
    kind: ReferenceFeedbackKind
    source_turn_id: str | None = Field(default=None, min_length=1, max_length=240)
    note: str | None = Field(default=None, max_length=1_000)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("recorded_at")
    @classmethod
    def require_aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("reference-feedback timestamps must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def normalize_evidence_target(self) -> MemoryReferenceFeedbackInput:
        if self.evidence_kind is ExperienceEvidenceKind.OPEN_LOOP:
            raise ValueError("use an open-loop transition for follow-up feedback")
        if self.evidence_kind is ExperienceEvidenceKind.MEMORY:
            self.evidence_id = self.evidence_id or self.memory_id
            self.memory_id = self.memory_id or self.evidence_id
            if self.memory_id != self.evidence_id:
                raise ValueError("memory_id and evidence_id must identify the same memory")
        elif self.memory_id is not None:
            raise ValueError("memory_id is only valid for memory evidence")
        if self.evidence_id is None:
            raise ValueError("reference feedback requires an evidence target")
        return self


class MemoryReferenceFeedbackRecord(StrictModel):
    id: str
    user_id: str
    scope: MemoryScope
    memory_id: str | None
    evidence_kind: ExperienceEvidenceKind
    evidence_id: str
    kind: ReferenceFeedbackKind
    source_turn_id: str | None
    note: str | None
    recorded_at: datetime
    created_at: datetime


class ExperienceEvidenceRef(StrictModel):
    kind: ExperienceEvidenceKind
    id: str = Field(min_length=1, max_length=240)


class MemoryUseDecision(StrictModel):
    evidence: ExperienceEvidenceRef
    mode: MemoryReferenceMode
    reasons: list[str] = Field(default_factory=list)


class MemoryUsePlan(StrictModel):
    decisions: list[MemoryUseDecision] = Field(default_factory=list)
    guidance: list[str] = Field(default_factory=list)


class ResponsePlanRequest(StrictModel):
    user_id: str = Field(min_length=1, max_length=128)
    scope: MemoryScope
    trigger_turn_id: str = Field(min_length=1, max_length=240)
    goal: ResponseGoal
    recall_request: RecallRequest | None = None
    user_asked_memory_question: bool = False
    current_turn_requires_full_attention: bool = False
    current_topic_keys: list[str] = Field(default_factory=list, max_length=64)
    user_reopened_topic: bool = False
    reopened_open_loop_id: str | None = Field(default=None, min_length=1, max_length=240)
    allow_follow_up: bool = True
    allow_due_topic_switch: bool = False
    allow_afterthought: bool | None = None
    channel_supports_multiple_beats: bool = True
    conversation_started_at: datetime | None = None
    cancel_on_new_user_turn: bool | None = None
    as_of: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("current_topic_keys")
    @classmethod
    def normalize_topic_keys(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip().casefold() for value in values if value.strip()))

    @field_validator("conversation_started_at", "as_of")
    @classmethod
    def require_aware_time(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("response-plan timestamps must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def aligned_recall_request(self) -> ResponsePlanRequest:
        if self.scope.conversation_id is None:
            raise ValueError("response plans require scope.conversation_id")
        if self.recall_request is not None and (
            self.recall_request.user_id != self.user_id or self.recall_request.scope != self.scope
        ):
            raise ValueError("recall_request must use the response plan user and exact scope")
        return self


class ResponseBeatRecord(StrictModel):
    id: str
    ordinal: int = Field(ge=0)
    kind: ResponseBeatKind
    source: ResponseBeatSource
    release_condition: BeatReleaseCondition
    status: ResponseBeatStatus
    guidance: str
    evidence: list[ExperienceEvidenceRef] = Field(default_factory=list)
    output_hash: str | None = None
    sent_at: datetime | None = None
    cancelled_at: datetime | None = None


class ResponsePlanRecord(StrictModel):
    id: str
    response_group_id: str
    user_id: str
    scope: MemoryScope
    trigger_turn_id: str
    goal: ResponseGoal
    delivery_mode: ResponseDeliveryMode
    status: ResponsePlanStatus
    revision: int = Field(ge=0)
    resolution_status: ResponsePlanResolutionStatus
    policy_version: int = Field(ge=0)
    config_fingerprint: str
    policy_bundle: PolicyBundleManifest
    cancel_on_new_user_turn: bool
    recall_action: RetrievalAction | None = None
    memory_use_plan: MemoryUsePlan
    follow_up: FollowUpDecision | None = None
    beats: list[ResponseBeatRecord] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None = None
    cancelled_at: datetime | None = None
    cancellation_reason: str | None = None


class ResponsePlanResolveRequest(StrictModel):
    user_id: str = Field(min_length=1, max_length=128)
    expected_revision: int = Field(ge=0)
    resolution_key: str = Field(min_length=1, max_length=240)
    as_of: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("as_of")
    @classmethod
    def require_aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("resolution timestamps must include a timezone")
        return value.astimezone(UTC)


class ResponsePlanInterruptRequest(StrictModel):
    user_id: str = Field(min_length=1, max_length=128)
    scope: MemoryScope
    reason: str = Field(default="new_user_input", min_length=1, max_length=240)
    as_of: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("as_of")
    @classmethod
    def require_aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("interrupt timestamps must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def require_conversation(self) -> ResponsePlanInterruptRequest:
        if self.scope.conversation_id is None:
            raise ValueError("interrupts require an exact conversation scope")
        return self


class ResponseBeatSentRequest(StrictModel):
    user_id: str = Field(min_length=1, max_length=128)
    rendered_text: str = Field(min_length=1, max_length=50_000)
    task_policy_version: int = Field(ge=0)
    host_release_signal: bool = False
    sent_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("sent_at")
    @classmethod
    def require_aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("sent_at must include a timezone")
        return value.astimezone(UTC)


class ConversationRepairRequest(StrictModel):
    user_id: str = Field(min_length=1, max_length=128)
    scope: MemoryScope = Field(default_factory=MemoryScope)
    kind: RepairKind
    source_turn_id: str | None = Field(default=None, min_length=1, max_length=240)
    memory_id: str | None = Field(default=None, min_length=1, max_length=240)
    evidence_kind: ExperienceEvidenceKind = ExperienceEvidenceKind.MEMORY
    evidence_id: str | None = Field(default=None, min_length=1, max_length=240)
    open_loop_id: str | None = Field(default=None, min_length=1, max_length=240)
    replacement_content: str | None = Field(default=None, max_length=20_000)
    replacement_title: str | None = Field(default=None, max_length=240)
    resolution_summary: str | None = Field(default=None, max_length=2_000)
    as_of: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("as_of")
    @classmethod
    def require_aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("repair timestamps must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def valid_target(self) -> ConversationRepairRequest:
        loop_actions = {RepairKind.RESOLVE_OPEN_LOOP, RepairKind.CANCEL_OPEN_LOOP}
        if self.kind is RepairKind.CORRECT_MEMORY and self.memory_id is None:
            raise ValueError("memory repair requires memory_id")
        if self.kind in {RepairKind.WRONG_REFERENCE, RepairKind.STOP_REFERENCING}:
            target = MemoryReferenceFeedbackInput(
                user_id=self.user_id,
                scope=self.scope,
                memory_id=self.memory_id,
                evidence_kind=self.evidence_kind,
                evidence_id=self.evidence_id,
                kind=ReferenceFeedbackKind.WRONG_MATCH,
            )
            self.memory_id = target.memory_id
            self.evidence_id = target.evidence_id
        if self.kind in loop_actions and self.open_loop_id is None:
            raise ValueError("open-loop repair requires open_loop_id")
        if self.kind is RepairKind.CORRECT_MEMORY and not self.replacement_content:
            raise ValueError("correct_memory requires replacement_content")
        return self


class ConversationRepairResult(StrictModel):
    applied: bool
    kind: RepairKind
    corrected_memory: MemoryCorrectionResult | None = None
    reference_feedback: MemoryReferenceFeedbackRecord | None = None
    open_loop: OpenLoopRecord | None = None
    acknowledgement_guidance: str
    reasons: list[str] = Field(default_factory=list)


class DiscourseInterpretRequest(StrictModel):
    user_id: str = Field(min_length=1, max_length=128)
    scope: MemoryScope
    turn_id: str = Field(min_length=1, max_length=240)
    current_topic_keys: list[str] = Field(default_factory=list, max_length=64)
    apply_low_risk_actions: bool = True
    as_of: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("as_of")
    @classmethod
    def require_aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("interpretation timestamps must include a timezone")
        return value.astimezone(UTC)

    @field_validator("current_topic_keys")
    @classmethod
    def normalize_topic_keys(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip().casefold() for value in values if value.strip()))

    @model_validator(mode="after")
    def require_conversation(self) -> DiscourseInterpretRequest:
        if self.scope.conversation_id is None:
            raise ValueError("discourse interpretation requires an exact conversation")
        return self


class DiscourseInterpretation(StrictModel):
    user_id: str
    scope: MemoryScope
    turn_id: str
    status: DiscourseInterpretationStatus
    signals: list[DiscourseSignal] = Field(default_factory=list)
    matched_phrases: dict[DiscourseSignal, list[str]] = Field(default_factory=dict)
    suggested_goal: ResponseGoal | None = None
    user_asked_memory_question: bool = False
    current_turn_requires_full_attention: bool = False
    interrupt_pending_response: bool = False
    automatic_action_status: AutomaticActionStatus = AutomaticActionStatus.NOT_REQUESTED
    repair: ConversationRepairResult | None = None
    cancelled_response_plan_ids: list[str] = Field(default_factory=list)
    response_guidance: list[str] = Field(default_factory=list)


class InterpretedResponsePlanRequest(StrictModel):
    user_id: str = Field(min_length=1, max_length=128)
    scope: MemoryScope
    turn_id: str = Field(min_length=1, max_length=240)
    fallback_goal: ResponseGoal = ResponseGoal.COMFORT
    recall_intent: RecallIntent = RecallIntent.GENERAL
    enable_recall: bool = True
    current_topic_keys: list[str] = Field(default_factory=list, max_length=64)
    allow_follow_up: bool = True
    allow_afterthought: bool | None = None
    conversation_started_at: datetime | None = None
    as_of: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("current_topic_keys")
    @classmethod
    def normalize_topic_keys(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip().casefold() for value in values if value.strip()))

    @field_validator("conversation_started_at", "as_of")
    @classmethod
    def require_aware_time(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("interpreted plan timestamps must include a timezone")
        return value.astimezone(UTC) if value is not None else None

    @model_validator(mode="after")
    def require_conversation(self) -> InterpretedResponsePlanRequest:
        if self.scope.conversation_id is None:
            raise ValueError("interpreted response plans require an exact conversation")
        return self


class InterpretedResponsePlan(StrictModel):
    interpretation: DiscourseInterpretation
    plan: ResponsePlanRecord


class CompanionContext(StrictModel):
    user_id: str
    scope: MemoryScope = Field(default_factory=MemoryScope)
    intent: RecallIntent
    sections: dict[str, list[RecallItem]]
    event_fallback: list[EventRecallItem]
    turn_fallback: list[TurnRecallItem] = Field(default_factory=list)
    guidance: list[str]
    pending_review_count: int
    config_fingerprint: str
    policy_bundle: PolicyBundleManifest
    generated_at: datetime
    character_budget: int
    rendered_characters: int
    token_budget: int
    rendered_tokens: int
    tokenizer: str
    prompt_text: str
    retrieval_outcome: RetrievalOutcome
    retrieval_action: RetrievalAction = RetrievalAction.ABSTAIN
    answer_semantics: AnswerSemantics = AnswerSemantics.EVENT_RECALL
    answer_cardinality: AnswerCardinality = AnswerCardinality.AUTO
    ambiguity_detected: bool = False
    clarification_guidance: str | None = None
    safety_budget_exceeded: bool = False
    budget_exhausted: bool = False
    budget_omitted_count: int = Field(default=0, ge=0)
    state_evidence_omitted_count: int = Field(default=0, ge=0)
    resolved_temporal_anchor: TemporalAnchorRecord | None = None
    temporal_anchor_candidates: list[TemporalAnchorRecord] = Field(default_factory=list)
    temporal_anchor_ambiguity: bool = False
    integrity_manifest: RetrievalIntegrityManifest = Field(
        default_factory=RetrievalIntegrityManifest
    )
    memory_use_summaries: list[MemoryUseSummary] = Field(default_factory=list)
    policy_version: int = Field(default=0, ge=0)
    state_result: StateQueryResult | None = None


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
    temporal_anchors: list[TemporalAnchorRecord] = Field(default_factory=list)
    conversation_turns: list[ConversationTurnRecord] = Field(default_factory=list)
    memory_uses: list[MemoryUseRecord] = Field(default_factory=list)
    policy_constraints: list[PolicyConstraintRecord] = Field(default_factory=list)
    open_loops: list[OpenLoopRecord] = Field(default_factory=list)
    reference_feedback: list[MemoryReferenceFeedbackRecord] = Field(default_factory=list)
    response_plans: list[ResponsePlanRecord] = Field(default_factory=list)

    @model_validator(mode="after")
    def verify_scope(self) -> ExportBundle:
        if any(memory.user_id != self.user_id for memory in self.memories):
            raise ValueError("export contains a memory from another user")
        if any(event.user_id != self.user_id for event in self.events):
            raise ValueError("export contains an event from another user")
        if any(anchor.user_id != self.user_id for anchor in self.temporal_anchors):
            raise ValueError("export contains a temporal anchor from another user")
        if any(turn.user_id != self.user_id for turn in self.conversation_turns):
            raise ValueError("export contains a conversation turn from another user")
        if any(use.user_id != self.user_id for use in self.memory_uses):
            raise ValueError("export contains a memory use from another user")
        if any(constraint.user_id != self.user_id for constraint in self.policy_constraints):
            raise ValueError("export contains a policy constraint from another user")
        if any(open_loop.user_id != self.user_id for open_loop in self.open_loops):
            raise ValueError("export contains an open loop from another user")
        if any(feedback.user_id != self.user_id for feedback in self.reference_feedback):
            raise ValueError("export contains reference feedback from another user")
        if any(plan.user_id != self.user_id for plan in self.response_plans):
            raise ValueError("export contains a response plan from another user")
        return self


class ProactivityRequest(StrictModel):
    user_id: str = Field(min_length=1, max_length=128)
    scope: MemoryScope = Field(default_factory=MemoryScope)
    channel: str = Field(default="chat", min_length=1, max_length=128)
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
