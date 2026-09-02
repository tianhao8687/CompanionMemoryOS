from __future__ import annotations

import math
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

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


class MemoryUseType(StrEnum):
    EXPLICIT_REFERENCE = "explicit_reference"
    SOFT_REFERENCE = "soft_reference"
    SILENT_INFLUENCE = "silent_influence"
    CLARIFICATION = "clarification"


class EpisodeStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    MERGED = "merged"
    EMPTY = "empty"


def _validate_embedding(embedding: list[float] | None, space: str | None) -> None:
    if (embedding is None) != (space is None):
        raise ValueError("embedding and embedding_space must be supplied together")
    if embedding is not None and any(not math.isfinite(value) for value in embedding):
        raise ValueError("embedding values must be finite")
