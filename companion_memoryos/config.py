from __future__ import annotations

import hashlib
import json
import os
import tomllib
from importlib.resources import files
from pathlib import Path
from typing import Any

from platformdirs import user_data_path
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from companion_memoryos.constants import (
    CONFIG_ENV_NAME,
    CONFIG_SCHEMA_VERSION,
    DATA_HOME_ENV_NAME,
    DEFAULT_CONFIG_RESOURCE,
    DEFAULT_ENCODING,
    SHA256_HEX_LENGTH,
    UNIT_INTERVAL_MAX,
    UNIT_INTERVAL_MIN,
    WEIGHT_TARGET,
    WEIGHT_TOLERANCE,
)
from companion_memoryos.schemas import MemoryKind, RecallIntent


class FrozenConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ServerConfig(FrozenConfig):
    host: str
    port: int = Field(ge=1, le=65_535)

    @field_validator("host")
    @classmethod
    def loopback_only(cls, value: str) -> str:
        if value not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("server.host must be a loopback address")
        return value


class DatabaseConfig(FrozenConfig):
    busy_timeout_ms: int = Field(gt=0)


class SecurityConfig(FrozenConfig):
    token_bytes: int = Field(ge=16)


class RetentionConfig(FrozenConfig):
    ephemeral_hours: int = Field(gt=0)
    short_term_days: int = Field(gt=0)
    long_term_days: int = Field(gt=0)
    sensitive_max_days: int = Field(gt=0)
    candidate_review_days: int = Field(gt=0)

    @model_validator(mode="after")
    def ordered_windows(self) -> RetentionConfig:
        if self.short_term_days > self.long_term_days:
            raise ValueError("short_term_days cannot exceed long_term_days")
        return self


class RetrievalConfig(FrozenConfig):
    candidate_pool: int = Field(gt=0)
    semantic_candidate_pool: int = Field(gt=0)
    event_candidate_pool: int = Field(gt=0)
    default_limit: int = Field(gt=0)
    max_limit: int = Field(gt=0)
    default_event_limit: int = Field(ge=0)
    max_event_limit: int = Field(ge=0)
    turn_candidate_pool: int = Field(gt=0)
    default_turn_limit: int = Field(ge=0)
    max_turn_limit: int = Field(ge=0)
    default_max_characters: int = Field(gt=0)
    max_characters: int = Field(gt=0)
    default_max_tokens: int = Field(gt=0)
    max_tokens: int = Field(gt=0)
    recency_half_life_days: float = Field(gt=0)
    cjk_ngram_min: int = Field(gt=0)
    cjk_ngram_max: int = Field(gt=0)
    minimum_token_length: int = Field(gt=0)
    max_fts_terms: int = Field(gt=0)
    max_index_terms: int = Field(gt=0)
    minimum_natural_query_characters: int = Field(gt=0)
    minimum_query_match: float = Field(ge=UNIT_INTERVAL_MIN, le=UNIT_INTERVAL_MAX)
    minimum_semantic_similarity: float = Field(ge=UNIT_INTERVAL_MIN, le=UNIT_INTERVAL_MAX)
    ambiguity_score_gap: float = Field(ge=UNIT_INTERVAL_MIN, le=UNIT_INTERVAL_MAX)
    confidence_hedge_threshold: float = Field(ge=UNIT_INTERVAL_MIN, le=UNIT_INTERVAL_MAX)
    confidence_natural_threshold: float = Field(ge=UNIT_INTERVAL_MIN, le=UNIT_INTERVAL_MAX)

    @model_validator(mode="after")
    def consistent_bounds(self) -> RetrievalConfig:
        if self.default_limit > self.max_limit:
            raise ValueError("default_limit cannot exceed max_limit")
        if self.default_event_limit > self.max_event_limit:
            raise ValueError("default_event_limit cannot exceed max_event_limit")
        if self.default_turn_limit > self.max_turn_limit:
            raise ValueError("default_turn_limit cannot exceed max_turn_limit")
        if self.default_max_characters > self.max_characters:
            raise ValueError("default_max_characters cannot exceed max_characters")
        if self.default_max_tokens > self.max_tokens:
            raise ValueError("default_max_tokens cannot exceed max_tokens")
        if self.cjk_ngram_min > self.cjk_ngram_max:
            raise ValueError("cjk_ngram_min cannot exceed cjk_ngram_max")
        if self.minimum_query_match > self.confidence_hedge_threshold:
            raise ValueError("minimum_query_match cannot exceed confidence_hedge_threshold")
        if self.confidence_hedge_threshold > self.confidence_natural_threshold:
            raise ValueError(
                "confidence_hedge_threshold cannot exceed confidence_natural_threshold"
            )
        return self


class RankingConfig(FrozenConfig):
    lexical: float = Field(ge=UNIT_INTERVAL_MIN, le=UNIT_INTERVAL_MAX)
    semantic: float = Field(ge=UNIT_INTERVAL_MIN, le=UNIT_INTERVAL_MAX)
    entity: float = Field(ge=UNIT_INTERVAL_MIN, le=UNIT_INTERVAL_MAX)
    temporal: float = Field(ge=UNIT_INTERVAL_MIN, le=UNIT_INTERVAL_MAX)
    salience: float = Field(ge=UNIT_INTERVAL_MIN, le=UNIT_INTERVAL_MAX)
    recency: float = Field(ge=UNIT_INTERVAL_MIN, le=UNIT_INTERVAL_MAX)
    emotion: float = Field(ge=UNIT_INTERVAL_MIN, le=UNIT_INTERVAL_MAX)
    need: float = Field(ge=UNIT_INTERVAL_MIN, le=UNIT_INTERVAL_MAX)
    continuity: float = Field(ge=UNIT_INTERVAL_MIN, le=UNIT_INTERVAL_MAX)

    @model_validator(mode="after")
    def weights_sum_to_one(self) -> RankingConfig:
        total = sum(self.model_dump().values())
        if abs(total - WEIGHT_TARGET) > WEIGHT_TOLERANCE:
            raise ValueError("ranking weights must sum to 1.0")
        return self


class PolicyConfig(FrozenConfig):
    sensitive_requires_explicit_consent: bool
    highly_sensitive_requires_review: bool
    unknown_sensitive_is_discarded: bool
    wellbeing_signals_are_ephemeral: bool
    exact_duplicate_detection: bool


class TokenizationConfig(FrozenConfig):
    encoding: str = Field(min_length=1)


class EventArchiveConfig(FrozenConfig):
    enabled: bool
    require_granted_consent: bool
    allow_assistant_events: bool
    allow_highly_sensitive: bool
    require_scoped_recall: bool
    retention_days: int = Field(gt=0)
    sensitive_retention_days: int = Field(gt=0)

    @model_validator(mode="after")
    def sensitive_window_is_not_longer(self) -> EventArchiveConfig:
        if self.sensitive_retention_days > self.retention_days:
            raise ValueError("sensitive_retention_days cannot exceed retention_days")
        return self


class TemporalAnchorConfig(FrozenConfig):
    enabled: bool
    minimum_match_characters: int = Field(gt=0)
    max_matches: int = Field(gt=0)
    allow_sensitive: bool


class ConversationLedgerConfig(FrozenConfig):
    enabled: bool
    require_granted_consent: bool
    allow_assistant_turns: bool
    allow_highly_sensitive: bool
    require_scoped_recall: bool


class EpistemicConfig(FrozenConfig):
    weak_confirmation_requires_review: bool
    ineligible_self_report_becomes_observation: bool


class MemoryUseLedgerConfig(FrozenConfig):
    enabled: bool


class OpenLoopConfig(FrozenConfig):
    enabled: bool
    require_granted_consent: bool
    allow_highly_sensitive: bool


class ExperienceConfig(FrozenConfig):
    enabled: bool
    default_cancel_on_new_user_turn: bool
    avoid_repeat_within_conversation: bool
    semantic_beats_enabled_by_default: bool
    afterthought_enabled_by_default: bool


class DiscourseConfig(FrozenConfig):
    listen_only_phrases: list[str]
    advice_request_phrases: list[str]
    memory_question_phrases: list[str]
    wrong_reference_phrases: list[str]
    stop_referencing_phrases: list[str]
    topic_switch_phrases: list[str]
    outcome_reported_phrases: list[str]

    @field_validator(
        "listen_only_phrases",
        "advice_request_phrases",
        "memory_question_phrases",
        "wrong_reference_phrases",
        "stop_referencing_phrases",
        "topic_switch_phrases",
        "outcome_reported_phrases",
    )
    @classmethod
    def normalized_phrases(cls, values: list[str]) -> list[str]:
        normalized = list(
            dict.fromkeys(value.strip().casefold() for value in values if value.strip())
        )
        if not normalized:
            raise ValueError("each discourse phrase family requires at least one phrase")
        return normalized


class PolicyEngineConfig(FrozenConfig):
    enabled: bool
    default_allow: bool


class PolicyBundleConfig(FrozenConfig):
    profile_id: str = Field(min_length=1, max_length=240)
    profile_version: str = Field(min_length=1, max_length=128)
    operating_point: str = Field(min_length=1, max_length=240)
    calibrated: bool
    production_eligible: bool
    feature_schema_sha256: str | None = None
    training_dataset_sha256: str | None = None
    validation_dataset_sha256: str | None = None
    promotion_report_sha256: str | None = None
    model_fingerprints: list[str] = Field(default_factory=list, max_length=32)

    @field_validator(
        "feature_schema_sha256",
        "training_dataset_sha256",
        "validation_dataset_sha256",
        "promotion_report_sha256",
    )
    @classmethod
    def validate_digest(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.casefold()
        if len(normalized) != SHA256_HEX_LENGTH or any(
            character not in "0123456789abcdef" for character in normalized
        ):
            raise ValueError("policy bundle digests must be SHA-256 hex values")
        return normalized

    @field_validator("model_fingerprints")
    @classmethod
    def validate_model_fingerprints(cls, values: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(value.strip() for value in values if value.strip()))
        if len(normalized) != len(values):
            raise ValueError("model_fingerprints cannot contain blanks or duplicates")
        return normalized

    @model_validator(mode="after")
    def production_requires_evidence(self) -> PolicyBundleConfig:
        if not self.production_eligible:
            return self
        if not self.calibrated:
            raise ValueError("production-eligible policy bundles must be calibrated")
        if not all(
            (
                self.feature_schema_sha256,
                self.training_dataset_sha256,
                self.validation_dataset_sha256,
                self.promotion_report_sha256,
                self.model_fingerprints,
            )
        ):
            raise ValueError("production-eligible policy bundles require evidence hashes")
        return self


class ProactivityConfig(FrozenConfig):
    enabled_by_default: bool
    minimum_idle_minutes: int = Field(gt=0)
    cooldown_minutes: int = Field(gt=0)
    maximum_outreaches_per_day: int = Field(gt=0)
    negative_signal_quiet_hours: int = Field(gt=0)
    require_relevant_reason: bool


class CompanionConfig(FrozenConfig):
    schema_version: str
    server: ServerConfig
    database: DatabaseConfig
    security: SecurityConfig
    retention: RetentionConfig
    retrieval: RetrievalConfig
    ranking: RankingConfig
    policy: PolicyConfig
    tokenization: TokenizationConfig
    event_archive: EventArchiveConfig
    temporal_anchors: TemporalAnchorConfig
    conversation_ledger: ConversationLedgerConfig
    epistemic: EpistemicConfig
    memory_use_ledger: MemoryUseLedgerConfig
    open_loops: OpenLoopConfig
    experience: ExperienceConfig
    discourse: DiscourseConfig
    policy_engine: PolicyEngineConfig
    policy_bundle: PolicyBundleConfig
    proactivity: ProactivityConfig
    continuity: dict[RecallIntent, dict[MemoryKind, float]]

    @field_validator("schema_version")
    @classmethod
    def current_schema(cls, value: str) -> str:
        if value != CONFIG_SCHEMA_VERSION:
            raise ValueError(f"unsupported config schema: {value}")
        return value

    @field_validator("continuity")
    @classmethod
    def complete_continuity_matrix(
        cls, value: dict[RecallIntent, dict[MemoryKind, float]]
    ) -> dict[RecallIntent, dict[MemoryKind, float]]:
        if set(value) != set(RecallIntent):
            raise ValueError("continuity must define every recall intent")
        for intent, weights in value.items():
            if set(weights) != set(MemoryKind):
                raise ValueError(f"continuity.{intent} must define every memory kind")
            if any(
                weight < UNIT_INTERVAL_MIN or weight > UNIT_INTERVAL_MAX
                for weight in weights.values()
            ):
                raise ValueError(f"continuity.{intent} weights must be within [0, 1]")
        return value

    def fingerprint(self) -> str:
        payload = json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode(DEFAULT_ENCODING)).hexdigest()


def default_data_dir() -> Path:
    configured = os.environ.get(DATA_HOME_ENV_NAME)
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(user_data_path("CompanionMemoryOS", appauthor=False)).resolve()


def load_config(path: str | Path | None = None) -> CompanionConfig:
    resource = files("companion_memoryos").joinpath(DEFAULT_CONFIG_RESOURCE)
    base = tomllib.loads(resource.read_text(encoding=DEFAULT_ENCODING))
    selected = Path(path) if path is not None else _path_from_environment()
    if selected is not None:
        with selected.expanduser().open("rb") as handle:
            override = tomllib.load(handle)
        base = _deep_merge(base, override)
    return CompanionConfig.model_validate(base)


def _path_from_environment() -> Path | None:
    configured = os.environ.get(CONFIG_ENV_NAME)
    return Path(configured) if configured else None


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = _deep_merge(current, value)
        else:
            merged[key] = value
    return merged
