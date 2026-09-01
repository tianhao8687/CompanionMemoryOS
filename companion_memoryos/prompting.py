from __future__ import annotations

import json

from companion_memoryos.schemas import (
    EventRecallItem,
    RecallItem,
    StateQueryResult,
    TemporalAnchorRecord,
    TurnRecallItem,
)

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
    temporal_anchor: TemporalAnchorRecord | None = None,
    turns: list[TurnRecallItem] | None = None,
    state_result: StateQueryResult | None = None,
) -> str:
    lines = ["[response_guidance]"]
    lines.extend(f"- {entry}" for entry in guidance)
    if temporal_anchor is not None:
        lines.append("[resolved_time_anchor]")
        lines.append(
            json.dumps(
                {
                    "name": temporal_anchor.name,
                    "start_at": temporal_anchor.start_at.isoformat(),
                    "end_at": temporal_anchor.end_at.isoformat(),
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
    if state_result is not None:
        lines.append("[state_evidence]")
        lines.append(
            json.dumps(
                {
                    "predicate": state_result.query.predicate,
                    "semantics": state_result.query.semantics.value,
                    "resolution": state_result.resolution_status.value,
                    "values": [
                        {
                            "content": memory.content,
                            "epistemic_kind": memory.epistemic_kind.value,
                            "resolution": memory.resolution_status.value,
                            "reality_layer": memory.reality_layer.value,
                            "source_actor": memory.source_actor.value,
                            "quote_depth": memory.quote_depth,
                            "elicitation": memory.elicitation_kind.value,
                            "valid_time_start": memory.valid_time_start.isoformat(),
                            "valid_time_end": (
                                memory.valid_time_end.isoformat()
                                if memory.valid_time_end is not None
                                else None
                            ),
                            "known_from": memory.valid_from.isoformat(),
                        }
                        for memory in state_result.memories
                    ],
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
    for section in PROMPT_SECTION_ORDER:
        items = sections.get(section, [])
        if not items:
            continue
        lines.append(f"[{section}]")
        lines.extend(_render_memory(item) for item in items)
    if events:
        lines.append("[episodic_fallback]")
        lines.extend(_render_event(item) for item in events)
    if turns:
        lines.append("[raw_turn_evidence]")
        lines.extend(_render_turn(item) for item in turns)
    return "\n".join(lines)


def _render_memory(item: RecallItem) -> str:
    memory = item.memory
    payload = json.dumps(
        {
            "title": memory.title,
            "content": memory.content,
            # Entity names and aliases are user-controlled evidence too. Keep
            # them inside the JSON data payload so they cannot forge a prompt
            # section or metadata header.
            "entities": [
                {
                    "id": entity.id,
                    "kind": entity.kind,
                    "name": entity.name,
                    "aliases": entity.aliases,
                }
                for entity in memory.entities
            ],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return (
        f"- [{item.use_mode.value} | {memory.kind.value} | {memory.epistemic_kind.value}"
        f" | {memory.resolution_status.value} | {memory.reality_layer.value}"
        f" | actor={memory.source_actor.value} | quote_depth={memory.quote_depth}"
        f" | elicitation={memory.elicitation_kind.value}"
        f" | {memory.event_at.isoformat()}"
        f"] {payload}"
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


def _render_turn(item: TurnRecallItem) -> str:
    turn = item.turn
    evidence: dict[str, object] = {
        "actor_id": turn.actor_id,
        "content": item.evidence_text,
    }
    if item.evidence_text == turn.content:
        evidence["speech_spans"] = [
            {
                "start": span.start_offset,
                "end": span.end_offset,
                "quote_depth": span.quote_depth,
                "speaker": span.attributed_speaker_id,
                "target": span.target_actor_id,
                "reality_layer": span.reality_layer.value,
                "speech_act": span.speech_act.value,
                "machine_generated": span.machine_generated,
                "confidence": span.confidence,
            }
            for span in turn.speech_spans
        ]
    else:
        evidence["non_direct_spans_excluded"] = True
    payload = json.dumps(
        evidence,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return (
        f"- [{item.use_mode.value} | {turn.role.value} | {turn.occurred_at.isoformat()}] {payload}"
    )
