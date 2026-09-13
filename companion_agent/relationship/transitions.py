"""Explainable, bidirectional stage policy based on several independent dimensions."""

from __future__ import annotations

from datetime import datetime, timedelta

from companion_agent.persona.models import RelationshipStage
from companion_agent.relationship.models import (
    RelationshipConfig,
    RelationshipModel,
    RelationshipPatternStatus,
    RelationshipStageState,
)

STAGES = [RelationshipStage.NEW, RelationshipStage.FAMILIAR, RelationshipStage.CLOSE]


def evaluate_transition(
    model: RelationshipModel,
    config: RelationshipConfig,
    as_of: datetime,
) -> RelationshipStageState:
    if as_of.tzinfo is None:
        raise ValueError("stage evaluation requires an aware timestamp")
    current = model.stage
    target = current
    reasons: list[str] = []
    evidence: list[str] = []
    patterns = [p for p in model.patterns if p.status is RelationshipPatternStatus.ESTABLISHED]
    milestones = [
        m
        for m in model.milestones
        if m.status.value == "active" and m.importance >= config.milestone_min_importance
    ]
    interactions = {ref: at for ref, at in model.interactions.items() if at <= as_of}
    days = len({at.date() for at in interactions.values()})
    recent_days = len(
        {
            at.date()
            for at in interactions.values()
            if as_of - at <= timedelta(days=config.continuity_window_days)
        }
    )
    elapsed = (as_of - model.started_at).total_seconds() / 86400
    last = max(interactions.values(), default=None)
    inactive = last is not None and as_of - last >= timedelta(days=config.inactivity_days)
    recent_conflict = (
        bool(model.recent_dynamics.evidence_ids)
        and timedelta(0)
        <= as_of - model.recent_dynamics.updated_at
        <= timedelta(days=config.dynamics_days)
        and model.recent_dynamics.recent_conflict_level >= config.conflict_downgrade_level
    )
    if model.distance_ceiling is not None and STAGES.index(current) > STAGES.index(
        model.distance_ceiling
    ):
        target = model.distance_ceiling
        reasons = ["用户明确要求降低关系距离，优先遵守"]
        evidence = model.distance_evidence_ids
    elif current is RelationshipStage.CLOSE and (inactive or recent_conflict):
        target = RelationshipStage.FAMILIAR
        reasons = ["长期未互动，暂时收敛亲密表达" if inactive else "近期明显冲突，暂时收敛亲密表达"]
        evidence = list(interactions) if inactive else model.recent_dynamics.evidence_ids
    elif not inactive and not recent_conflict:
        if (
            current is RelationshipStage.NEW
            and elapsed >= config.familiar_days
            and days >= config.familiar_active_days
            and len(patterns) >= config.familiar_patterns
            and len(milestones) >= config.familiar_milestones
        ):
            target = RelationshipStage.FAMILIAR
            reasons = [
                f"关系持续至少 {config.familiar_days} 天",
                f"在 {days} 个不同日期主动互动",
                "已形成稳定互动模式和多个共同里程碑",
            ]
        elif (
            current is RelationshipStage.FAMILIAR
            and elapsed >= config.close_days
            and days >= config.close_active_days
            and recent_days >= config.close_recent_active_days
            and len(patterns) >= config.close_patterns
            and len(milestones) >= config.close_milestones
            and model.identity.confirmed_by_user
            and bool(model.identity.labels)
        ):
            target = RelationshipStage.CLOSE
            reasons = ["长期、多日连续互动", "用户明确确认关系定义", "有稳定习惯与共同历史支持"]
        if target is not current:
            evidence = [*interactions, *model.identity.evidence_ids, *model.started_at_evidence_ids]
            evidence.extend(ref for p in patterns for ref in p.evidence_ids)
            evidence.extend(ref for m in milestones for ref in m.evidence_ids)
    if model.distance_ceiling is not None and STAGES.index(target) > STAGES.index(
        model.distance_ceiling
    ):
        target = model.distance_ceiling
    if target is current:
        return model.stage_state.model_copy(deep=True)
    return RelationshipStageState(
        stage=target, entered_at=as_of, reasons=reasons, evidence_ids=list(dict.fromkeys(evidence))
    )
