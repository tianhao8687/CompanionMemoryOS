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
    default_limit: int = Field(gt=0)
    max_limit: int = Field(gt=0)
    default_max_characters: int = Field(gt=0)
    max_characters: int = Field(gt=0)
    recency_half_life_days: float = Field(gt=0)
    cjk_ngram_min: int = Field(gt=0)
    cjk_ngram_max: int = Field(gt=0)
    minimum_token_length: int = Field(gt=0)
    max_fts_terms: int = Field(gt=0)

    @model_validator(mode="after")
    def consistent_bounds(self) -> RetrievalConfig:
        if self.default_limit > self.max_limit:
            raise ValueError("default_limit cannot exceed max_limit")
        if self.default_max_characters > self.max_characters:
            raise ValueError("default_max_characters cannot exceed max_characters")
        if self.cjk_ngram_min > self.cjk_ngram_max:
            raise ValueError("cjk_ngram_min cannot exceed cjk_ngram_max")
        return self


class RankingConfig(FrozenConfig):
    lexical: float = Field(ge=UNIT_INTERVAL_MIN, le=UNIT_INTERVAL_MAX)
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


class CompanionConfig(FrozenConfig):
    schema_version: str
    server: ServerConfig
    database: DatabaseConfig
    security: SecurityConfig
    retention: RetentionConfig
    retrieval: RetrievalConfig
    ranking: RankingConfig
    policy: PolicyConfig
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
