"""Expose evidence authority and search incompleteness at the final model boundary."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from companion_memoryos.schemas import (
    CompanionContext,
    EpistemicKind,
    EvidenceActor,
    MemoryRecord,
    MemoryStatus,
    RealityLayer,
    ResolutionStatus,
)


def memory_authority(memory: MemoryRecord, as_of: datetime) -> str:
    if memory.quote_depth or memory.reality_layer is not RealityLayer.REAL_WORLD:
        return "attributed_material_not_user_fact"
    if memory.resolution_status is not ResolutionStatus.RESOLVED:
        return "unresolved_not_established"
    if memory.epistemic_kind not in {EpistemicKind.OBSERVATION, EpistemicKind.DIRECT_SELF_REPORT}:
        return "inference_or_belief_not_observation"
    if memory.source_actor is not EvidenceActor.AUTHENTICATED_USER:
        return "non_user_source_not_user_testimony"
    if (
        memory.status is not MemoryStatus.ACTIVE
        or memory.valid_time_start > as_of
        or (memory.valid_time_end is not None and memory.valid_time_end <= as_of)
        or (memory.expires_at is not None and memory.expires_at <= as_of)
    ):
        return "historical_not_current"
    return "applicable_user_observation"


def search_grounding(context: CompanionContext | None) -> dict[str, Any]:
    if context is None:
        return {"coverage": "not_searched", "missing_details": "unknown"}
    return {
        "coverage": "selected_evidence_not_complete_history",
        "missing_details": "unknown",
        "ambiguity_detected": context.ambiguity_detected,
        "budget_omitted_count": context.budget_omitted_count,
        "budget_exhausted": context.budget_exhausted,
        "state_evidence_omitted_count": context.state_evidence_omitted_count,
        "state_resolution": context.state_result.resolution_status.value
        if context.state_result
        else None,
        "integrity": context.integrity_manifest.model_dump(mode="json"),
        "query_context_turn_ids": context.query_context_turn_ids,
        "query_context_is_identity_resolution": False,
    }
