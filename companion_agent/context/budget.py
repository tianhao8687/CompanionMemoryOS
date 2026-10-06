"""Budget selection for conversation; never changes stored memories or permissions."""

from companion_memoryos.prompting import render_prompt
from companion_memoryos.schemas import (
    CompanionContext,
    ConversationRole,
    ConversationTurnRecord,
    ExperienceEvidenceKind,
    MemoryReferenceMode,
    MemoryUsePlan,
    RecallUseMode,
    RetrievalAction,
    RetrievalOutcome,
)
from companion_memoryos.tokens import TokenCounter

BACKGROUND_MODES = {
    MemoryReferenceMode.SOURCE_CONTEXT,
    MemoryReferenceMode.SILENT_INFLUENCE,
    MemoryReferenceMode.SOFT_REFERENCE,
}


def prune_background_evidence(
    context: CompanionContext | None,
    plan: MemoryUsePlan,
    protected_sources: set[str],
    token_counter: TokenCounter,
) -> tuple[CompanionContext, str] | None:
    if context is None:
        return None
    modes = {(item.evidence.kind, item.evidence.id): item.mode for item in plan.decisions}
    state_ids = (
        {item.id for item in context.state_result.memories} if context.state_result else set()
    )
    candidates: list[tuple[float, ExperienceEvidenceKind, str]] = []
    for items in context.sections.values():
        for item in items:
            if (
                not item.pinned
                and item.memory.id not in state_ids
                and not protected_sources.intersection(item.memory.evidence_turn_ids)
                and f"memory:{item.memory.id}" not in protected_sources
                and modes.get((ExperienceEvidenceKind.MEMORY, item.memory.id)) in BACKGROUND_MODES
            ):
                candidates.append((item.score.total, ExperienceEvidenceKind.MEMORY, item.memory.id))
    for event in context.event_fallback:
        if (
            f"event:{event.event.id}" not in protected_sources
            and modes.get((ExperienceEvidenceKind.EVENT, event.event.id)) in BACKGROUND_MODES
        ):
            candidates.append((event.total, ExperienceEvidenceKind.EVENT, event.event.id))
    for turn in context.turn_fallback:
        if (
            turn.turn.id not in protected_sources
            and f"turn:{turn.turn.id}" not in protected_sources
            and modes.get((ExperienceEvidenceKind.TURN, turn.turn.id)) in BACKGROUND_MODES
        ):
            candidates.append((turn.total, ExperienceEvidenceKind.TURN, turn.turn.id))
    if not candidates:
        return None
    _, kind, identifier = min(candidates)
    selected = context.model_copy(deep=True)
    if kind is ExperienceEvidenceKind.MEMORY:
        selected.sections = {
            section: [item for item in items if item.memory.id != identifier]
            for section, items in selected.sections.items()
        }
        selected.memory_use_summaries = [
            item for item in selected.memory_use_summaries if item.memory_id != identifier
        ]
    elif kind is ExperienceEvidenceKind.EVENT:
        selected.event_fallback = [
            item for item in selected.event_fallback if item.event.id != identifier
        ]
    else:
        selected.turn_fallback = [
            item for item in selected.turn_fallback if item.turn.id != identifier
        ]
    answerable = (
        any(
            not item.pinned and item.use_mode is not RecallUseMode.DO_NOT_ASSERT
            for items in selected.sections.values()
            for item in items
        )
        or any(item.use_mode is not RecallUseMode.DO_NOT_ASSERT for item in selected.event_fallback)
        or any(item.use_mode is not RecallUseMode.DO_NOT_ASSERT for item in selected.turn_fallback)
    )
    if not answerable and selected.state_result is None:
        selected.retrieval_action = RetrievalAction.ABSTAIN
        selected.retrieval_outcome = RetrievalOutcome.NO_MATCH
    selected.budget_exhausted = True
    selected.budget_omitted_count += 1
    selected.prompt_text = render_prompt(
        selected.guidance,
        selected.sections,
        selected.event_fallback,
        selected.resolved_temporal_anchor,
        selected.turn_fallback,
        selected.state_result,
    )
    selected.rendered_characters = len(selected.prompt_text)
    selected.rendered_tokens = token_counter.count(selected.prompt_text)
    return selected, f"{kind.value}:{identifier}"


def trim_oldest_exchange(
    recent: list[ConversationTurnRecord],
    protected_ids: set[str],
    *,
    preserve_latest: bool = True,
) -> list[str]:
    """Remove a whole exchange; explicit quoted sources are always protected.

    Prefer preserving the latest exchange. The final fallback may evict it when
    it cannot fit alongside the current message even without optional evidence.
    Storage and source-addressed recall are unaffected by this request-only trim.
    """
    groups: list[list[ConversationTurnRecord]] = []
    for turn in recent:
        if not groups or turn.role is ConversationRole.USER:
            groups.append([])
        groups[-1].append(turn)
    for group in groups[:-1] if preserve_latest else groups:
        removed = {turn.id for turn in group}
        if removed.isdisjoint(protected_ids):
            recent[:] = [turn for turn in recent if turn.id not in removed]
            return [turn.id for turn in group]
    return []
