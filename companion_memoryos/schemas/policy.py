from __future__ import annotations

from datetime import UTC, datetime

from pydantic import Field, field_validator, model_validator

from companion_memoryos.schemas.core import (
    MemoryScope,
    PolicyConstraintStatus,
    PolicyEffect,
    StrictModel,
)


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
