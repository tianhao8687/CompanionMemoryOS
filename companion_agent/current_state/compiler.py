from __future__ import annotations

import json

from companion_agent.current_state.models import CompiledCurrentState, StateKind, StatePreparation
from companion_agent.relationship import RelationshipKey
from companion_memoryos.schemas import ResponseGoal
from companion_memoryos.tokens import TokenCounter


class CurrentStateBudgetError(ValueError):
    """User requests cannot be silently removed to fit an optional context budget."""


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
        "goal_authority": "suggestion",
        "influence": [],
    }
    chosen = []
    entries: list[dict[str, object]] = []
    holds = [r for r in preparation.records if r.slot.startswith("style:reference")]
    for record in sorted(
        preparation.records,
        key=lambda item: (
            {StateKind.STYLE: 0, StateKind.COMMUNICATION: 1, StateKind.CONDITION: 2}[item.kind],
            item.slot,
        ),
    ):
        if record.kind is StateKind.CONDITION and (
            any(r.topic is None or r.topic == record.topic for r in holds)
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
        if (
            record.kind is StateKind.COMMUNICATION
            and record.value != goal.value
            and (
                preparation.analysis.concrete_task or preparation.analysis.explicit_goal is not None
            )
        ):
            continue
        entry: dict[str, object] = {
            "kind": record.kind.value,
            "slot": record.slot,
            "value": record.value,
            "topic": record.topic,
            "valid_until": record.expires_at.isoformat(),
            "authority": "self_report"
            if record.kind is StateKind.CONDITION
            else "explicit_request",
        }
        if record.slot.startswith("style:reference"):
            entry["guidance"] = "暂停主动提起此话题；不表示解决，其他话题不受此条影响。"
        payload["influence"] = [*entries, entry]
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if counter.count(text) <= max_tokens:
            entries.append(entry)
            chosen.append(record)
        elif record.kind is not StateKind.CONDITION:
            raise CurrentStateBudgetError("active user requests exceed current state budget")
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
        has_explicit_requests=any(record.kind is not StateKind.CONDITION for record in chosen),
    )
