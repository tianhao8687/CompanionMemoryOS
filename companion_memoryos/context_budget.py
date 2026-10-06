"""Pack already authorized, ranked evidence without another search or storage write."""

from companion_memoryos.prompting import render_prompt
from companion_memoryos.schemas import (
    AnswerSemantics,
    CompanionContext,
    RecallUseMode,
    RetrievalAction,
)
from companion_memoryos.tokens import TokenCounter


def fit_context_budget(
    context: CompanionContext,
    token_counter: TokenCounter,
    *,
    max_tokens: int | None = None,
    max_characters: int | None = None,
) -> CompanionContext:
    """Only shrink a candidate context; keep boundaries and report incomplete evidence.

    The caller retains the original candidates if it needs to try another allocation.
    A smaller allocation cannot restore a source omitted by retrieval or change its score,
    permissions, provenance or certainty. State answers remain all-or-abstain.
    """
    selected = context.model_copy(deep=True)
    selected.token_budget = min(
        context.token_budget, context.token_budget if max_tokens is None else max_tokens
    )
    selected.character_budget = min(
        context.character_budget,
        context.character_budget if max_characters is None else max_characters,
    )
    if selected.token_budget < 1 or selected.character_budget < 1:
        raise ValueError("context budgets must be positive")
    selected.sections = {
        section: [item for item in items if item.pinned]
        for section, items in context.sections.items()
        if any(item.pinned for item in items)
    }
    selected.event_fallback = []
    selected.turn_fallback = []
    if selected.state_result is not None:
        selected.state_result.memories = []

    def render() -> tuple[str, int]:
        prompt = render_prompt(
            selected.guidance,
            selected.sections,
            selected.event_fallback,
            selected.resolved_temporal_anchor,
            selected.turn_fallback,
            selected.state_result,
        )
        return prompt, token_counter.count(prompt)

    selected.prompt_text, selected.rendered_tokens = render()
    selected.safety_budget_exceeded = (
        selected.rendered_tokens > selected.token_budget
        or len(selected.prompt_text) > selected.character_budget
    )
    selected.budget_exhausted |= selected.safety_budget_exceeded

    def admit() -> bool:
        prompt, tokens = render()
        if tokens <= selected.token_budget and len(prompt) <= selected.character_budget:
            selected.prompt_text, selected.rendered_tokens = prompt, tokens
            return True
        selected.budget_exhausted = True
        selected.budget_omitted_count += 1
        return False

    if context.state_result is not None and selected.state_result is not None:
        for memory in context.state_result.memories:
            selected.state_result.memories.append(memory)
            if not admit():
                selected.state_result.memories.pop()
                selected.state_evidence_omitted_count += 1
    # Preserve the section priority and the ranked order within each section.
    ordinary = [
        (section, item)
        for section, items in context.sections.items()
        for item in items
        if not item.pinned
    ]
    for section, item in ordinary:
        selected.sections.setdefault(section, []).append(item)
        if not admit():
            selected.sections[section].pop()
            if not selected.sections[section]:
                del selected.sections[section]
    for event in context.event_fallback:
        selected.event_fallback.append(event)
        if not admit():
            selected.event_fallback.pop()
    for turn in context.turn_fallback:
        selected.turn_fallback.append(turn)
        if not admit():
            selected.turn_fallback.pop()
    selected.rendered_characters = len(selected.prompt_text)
    if selected.state_evidence_omitted_count:
        selected.retrieval_action = RetrievalAction.ABSTAIN
    if selected.retrieval_action in {RetrievalAction.ANSWER_SINGLE, RetrievalAction.ANSWER_MULTI}:
        if selected.state_result is not None:
            answerable = bool(selected.state_result.memories)
        else:
            answerable = any(
                item.use_mode is not RecallUseMode.DO_NOT_ASSERT for item in selected.turn_fallback
            )
            if selected.answer_semantics is not AnswerSemantics.UTTERANCE_HISTORY:
                answerable |= any(
                    not item.pinned and item.use_mode is not RecallUseMode.DO_NOT_ASSERT
                    for items in selected.sections.values()
                    for item in items
                ) or any(
                    item.use_mode is not RecallUseMode.DO_NOT_ASSERT
                    for item in selected.event_fallback
                )
        if not answerable:
            selected.retrieval_action = RetrievalAction.ABSTAIN
    included = {item.memory.id for items in selected.sections.values() for item in items}
    if selected.state_result is not None:
        included.update(item.id for item in selected.state_result.memories)
    selected.memory_use_summaries = [
        summary for summary in selected.memory_use_summaries if summary.memory_id in included
    ]
    return selected
