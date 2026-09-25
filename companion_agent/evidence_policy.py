"""Carry source-conversation reference restrictions into derived relationship context."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from companion_agent.relationship.models import RelationshipKey
from companion_memoryos.experience import SUPPRESSING_FEEDBACK
from companion_memoryos.schemas import (
    ConsentState,
    ConversationTurnRecord,
    ExperienceEvidenceKind,
    ExperienceEvidenceRef,
    MemoryReferenceFeedbackRecord,
    MemoryReferenceMode,
    MemoryScope,
    MemoryStatus,
    MemoryUsePlan,
    Sensitivity,
    TurnDeletionState,
)
from companion_memoryos.service import CompanionMemoryService


def restricted_evidence(
    memory: CompanionMemoryService,
    key: RelationshipKey,
    refs: list[ExperienceEvidenceRef],
    as_of: datetime,
    *,
    conversation_id: str | None = None,
) -> set[str]:
    scopes = [
        MemoryScope(
            companion_id=key.companion_id,
            relationship_id=key.relationship_id,
            conversation_id=conversation_id,
        )
    ]
    for ref in refs:
        try:
            if ref.kind is ExperienceEvidenceKind.TURN:
                scope = memory.store.get_turn(ref.id, key.user_id).scope
            elif ref.kind is ExperienceEvidenceKind.MEMORY:
                scope = memory.store.get(ref.id, key.user_id).scope
            else:
                continue
            if (
                scope.companion_id == key.companion_id
                and scope.relationship_id == key.relationship_id
            ):
                scopes.append(scope)
        except KeyError:
            continue
    latest: dict[tuple[ExperienceEvidenceKind, str], MemoryReferenceFeedbackRecord] = {}
    for scope in {scope.model_dump_json(): scope for scope in scopes}.values():
        for target, feedback in memory.store.latest_reference_feedback(
            key.user_id, scope, refs, as_of
        ).items():
            previous = latest.get(target)
            if previous is None or feedback.recorded_at > previous.recorded_at:
                latest[target] = feedback
    return {
        f"{kind.value}:{identifier}"
        for (kind, identifier), feedback in latest.items()
        if feedback.kind in SUPPRESSING_FEEDBACK
    }


def filter_recent_turns(
    memory: CompanionMemoryService,
    key: RelationshipKey,
    turns: list[ConversationTurnRecord],
    plan: MemoryUsePlan,
    as_of: datetime,
    *,
    allow_sensitive: bool = False,
) -> list[ConversationTurnRecord]:
    """A hidden source must not reappear through its reply or a later derived reply."""
    records = {turn.id: turn for turn in turns}
    dependencies: dict[str, list[str]] = {}
    legacy_unavailable: set[str] = set()
    pending = list(records)
    while pending:
        identifier = pending.pop()
        turn = records[identifier]
        refs = turn.metadata.get("context_turn_ids", [])
        refs = [ref for ref in refs if isinstance(ref, str)] if isinstance(refs, list) else []
        # v0.4.0 recorded state ids. Recover only their already-audited source revision;
        # never re-interpret the conversation or guess a missing dependency.
        if "context_turn_ids" not in turn.metadata and turn.metadata.get("current_state_ids"):
            try:
                for state_id in turn.metadata["current_state_ids"]:
                    with memory.store.database.connection() as connection:
                        rows = connection.execute(
                            "SELECT data_json FROM agent_current_state_events WHERE "
                            "user_id=? AND companion_id=? AND relationship_id=? AND state_id=?",
                            (*key.values, state_id),
                        ).fetchall()
                    prior = [json.loads(row["data_json"]) for row in rows]
                    prior = [
                        r
                        for r in prior
                        if datetime.fromisoformat(r["observed_at"]) <= turn.occurred_at
                        and r["source_sequence"] < turn.server_sequence
                    ]
                    if not prior:
                        legacy_unavailable.add(identifier)
                    else:
                        latest = max(prior, key=lambda r: (r["observed_at"], r["source_sequence"]))
                        refs.append(latest["source_turn_id"])
            except (sqlite3.Error, ValueError, KeyError, TypeError):
                legacy_unavailable.add(identifier)
        deps = list(
            dict.fromkeys([*refs, *([turn.reply_to_turn_id] if turn.reply_to_turn_id else [])])
        )
        dependencies[identifier] = deps
        for ref in deps:
            if ref not in records:
                try:
                    records[ref] = memory.store.get_turn(ref, key.user_id)
                    pending.append(ref)
                except KeyError:
                    pass
    blocked = restricted_evidence(
        memory,
        key,
        [ExperienceEvidenceRef(kind=ExperienceEvidenceKind.TURN, id=ref) for ref in records],
        as_of,
    )
    blocked.update(
        f"turn:{d.evidence.id}"
        for d in plan.decisions
        if d.evidence.kind is ExperienceEvidenceKind.TURN
        and d.mode in {MemoryReferenceMode.SUPPRESS, MemoryReferenceMode.CLARIFY}
        and d.usage_scope == "all_context"
    )
    allowed: set[str] = set()
    for turn in sorted(records.values(), key=lambda t: t.server_sequence):
        if (
            turn.consent is ConsentState.GRANTED
            and turn.deletion_state is TurnDeletionState.ACTIVE
            and (allow_sensitive or turn.sensitivity is Sensitivity.NORMAL)
            and turn.occurred_at <= as_of
            and turn.scope.companion_id == key.companion_id
            and turn.scope.relationship_id == key.relationship_id
            and f"turn:{turn.id}" not in blocked
            and turn.id not in legacy_unavailable
            and all(ref in allowed for ref in dependencies[turn.id])
        ):
            allowed.add(turn.id)
    return [turn for turn in turns if turn.id in allowed]


def filter_superseded_context(
    memory: CompanionMemoryService,
    key: RelationshipKey,
    scope: MemoryScope,
    turns: list[ConversationTurnRecord],
) -> list[ConversationTurnRecord]:
    """For current answers, a superseded fact must not leak through its source/replies.

    This projection neither deletes historical facts nor creates permanent feedback.
    The caller can retain historical evidence for an explicit question about the past.
    """
    obsolete = memory.store.list_memories(key.user_id, {MemoryStatus.SUPERSEDED}, scope=scope)
    hidden = {source for record in obsolete for source in record.evidence_turn_ids}
    for turn in sorted(turns, key=lambda item: item.server_sequence):
        if turn.role.value == "assistant" and (
            turn.reply_to_turn_id in hidden
            or hidden.intersection(turn.metadata.get("context_turn_ids", []))
        ):
            hidden.add(turn.id)
    return [turn for turn in turns if turn.id not in hidden]
