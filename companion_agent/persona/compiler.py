from __future__ import annotations

import json

from companion_agent.persona.models import (
    CompiledPersonaContext,
    PersonaDefinition,
    RelationshipStage,
)
from companion_agent.persona.tokens import (
    DEFAULT_MAX_PERSONA_TOKENS,
    PersonaBudgetError,
    default_token_counter,
)
from companion_memoryos.schemas import ResponseGoal
from companion_memoryos.tokens import TokenCounter


def compile_persona_context(
    persona: PersonaDefinition,
    response_goal: ResponseGoal,
    relationship_stage: RelationshipStage,
    *,
    max_persona_tokens: int = DEFAULT_MAX_PERSONA_TOKENS,
    token_counter: TokenCounter | None = None,
    max_examples: int = 2,
) -> CompiledPersonaContext:
    if max_persona_tokens < 1 or max_examples < 0:
        raise ValueError("invalid persona budget or example limit")
    goal = ResponseGoal(response_goal)
    stage = RelationshipStage(relationship_stage)
    counter = token_counter or default_token_counter()

    # Every kernel statement, invariant, and current style survives compression.
    # Remove exact duplicate prose structurally; never slice a rule mid-sentence.
    def unique(values: list[str]) -> str:
        return "；".join(dict.fromkeys(values))

    lines = [f"Identity: {persona.display_name}；{persona.identity.role}", "Character Kernel:"]
    for key, values in persona.kernel.model_dump().items():
        lines.append(f"{key}: {unique(values)}")
    lines.append(f"Response Goal: {goal.value}")
    for key, values in persona.response_styles[goal].model_dump().items():
        lines.append(f"{key}: {unique(values)}")
    lines.append(f"Relationship Stage: {stage.value}")
    for key, values in persona.relationship_styles[stage].model_dump().items():
        lines.append(f"{key}: {unique(values)}")
    lines.append("Behavioral Invariants:")
    lines.extend(f"{rule.severity}/{rule.id}: {rule.description}" for rule in persona.invariants)
    text = "\n".join(lines)
    if counter.count(text) > max_persona_tokens:
        raise PersonaBudgetError("mandatory persona exceeds max_persona_tokens; edit the source")
    omitted: list[str] = []
    summary = f"\nIdentity summary: {persona.identity.summary}"
    if counter.count(text + summary) <= max_persona_tokens:
        text += summary
    else:
        omitted.append("identity.summary")
    ranked: list[tuple[int, int]] = []
    for index, example in enumerate(persona.examples):
        tags = {tag.lower() for tag in example.tags}
        stage_tags = tags & {item.value for item in RelationshipStage}
        if goal.value in tags and (not stage_tags or stage.value in stage_tags):
            ranked.append((-(2 + int(stage.value in tags)), index))
    selected: list[int] = []
    for _, index in sorted(ranked):
        example = persona.examples[index]
        addition = (
            "\nExample (fictional style demonstration, not conversation evidence): "
            + json.dumps(
                example.model_dump(exclude={"tags"}), ensure_ascii=False, separators=(",", ":")
            )
        )
        if len(selected) < max_examples and counter.count(text + addition) <= max_persona_tokens:
            text += addition
            selected.append(index)
    omitted.extend(f"examples.{i}" for i in range(len(persona.examples)) if i not in selected)
    return CompiledPersonaContext(
        persona_id=persona.persona_id,
        persona_version=persona.version,
        text=text,
        estimated_tokens=counter.count(text),
        response_goal=goal,
        relationship_stage=stage,
        omitted_items=omitted,
        selected_example_indices=selected,
    )
