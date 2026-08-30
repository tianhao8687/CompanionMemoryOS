from __future__ import annotations

from datetime import UTC, datetime, timedelta

from companion_memoryos.schemas import ProactivityRequest
from companion_memoryos.service import CompanionMemoryService


def request(service: CompanionMemoryService, **updates: object) -> ProactivityRequest:
    now = datetime.now(UTC)
    values: dict[str, object] = {
        "user_id": "alice",
        "permission_granted": True,
        "last_user_message_at": now
        - timedelta(minutes=service.config.proactivity.minimum_idle_minutes),
        "has_relevant_reason": True,
        "as_of": now,
    }
    values.update(updates)
    return ProactivityRequest.model_validate(values)


def test_proactivity_is_blocked_without_permission(service: CompanionMemoryService) -> None:
    decision = service.proactivity(request(service, permission_granted=False))

    assert decision.should_reach_out is False
    assert "permission_missing" in decision.reasons
    assert decision.next_allowed_at is None


def test_quiet_mode_overrides_a_relevant_reason(service: CompanionMemoryService) -> None:
    decision = service.proactivity(request(service, quiet_mode=True))

    assert decision.should_reach_out is False
    assert "quiet_mode" in decision.reasons


def test_welcome_relevant_outreach_is_allowed(service: CompanionMemoryService) -> None:
    decision = service.proactivity(request(service))

    assert decision.should_reach_out is True
    assert decision.reasons == ["welcome_and_relevant"]
