"""Erase a requested location without deleting independent dialogue in its lineage."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from companion_memoryos.schemas import (
    ConversationRole,
    ConversationTurnRecord,
    MemoryStatus,
    TurnDeletionState,
)

if TYPE_CHECKING:
    from companion_agent.cognition import ApplicationMemory


CLAUSE = re.compile(r"[^，,。！？!?；;\n]+[，,。！？!?；;\n]*")
POSITION = re.compile(
    r"(?:放|搁|收|藏|塞|装|夹|存|挪|搬|移)(?:在|进|到)(?:了)?|位置(?:是|在|：|:)|"
    r"在(?=.{1,40}(?:里|内|层|边|旁|下|上|柜|架|抽屉|袋|套|箱|盒))"
)
SPATIAL = re.compile(r"位置|里|内|层|旁|边|下|上|柜|架|抽屉|袋|套|箱")
ANAPHORA = re.compile(r"^(?:它|那(?:个|只|件|里)|这个|这里|就|还|仍)|老地方|原处")


def normalize_place(text: str) -> str:
    text = re.sub(r"最?(?:底层|底下|下面|下层)", "底部", text)
    text = re.sub(r"最?(?:顶层|顶上|上面|上层)", "顶部", text)
    text = re.sub(r"(?:铁皮柜|铁柜|储物柜|柜子)", "柜", text)
    return text.replace("的", "")


def place_fragments(place: str) -> set[str]:
    normalized = normalize_place(place)
    fragments = {normalized, normalized.rstrip("里面内")}
    for match in re.finditer(
        r"(?:柜|抽屉|书架|书桌|帆布袋|雨伞套|床|沙发)(?:底部|顶部|里|旁|下|上|内)", normalized
    ):
        fragments.add(match.group())
        # A reply may name just the container ("帆布袋先别倒出来")
        # without repeating its colour or "inside". That still reveals it.
        container = re.sub(r"(?:底部|顶部|里|旁|下|上|内)$", "", match.group())
        if len(container) >= 2:
            fragments.add(container)
    return {fragment for fragment in fragments if len(fragment) >= 2}


def location_ranges(
    text: str, target: str, *, places: set[str] | None = None, dependent: bool = False
) -> list[tuple[int, int]]:
    """Select clauses, never rewrite retained words or guess a replacement fact.

    Dependent replies can omit the noun; exact place fragments and spatial
    anaphora cover those references. An unrelated named object's location is
    not erased just because it shares the same conversation.
    """
    output: list[tuple[int, int]] = []
    previous_target = False
    for part in CLAUSE.finditer(text):
        clause = part.group()
        names_target = target in clause
        position = POSITION.search(clause)
        refers_to_place = any(place in normalize_place(clause) for place in places or set())
        anaphoric = bool(ANAPHORA.search(clause.strip(' "“「『*')))
        if (
            (names_target and position)
            or (
                previous_target
                and position
                and (anaphoric or not clause[: position.start()].strip())
            )
            or (dependent and refers_to_place)
            or (dependent and anaphoric and (position or SPATIAL.search(clause)))
        ):
            output.append((part.start(), part.end()))
        previous_target = names_target or (previous_target and anaphoric)
    return output


def forget_location(memory: ApplicationMemory, request: ConversationTurnRecord, target: str) -> int:
    turns = [
        item
        for item in memory.store.list_turns(request.user_id)
        if item.scope.companion_id == request.scope.companion_id
        and item.scope.relationship_id == request.scope.relationship_id
        and item.scope.group_id == request.scope.group_id
        and item.server_sequence < request.server_sequence
        and item.deletion_state is TurnDeletionState.ACTIVE
    ]
    source_ranges: dict[str, list[tuple[int, int]]] = {}
    places: set[str] = set()
    for turn in turns:
        if turn.role is not ConversationRole.USER:
            continue
        spans = location_ranges(memory._direct_user_discourse_text(turn), target)
        # Offsets belong to the original stored text, including quotation labels.
        if not spans:
            continue
        spans = location_ranges(turn.content, target)
        source_ranges[turn.id] = spans
        for start, end in spans:
            clause = turn.content[start:end].strip("，,。！？!?；;\n ")
            match = POSITION.search(clause)
            if match:
                place = clause[match.end() :].strip(' 的了“”「」"')
                if len(place) >= 2:
                    places.update(place_fragments(place))
    cards = {
        record.id: record
        for record in memory.store.list_memories(request.user_id)
        if record.scope.companion_id == request.scope.companion_id
        and record.scope.relationship_id == request.scope.relationship_id
        and record.scope.group_id == request.scope.group_id
        and record.status in {MemoryStatus.ACTIVE, MemoryStatus.CANDIDATE, MemoryStatus.SUPERSEDED}
        and (
            set(record.evidence_turn_ids).intersection(source_ranges)
            or location_ranges(record.content, target)
        )
    }
    plans = {
        plan.trigger_turn_id: plan for plan in memory.store.list_response_plans(request.user_id)
    }

    lineage = set(source_ranges)
    selected = dict(source_ranges)
    for turn in sorted(turns, key=lambda item: item.server_sequence):
        if turn.role is not ConversationRole.ASSISTANT:
            continue
        plan = plans.get(turn.reply_to_turn_id or "")
        recalled = bool(
            plan
            and any(
                decision.mode.value not in {"suppress", "clarify"}
                and (
                    (decision.evidence.kind.value == "turn" and decision.evidence.id in lineage)
                    or (decision.evidence.kind.value == "memory" and decision.evidence.id in cards)
                )
                for decision in plan.memory_use_plan.decisions
            )
        )
        if (
            recalled
            or turn.reply_to_turn_id in lineage
            or lineage.intersection(turn.metadata.get("context_turn_ids", []))
        ):
            lineage.add(turn.id)
            spans = location_ranges(turn.content, target, places=places, dependent=True)
            if spans:
                selected[turn.id] = spans

    # One transaction: a retrieval must never see clean sources with old derived
    # summaries or an old vector. Do not use exported transcripts as new evidence.
    with memory.store.database.atomic():
        for identifier, spans in selected.items():
            memory.store.redact_turn(identifier, request.user_id, spans)
        # A card can predate source linking. Only location-bearing cards qualify;
        # mentioning the same object alone is not a deletion target.
        forgotten_cards = 0
        for record in cards.values():
            if location_ranges(record.content, target, places=places, dependent=True):
                memory.store.forget(record.id, request.user_id)
                forgotten_cards += 1
    if memory.on_memory_changed:
        memory.on_memory_changed()
    return len(selected) + forgotten_cards
