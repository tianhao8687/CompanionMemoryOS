"""Historical familiarity and present expression distance are independent."""

from __future__ import annotations

from datetime import datetime, timedelta

from companion_agent.persona.models import RelationshipStage
from companion_agent.relationship.models import (
    RelationshipConfig,
    RelationshipModel,
    RelationshipPatternStatus,
    RelationshipStageState,
)
from companion_agent.semantics import RelationshipDistance

STAGES = [RelationshipStage.NEW, RelationshipStage.FAMILIAR, RelationshipStage.ESTABLISHED]


def evaluate_distance(
    model: RelationshipModel, config: RelationshipConfig, as_of: datetime
) -> RelationshipDistance:
    if model.distance_ceiling is RelationshipStage.NEW:
        return RelationshipDistance.RESERVED
    dynamics = model.recent_dynamics
    if (
        dynamics.evidence_ids
        and timedelta(0) <= as_of - dynamics.updated_at <= timedelta(days=config.dynamics_days)
        and dynamics.recent_conflict_level >= config.conflict_downgrade_level
    ):
        return RelationshipDistance.RESERVED
    if model.distance_ceiling is RelationshipStage.FAMILIAR or (
        model.last_interaction_at is not None
        and as_of - model.last_interaction_at >= timedelta(days=config.inactivity_days)
    ):
        return RelationshipDistance.CAUTIOUS
    return RelationshipDistance.OPEN


def evaluate_transition(
    model: RelationshipModel, config: RelationshipConfig, as_of: datetime
) -> RelationshipStageState:
    if as_of.tzinfo is None:
        raise ValueError("stage evaluation requires an aware timestamp")
    interactions = {ref: at for ref, at in model.interactions.items() if at <= as_of}
    dates = {at.date() for at in interactions.values()}
    elapsed = (max(interactions.values()) - min(interactions.values())).days if interactions else 0
    patterns = [p for p in model.patterns if p.status is RelationshipPatternStatus.ESTABLISHED]
    milestones = [
        m
        for m in model.milestones
        if m.status.value == "active" and m.importance >= config.milestone_min_importance
    ]
    experiences = {ref: at for ref, at in model.shared_experiences.items() if at <= as_of}
    familiar_support = (
        bool(patterns) or len(experiences) >= config.familiar_experiences or bool(milestones)
    )
    established_support = (
        len(patterns) >= config.close_patterns
        or len(experiences) >= config.established_experiences
        or len(milestones) >= config.close_milestones
    )
    target = model.stage
    reasons: list[str] = []
    if (
        model.stage is RelationshipStage.NEW
        and elapsed >= config.familiar_days
        and len(dates) >= config.familiar_active_days
        and familiar_support
    ):
        target = RelationshipStage.FAMILIAR
        reasons = [
            f"实际互动跨度 {elapsed} 天，覆盖 {len(dates)} 个日期",
            "稳定模式、共同经历或里程碑提供熟悉感证据；不要求特定关系身份",
        ]
    elif (
        model.stage is RelationshipStage.FAMILIAR
        and elapsed >= config.close_days
        and len(dates) >= config.close_active_days
        and established_support
    ):
        target = RelationshipStage.ESTABLISHED
        reasons = ["长期多日互动与稳定共同历史支持", "关系身份和当前表达距离不参与历史深度门控"]
    if target is model.stage:
        return model.stage_state.model_copy(deep=True)
    refs = [*interactions, *experiences]
    refs.extend(ref for p in patterns for ref in p.evidence_ids)
    refs.extend(ref for m in milestones for ref in m.evidence_ids)
    return RelationshipStageState(
        stage=target, entered_at=as_of, reasons=reasons, evidence_ids=list(dict.fromkeys(refs))
    )
