from __future__ import annotations

import json

from companion_agent.current_state.models import CompiledCurrentState, StateKind, StatePreparation
from companion_agent.relationship import RelationshipKey
from companion_memoryos.schemas import ResponseGoal
from companion_memoryos.tokens import TokenCounter


def compile_current_state(
    key: RelationshipKey,
    preparation: StatePreparation,
    goal: ResponseGoal,
    counter: TokenCounter,
    *,
    max_tokens: int = 450,
) -> CompiledCurrentState:
    payload: dict[str, object] = {
        "response_goal": goal.value,
        "influence": [],
        "rules": (
            "仅在有效范围内无声影响；当前明确任务和纠正优先。"
            "未列出或过期不代表恢复、解决或撤销边界。不要播报状态标签。"
        ),
    }
    if preparation.interaction_guidance:
        payload["interaction_guidance"] = preparation.interaction_guidance
    chosen = []
    entries: list[dict[str, object]] = []
    hold = any(record.slot == "style:reference" for record in preparation.records)
    for record in sorted(
        preparation.records,
        key=lambda item: (
            {StateKind.STYLE: 0, StateKind.COMMUNICATION: 1, StateKind.CONDITION: 2}[item.kind],
            item.slot,
        ),
    ):
        if record.kind is StateKind.CONDITION and (
            hold
            or (
                preparation.analysis.concrete_task
                and record.topic not in preparation.analysis.topics
            )
        ):
            continue
        if (
            record.kind is StateKind.CONDITION
            and record.topic
            and preparation.analysis.topics
            and record.topic not in preparation.analysis.topics
        ):
            continue
        if record.kind is StateKind.COMMUNICATION and record.value != goal.value:
            continue
        entry: dict[str, object] = {
            "kind": record.kind.value,
            "slot": record.slot,
            "value": record.value,
            "topic": record.topic,
            "valid_until": record.expires_at.isoformat(),
        }
        if record.slot == "style:reference":
            entry["guidance"] = "暂停主动提起旧事，不据此判断事情已解决，也不为建档追问。"
        payload["influence"] = [*entries, entry]
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if counter.count(text) <= max_tokens:
            entries.append(entry)
            chosen.append(record)
    payload["influence"] = entries
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if counter.count(text) > max_tokens:
        raise ValueError("current state budget is too small")
    return CompiledCurrentState(
        **key.model_dump(),
        effective_goal=goal,
        text=text,
        estimated_tokens=counter.count(text),
        state_ids=[r.state_id for r in chosen],
        source_turn_ids=[r.source_turn_id for r in chosen],
        degraded=preparation.degraded,
    )
