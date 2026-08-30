from __future__ import annotations

from datetime import timedelta

from companion_memoryos.config import CompanionConfig
from companion_memoryos.schemas import ProactivityDecision, ProactivityRequest


def decide_proactivity(
    request: ProactivityRequest,
    config: CompanionConfig,
) -> ProactivityDecision:
    settings = config.proactivity
    reasons: list[str] = []
    requires_state_change = False
    permission = (
        settings.enabled_by_default
        if request.permission_granted is None
        else request.permission_granted
    )
    if not permission:
        reasons.append("permission_missing")
        requires_state_change = True
    if request.quiet_mode:
        reasons.append("quiet_mode")
        requires_state_change = True

    idle_until = request.last_user_message_at + timedelta(minutes=settings.minimum_idle_minutes)
    if request.as_of < idle_until:
        reasons.append("minimum_idle_not_reached")

    cooldown_until = None
    if request.last_outreach_at is not None:
        cooldown_until = request.last_outreach_at + timedelta(minutes=settings.cooldown_minutes)
        if request.as_of < cooldown_until:
            reasons.append("cooldown_active")

    if request.outreaches_today >= settings.maximum_outreaches_per_day:
        reasons.append("daily_limit_reached")
        requires_state_change = True
    if settings.require_relevant_reason and not request.has_relevant_reason:
        reasons.append("no_relevant_reason")
        requires_state_change = True

    negative_until = None
    if request.recent_negative_signal_at is not None:
        negative_until = request.recent_negative_signal_at + timedelta(
            hours=settings.negative_signal_quiet_hours
        )
        if request.as_of < negative_until:
            reasons.append("negative_signal_quiet_period")

    next_allowed_candidates = [idle_until]
    if cooldown_until is not None:
        next_allowed_candidates.append(cooldown_until)
    if negative_until is not None:
        next_allowed_candidates.append(negative_until)
    next_allowed_at = None if requires_state_change else max(next_allowed_candidates)
    should_reach_out = not reasons
    return ProactivityDecision(
        should_reach_out=should_reach_out,
        reasons=reasons or ["welcome_and_relevant"],
        next_allowed_at=None if should_reach_out else next_allowed_at,
    )
