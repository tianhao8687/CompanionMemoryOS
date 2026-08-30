from __future__ import annotations

import json

from companion_memoryos.schemas import EventRecallItem, RecallItem

PROMPT_SECTION_ORDER = (
    "boundaries",
    "relationship",
    "profile",
    "support",
    "continuity",
    "emotional_context",
    "shared_history",
    "wellbeing",
)


def render_prompt(
    guidance: list[str],
    sections: dict[str, list[RecallItem]],
    events: list[EventRecallItem],
) -> str:
    lines = ["[response_guidance]"]
    lines.extend(f"- {entry}" for entry in guidance)
    for section in PROMPT_SECTION_ORDER:
        items = sections.get(section, [])
        if not items:
            continue
        lines.append(f"[{section}]")
        lines.extend(_render_memory(item) for item in items)
    if events:
        lines.append("[episodic_fallback]")
        lines.extend(_render_event(item) for item in events)
    return "\n".join(lines)


def _render_memory(item: RecallItem) -> str:
    memory = item.memory
    entities = ", ".join(entity.name for entity in memory.entities)
    entity_suffix = f" | entities={entities}" if entities else ""
    payload = json.dumps(
        {"title": memory.title, "content": memory.content},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return (
        f"- [{item.use_mode.value} | {memory.kind.value} | {memory.event_at.isoformat()}"
        f"{entity_suffix}] {payload}"
    )


def _render_event(item: EventRecallItem) -> str:
    event = item.event
    payload = json.dumps(
        {"content": event.content},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return (
        f"- [{item.use_mode.value} | {event.role.value} | {event.occurred_at.isoformat()}] "
        f"{payload}"
    )
