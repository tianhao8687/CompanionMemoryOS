"""Evidence-backed, exact alias resolution. No new database or automatic identity merges."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from companion_memoryos.schemas import (
    ConversationTurnRecord,
    EntityRef,
    EntityResolution,
    MemoryScope,
    RealityLayer,
    TurnInterpretation,
)
from companion_memoryos.store import MemoryStore, datetime_to_text


def entity_key(value: str) -> str:
    return value.strip().casefold()


def domain_filter(alias: str, scope: MemoryScope) -> tuple[str, list[Any]]:
    columns = ["companion_id", "relationship_id", "group_id"]
    if scope.relationship_id is None:
        columns.append("conversation_id")
    return (
        " AND ".join(f"{alias}.{column} IS ?" for column in columns),
        [getattr(scope, column) for column in columns],
    )


def entity_catalog(
    store: MemoryStore,
    user_id: str,
    scope: MemoryScope,
    reality_layer: RealityLayer,
    as_of: datetime,
    limit: int,
    *,
    names: list[str] | None = None,
    text: str | None = None,
    kind: str | None = None,
    allow_sensitive: bool = True,
) -> tuple[list[EntityRef], bool]:
    """Apply consent domain and evidence lifecycle filters BEFORE returning model context."""
    turn_scope, turn_values = domain_filter("t", scope)
    memory_scope, memory_values = domain_filter("m", scope)
    sensitive_turn = "" if allow_sensitive else " AND t.sensitivity = 'normal'"
    sensitive_memory = "" if allow_sensitive else " AND m.sensitivity = 'normal'"
    query = f"""
        WITH source_entities AS (
          SELECT json_extract(e.value, '$.entity') AS payload,
                 json_extract(e.value, '$.reality_layer') AS layer,
                 i.created_at AS observed_at
          FROM turn_interpretations i
          JOIN conversation_turns t ON t.id = i.turn_id
          JOIN json_each(i.record_json, '$.entity_resolutions') e
          WHERE t.user_id = ? AND {turn_scope}
            AND t.deletion_state = 'active' AND t.consent = 'granted'
            AND t.occurred_at <= ? AND json_extract(e.value, '$.entity') IS NOT NULL
            {sensitive_turn}
          UNION ALL
          SELECT e.value AS payload, m.reality_layer AS layer, m.created_at AS observed_at
          FROM memories m JOIN json_each(m.entities_json) e
          WHERE m.user_id = ? AND {memory_scope}
            AND m.status IN ('active', 'candidate') AND m.consent = 'granted'
            AND m.event_at <= ? AND (m.expires_at IS NULL OR m.expires_at > ?)
            {sensitive_memory}
        )
        SELECT payload, MAX(observed_at) AS last_observed
        FROM source_entities WHERE layer = ?
    """
    time = datetime_to_text(as_of)
    parameters: list[Any] = [
        user_id,
        *turn_values,
        time,
        user_id,
        *memory_values,
        time,
        time,
        reality_layer.value,
    ]
    if kind is not None:
        query += " AND json_extract(payload, '$.kind') = ?"
        parameters.append(kind)
    if names is not None:
        normalized = list(dict.fromkeys(entity_key(name) for name in names if name.strip()))
        if not normalized:
            return [], False
        placeholders = ",".join("?" for _ in normalized)
        query += (
            f" AND (companion_entity_key(json_extract(payload, '$.name')) IN ({placeholders})"
            " OR EXISTS (SELECT 1 FROM json_each(payload, '$.aliases') a"
            f" WHERE companion_entity_key(a.value) IN ({placeholders})))"
        )
        parameters.extend([*normalized, *normalized])
    elif text is not None:
        query += (
            " AND (instr(?, companion_entity_key(json_extract(payload, '$.name'))) > 0"
            " OR EXISTS (SELECT 1 FROM json_each(payload, '$.aliases') a"
            " WHERE a.value != '' AND instr(?, companion_entity_key(a.value)) > 0))"
        )
        parameters.extend([entity_key(text), entity_key(text)])
    query += (
        " GROUP BY json_extract(payload, '$.id')"
        " ORDER BY last_observed DESC, json_extract(payload, '$.id') LIMIT ?"
    )
    parameters.append(limit + 1)
    with store.database.connection() as connection:
        connection.create_function("companion_entity_key", 1, entity_key, deterministic=True)
        rows = connection.execute(query, parameters).fetchall()
    return [EntityRef.model_validate_json(row["payload"]) for row in rows[:limit]], len(
        rows
    ) > limit


def resolve_entities(
    store: MemoryStore,
    turn: ConversationTurnRecord,
    proposed: TurnInterpretation,
    limit: int,
) -> tuple[TurnInterpretation, list[EntityResolution], list[str]]:
    resolutions: list[EntityResolution] = []
    mapping: dict[str, str] = {}
    unresolved: set[str] = set()
    reasons: list[str] = []
    reserved = {turn.user_id, turn.actor_id, turn.scope.companion_id}
    for proposal in proposed.entities:
        if proposal.ref in reserved:
            raise ValueError("entity refs cannot replace authenticated actor IDs")
        observed = list(
            dict.fromkeys(
                value
                for value in [proposal.name, *proposal.aliases]
                if entity_key(value) in entity_key(turn.content)
            )
        )
        resolution = EntityResolution(
            ref=proposal.ref,
            status="unanchored",
            reality_layer=proposal.reality_layer,
        )
        matches, truncated = (
            entity_catalog(
                store,
                turn.user_id,
                turn.scope,
                proposal.reality_layer,
                turn.occurred_at,
                limit,
                names=observed,
                kind=proposal.kind,
            )
            if observed and proposal.action != "new"
            else ([], False)
        )
        if truncated or len(matches) > 1:
            resolution.status = "ambiguous"
            resolution.candidate_ids = [match.id for match in matches]
            resolution.reasons = ["namesake_not_automatically_merged"]
        elif observed and (matches or proposal.name in observed):
            resolution.status = "matched" if matches else "new"
            # Store only spellings actually observed HERE, not inherited names from older roots.
            # Forgetting a source therefore removes its alias evidence from the derived catalog.
            display = proposal.name if proposal.name in observed else observed[0]
            resolution.entity = EntityRef(
                id=matches[0].id if matches else f"entity:{uuid4()}",
                kind=proposal.kind,
                name=display,
                aliases=[value for value in observed if value != display],
            )
            mapping[proposal.ref] = resolution.entity.id
        if resolution.entity is None:
            unresolved.add(proposal.ref)
            reasons.append(f"entity_{resolution.status}:{proposal.ref}")
        resolutions.append(resolution)

    def references_known(subject: str | None, refs: list[str]) -> bool:
        return subject not in unresolved and not (set(refs) & unresolved)

    updates: dict[str, Any] = {}
    for category in ("memory_candidates", "state_claims"):
        candidates = []
        for candidate in getattr(proposed, category):
            if not references_known(candidate.subject_actor_id, candidate.entity_refs):
                reasons.append("ambiguous_entity_candidate_deferred")
                continue
            if any(ref not in mapping for ref in candidate.entity_refs):
                raise ValueError("candidate refers to an unknown local entity ref")
            candidates.append(
                candidate.model_copy(
                    update={
                        "subject_actor_id": (
                            mapping.get(candidate.subject_actor_id, candidate.subject_actor_id)
                            if candidate.subject_actor_id is not None
                            else None
                        ),
                    }
                )
            )
        updates[category] = candidates
    hint = proposed.episode_hint
    if hint is not None:
        if set(hint.participant_actor_ids) & unresolved:
            updates["episode_hint"] = None
            reasons.append("episode_hint_with_ambiguous_participant_deferred")
        else:
            updates["episode_hint"] = hint.model_copy(
                update={
                    "participant_actor_ids": [
                        mapping.get(actor, actor) for actor in hint.participant_actor_ids
                    ],
                }
            )
    return proposed.model_copy(update=updates), resolutions, reasons
