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
from companion_agent.semantics import RelationshipDistance, RelationshipIdentityType
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
    relationship_identity: RelationshipIdentityType = RelationshipIdentityType.UNDEFINED,
    relationship_distance: RelationshipDistance = RelationshipDistance.OPEN,
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
    lines.append(f"Response Goal (suggestion, may blend): {goal.value}")
    lines.append(
        "以下表达风格是可调整的偏好；当前明确要求优先，可在完成任务时自然结合关心、分析或幽默。"
    )
    for key, values in persona.response_styles[goal].model_dump().items():
        lines.append(f"{key}: {unique(values)}")
    lines.append(f"Familiarity Stage: {stage.value}")
    for key, values in persona.relationship_styles[stage].model_dump().items():
        lines.append(f"{key}: {unique(values)}")
    lines.append(f"Relationship Identity: {relationship_identity.value}")
    identity_style = persona.identity_styles.get(relationship_identity)
    if identity_style is not None:
        for key, values in identity_style.model_dump().items():
            lines.append(f"identity_{key}: {unique(values)}")
    elif relationship_identity is RelationshipIdentityType.ROMANTIC_PARTNER:
        lines.append("已确认恋人身份：可以采用双方允许的情侣称呼和适度亲密；NEW不禁止恋爱表达。")
    lines.append("熟悉度只限制历史知识：不能因关系身份虚构相处时长、共同生活、习惯或内部梗。")
    lines.append(f"Current Relationship Distance: {relationship_distance.value}")
    if relationship_distance is not RelationshipDistance.OPEN:
        lines.append("当前收敛表达，尊重用户距离与边界；这不改变关系身份，也不抹掉共同历史。")
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
        tags = {"established" if tag.lower() == "close" else tag.lower() for tag in example.tags}
        stage_tags = tags & {item.value for item in RelationshipStage}
        ranked.append((-(2 * int(goal.value in tags) + int(stage.value in stage_tags)), index))
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
        relationship_identity=relationship_identity,
        relationship_distance=relationship_distance,
        omitted_items=omitted,
        selected_example_indices=selected,
    )
