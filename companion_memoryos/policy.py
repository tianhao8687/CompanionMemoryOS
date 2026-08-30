from __future__ import annotations

from datetime import datetime, timedelta

from companion_memoryos.config import CompanionConfig
from companion_memoryos.schemas import (
    ConsentState,
    MemoryInput,
    MemoryKind,
    RetentionClass,
    Sensitivity,
    StorageAction,
    StoragePolicyDecision,
)

DEFAULT_RETENTION_BY_KIND: dict[MemoryKind, RetentionClass] = {
    MemoryKind.IDENTITY: RetentionClass.DURABLE,
    MemoryKind.PREFERENCE: RetentionClass.DURABLE,
    MemoryKind.BOUNDARY: RetentionClass.DURABLE,
    MemoryKind.SUPPORT_STRATEGY: RetentionClass.DURABLE,
    MemoryKind.COMMITMENT: RetentionClass.LONG_TERM,
    MemoryKind.RITUAL: RetentionClass.LONG_TERM,
    MemoryKind.EMOTION_EPISODE: RetentionClass.SHORT_TERM,
    MemoryKind.SHARED_MOMENT: RetentionClass.LONG_TERM,
    MemoryKind.WELLBEING_SIGNAL: RetentionClass.EPHEMERAL,
    MemoryKind.RELATIONSHIP: RetentionClass.DURABLE,
}


def decide_storage(item: MemoryInput, config: CompanionConfig) -> StoragePolicyDecision:
    retention = item.retention or DEFAULT_RETENTION_BY_KIND[item.kind]
    reasons: list[str] = []

    if item.consent is ConsentState.DENIED:
        return StoragePolicyDecision(
            action=StorageAction.DISCARD,
            retention=retention,
            expires_at=None,
            reasons=["consent_denied"],
        )

    if item.kind is MemoryKind.WELLBEING_SIGNAL and config.policy.wellbeing_signals_are_ephemeral:
        retention = RetentionClass.EPHEMERAL
        reasons.append("wellbeing_forced_ephemeral")

    is_sensitive = item.sensitivity is not Sensitivity.NORMAL
    if (
        is_sensitive
        and item.consent is ConsentState.UNKNOWN
        and config.policy.unknown_sensitive_is_discarded
    ):
        return StoragePolicyDecision(
            action=StorageAction.DISCARD,
            retention=retention,
            expires_at=None,
            reasons=[*reasons, "sensitive_consent_unknown"],
        )

    explicitly_consented = item.consent is ConsentState.GRANTED and item.explicit_user_request
    if (
        is_sensitive
        and config.policy.sensitive_requires_explicit_consent
        and not explicitly_consented
    ):
        return StoragePolicyDecision(
            action=StorageAction.DISCARD,
            retention=retention,
            expires_at=None,
            reasons=[*reasons, "sensitive_without_explicit_consent"],
        )

    action = StorageAction.ACTIVATE if explicitly_consented else StorageAction.CANDIDATE
    reasons.append("explicitly_confirmed" if explicitly_consented else "requires_review")
    if (
        item.sensitivity is Sensitivity.HIGHLY_SENSITIVE
        and config.policy.highly_sensitive_requires_review
    ):
        action = StorageAction.CANDIDATE
        reasons.append("highly_sensitive_requires_review")

    expires_at = retention_expiry(item.event_at, retention, item.sensitivity, config)
    if is_sensitive:
        reasons.append("sensitive_retention_capped")
    if action is StorageAction.CANDIDATE:
        review_cap = item.event_at + timedelta(days=config.retention.candidate_review_days)
        expires_at = _earlier(expires_at, review_cap)

    return StoragePolicyDecision(
        action=action,
        retention=retention,
        expires_at=expires_at,
        reasons=reasons,
    )


def retention_expiry(
    event_at: datetime,
    retention: RetentionClass,
    sensitivity: Sensitivity,
    config: CompanionConfig,
) -> datetime | None:
    expires_at: datetime | None
    if retention is RetentionClass.DURABLE:
        expires_at = None
    elif retention is RetentionClass.EPHEMERAL:
        expires_at = event_at + timedelta(hours=config.retention.ephemeral_hours)
    elif retention is RetentionClass.SHORT_TERM:
        expires_at = event_at + timedelta(days=config.retention.short_term_days)
    else:
        expires_at = event_at + timedelta(days=config.retention.long_term_days)
    if sensitivity is not Sensitivity.NORMAL:
        sensitive_cap = event_at + timedelta(days=config.retention.sensitive_max_days)
        expires_at = _earlier(expires_at, sensitive_cap)
    return expires_at


def _earlier(current: datetime | None, cap: datetime) -> datetime:
    return cap if current is None else min(current, cap)
