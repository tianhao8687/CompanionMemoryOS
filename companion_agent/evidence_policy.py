"""Carry source-conversation reference restrictions into derived relationship context."""

from __future__ import annotations

from datetime import datetime

from companion_agent.relationship.models import RelationshipKey
from companion_memoryos.experience import SUPPRESSING_FEEDBACK
from companion_memoryos.schemas import (
    ExperienceEvidenceKind,
    ExperienceEvidenceRef,
    MemoryReferenceFeedbackRecord,
    MemoryScope,
)
from companion_memoryos.service import CompanionMemoryService


def restricted_evidence(
    memory: CompanionMemoryService,
    key: RelationshipKey,
    refs: list[ExperienceEvidenceRef],
    as_of: datetime,
    *,
    conversation_id: str | None = None,
) -> set[str]:
    scopes = [
        MemoryScope(
            companion_id=key.companion_id,
            relationship_id=key.relationship_id,
            conversation_id=conversation_id,
        )
    ]
    for ref in refs:
        try:
            if ref.kind is ExperienceEvidenceKind.TURN:
                scope = memory.store.get_turn(ref.id, key.user_id).scope
            elif ref.kind is ExperienceEvidenceKind.MEMORY:
                scope = memory.store.get(ref.id, key.user_id).scope
            else:
                continue
            if (
                scope.companion_id == key.companion_id
                and scope.relationship_id == key.relationship_id
            ):
                scopes.append(scope)
        except KeyError:
            continue
    latest: dict[tuple[ExperienceEvidenceKind, str], MemoryReferenceFeedbackRecord] = {}
    for scope in {scope.model_dump_json(): scope for scope in scopes}.values():
        for target, feedback in memory.store.latest_reference_feedback(
            key.user_id, scope, refs, as_of
        ).items():
            previous = latest.get(target)
            if previous is None or feedback.recorded_at > previous.recorded_at:
                latest[target] = feedback
    return {
        f"{kind.value}:{identifier}"
        for (kind, identifier), feedback in latest.items()
        if feedback.kind in SUPPRESSING_FEEDBACK
    }
