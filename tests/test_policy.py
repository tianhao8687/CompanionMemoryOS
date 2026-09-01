from __future__ import annotations

from datetime import UTC, datetime, timedelta

from companion_memoryos.config import CompanionConfig
from companion_memoryos.policy import decide_storage
from companion_memoryos.schemas import (
    ConsentState,
    MemoryInput,
    MemoryKind,
    RetentionClass,
    Sensitivity,
    StorageAction,
)


def item(**updates: object) -> MemoryInput:
    values: dict[str, object] = {
        "user_id": "alice",
        "kind": MemoryKind.PREFERENCE,
        "title": "称呼偏好",
        "content": "请叫我小禾",
    }
    values.update(updates)
    return MemoryInput.model_validate(values)


def test_denied_consent_is_never_stored(config: CompanionConfig) -> None:
    decision = decide_storage(item(consent=ConsentState.DENIED), config)
    assert decision.action is StorageAction.DISCARD


def test_unknown_sensitive_memory_is_discarded(config: CompanionConfig) -> None:
    decision = decide_storage(item(sensitivity=Sensitivity.SENSITIVE), config)
    assert decision.action is StorageAction.DISCARD


def test_explicit_normal_memory_activates(config: CompanionConfig) -> None:
    decision = decide_storage(
        item(consent=ConsentState.GRANTED, explicit_user_request=True), config
    )
    assert decision.action is StorageAction.ACTIVATE


def test_highly_sensitive_memory_still_requires_review(config: CompanionConfig) -> None:
    decision = decide_storage(
        item(
            consent=ConsentState.GRANTED,
            explicit_user_request=True,
            sensitivity=Sensitivity.HIGHLY_SENSITIVE,
        ),
        config,
    )
    assert decision.action is StorageAction.CANDIDATE


def test_wellbeing_signal_is_ephemeral(config: CompanionConfig) -> None:
    decision = decide_storage(
        item(kind=MemoryKind.WELLBEING_SIGNAL, title="睡眠", content="昨晚没睡好"),
        config,
    )
    assert decision.retention is RetentionClass.EPHEMERAL
    assert decision.expires_at is not None


def test_candidate_review_window_uses_storage_time(config: CompanionConfig) -> None:
    stored_at = datetime(2026, 8, 31, tzinfo=UTC)
    decision = decide_storage(
        item(event_at=datetime(2020, 1, 1, tzinfo=UTC)),
        config,
        stored_at=stored_at,
    )

    assert decision.expires_at == stored_at + timedelta(days=config.retention.candidate_review_days)


def test_future_event_cannot_extend_sensitive_storage_cap(
    config: CompanionConfig,
) -> None:
    stored_at = datetime(2026, 8, 31, tzinfo=UTC)
    decision = decide_storage(
        item(
            event_at=datetime(2100, 1, 1, tzinfo=UTC),
            consent=ConsentState.GRANTED,
            explicit_user_request=True,
            sensitivity=Sensitivity.SENSITIVE,
        ),
        config,
        stored_at=stored_at,
    )

    assert decision.expires_at == stored_at + timedelta(days=config.retention.sensitive_max_days)
