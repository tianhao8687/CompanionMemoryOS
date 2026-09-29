"""Literal conversational anchors, not inferred pronoun-to-person bindings."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from companion_agent.evidence_policy import filter_recent_turns, filter_superseded_context
from companion_agent.passages import evidence_window
from companion_agent.relationship.models import RelationshipKey
from companion_memoryos.schemas import (
    ConversationTurnRecord,
    DiscourseSignal,
    MemoryUsePlan,
    ProcessTurnRequest,
    ProcessTurnResult,
    RecallRequest,
)
from companion_memoryos.turn_layers import turn_reality_layer

if TYPE_CHECKING:
    from companion_agent.cognition import ApplicationMemory


def contextual_query(
    memory: ApplicationMemory,
    request: ProcessTurnRequest,
    result: ProcessTurnResult,
    recall: RecallRequest,
) -> tuple[str, list[str]]:
    turn = result.storage.turn
    if (
        turn is None
        or request.recall_request is not None
        or (result.discourse and DiscourseSignal.TOPIC_SWITCH in result.discourse.signals)
    ):
        return recall.query, []
    anchor_id = turn.reply_to_turn_id
    episode_id: str | None = None
    interpretation = result.interpretation
    if anchor_id is None and interpretation is not None:
        hint = interpretation.model_output.episode_hint
        current = memory.store.get_turn(turn.id, turn.user_id)
        if (
            hint is not None
            and hint.action == "attach"
            and hint.episode_id == interpretation.episode_id == current.episode_id
        ):
            anchor_id = hint.continuity_turn_id
            episode_id = hint.episode_id
    # Unresolved language stays with native chat history, not an inferred search binding.
    if anchor_id is None:
        return recall.query, []
    try:
        candidates: list[ConversationTurnRecord] = [memory.store.get_turn(anchor_id, turn.user_id)]
    except KeyError:
        return recall.query, []
    candidates = [
        item
        for item in candidates
        if item.scope == turn.scope
        and (episode_id is None or item.episode_id == episode_id)
        and item.server_sequence < turn.server_sequence
        and item.occurred_at <= turn.occurred_at
        and turn_reality_layer(
            item.content,
            json.dumps(item.metadata),
            json.dumps([span.model_dump(mode="json") for span in item.speech_spans]),
        )
        == request.reality_layer.value
    ]
    key = RelationshipKey(
        user_id=turn.user_id,
        companion_id=turn.scope.companion_id or "",
        relationship_id=turn.scope.relationship_id or "",
    )
    candidates = filter_superseded_context(
        memory,
        key,
        turn.scope,
        filter_recent_turns(memory, key, candidates, MemoryUsePlan(), recall.as_of),
    )
    if not candidates:
        return recall.query, []
    anchor = candidates[0]
    start, end = evidence_window(anchor.content, recall.query, memory.config)
    # Search context never replaces the actual user message or establishes a fact.
    query = recall.query[:3200] + "\n" + anchor.content[start:end]
    return query[:4000], [anchor.id]
