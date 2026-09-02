from __future__ import annotations

from typing import TYPE_CHECKING

from companion_memoryos.schemas import (
    EpistemicKind,
    EvidenceActor,
    MemoryInput,
    MemoryKind,
    MemoryRecord,
    MemoryScope,
    MemoryStatus,
    ProfileSnapshot,
    RealityLayer,
    ResolutionStatus,
    StateQuery,
    StateQueryResult,
)
from companion_memoryos.service_rules import WEAK_ELICITATION_KINDS

if TYPE_CHECKING:
    from companion_memoryos.service import CompanionMemoryService


def profile(
    self: CompanionMemoryService, user_id: str, scope: MemoryScope | None = None
) -> ProfileSnapshot:
    active = self.store.list_memories(user_id, {MemoryStatus.ACTIVE}, scope=scope or MemoryScope())
    active = [memory for memory in active if memory.subject_actor_id in {None, user_id}]
    return ProfileSnapshot(
        user_id=user_id,
        identity=self._of_kind(active, MemoryKind.IDENTITY),
        preferences=self._of_kind(active, MemoryKind.PREFERENCE),
        boundaries=self._of_kind(active, MemoryKind.BOUNDARY),
        support_strategies=self._of_kind(active, MemoryKind.SUPPORT_STRATEGY),
        rituals=self._of_kind(active, MemoryKind.RITUAL),
        relationships=self._of_kind(active, MemoryKind.RELATIONSHIP),
        pending_review_count=self.store.pending_count(user_id),
    )


def query_state(self: CompanionMemoryService, query: StateQuery) -> StateQueryResult:
    return self.store.query_state(query)


def _of_kind(memories: list[MemoryRecord], kind: MemoryKind) -> list[MemoryRecord]:
    return [memory for memory in memories if memory.kind is kind]


def _is_direct_user_evidence(item: MemoryInput) -> bool:
    return (
        item.source_actor is EvidenceActor.AUTHENTICATED_USER
        and item.quote_depth == 0
        and (item.reality_layer not in {RealityLayer.QUOTE, RealityLayer.FICTION})
    )


def _enforce_epistemic_eligibility(
    self: CompanionMemoryService, item: MemoryInput
) -> tuple[MemoryInput, list[str]]:
    state_kinds = {EpistemicKind.DIRECT_SELF_REPORT, EpistemicKind.RELATIONSHIP_CONTRACT}
    if item.epistemic_kind not in state_kinds:
        return (item, [])
    directly_attributed = self._is_direct_user_evidence(item)
    if item.epistemic_kind is EpistemicKind.DIRECT_SELF_REPORT and item.subject_actor_id not in {
        None,
        item.user_id,
    }:
        directly_attributed = False
    if not directly_attributed and self.config.epistemic.ineligible_self_report_becomes_observation:
        return (
            item.model_copy(
                update={
                    "epistemic_kind": EpistemicKind.OBSERVATION,
                    "resolution_status": ResolutionStatus.CONTESTED,
                    "explicit_user_request": False,
                }
            ),
            ["ineligible_self_report_downgraded_to_observation"],
        )
    if (
        item.elicitation_kind in WEAK_ELICITATION_KINDS
        and self.config.epistemic.weak_confirmation_requires_review
    ):
        return (
            item.model_copy(
                update={
                    "resolution_status": ResolutionStatus.CONTESTED,
                    "explicit_user_request": False,
                }
            ),
            ["weak_confirmation_requires_review"],
        )
    return (item, ["qualified_direct_state_evidence"])
