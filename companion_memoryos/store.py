from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

from companion_memoryos.constants import DEFAULT_ENCODING
from companion_memoryos.database import Database
from companion_memoryos.schemas import (
    AnswerSemantics,
    BeatReleaseCondition,
    ChannelStatus,
    ChannelWatermark,
    ConsentState,
    ConversationEventInput,
    ConversationEventRecord,
    ConversationRole,
    ConversationTurnInput,
    ConversationTurnRecord,
    EpistemicKind,
    EventStatus,
    ExperienceEvidenceKind,
    ExperienceEvidenceRef,
    FollowUpDecision,
    MemoryInput,
    MemoryRecord,
    MemoryReferenceFeedbackInput,
    MemoryReferenceFeedbackRecord,
    MemoryReferenceMode,
    MemoryScope,
    MemoryStatus,
    MemoryUseInput,
    MemoryUsePlan,
    MemoryUseRecord,
    MemoryUseSummary,
    MemoryUseType,
    OpenLoopInput,
    OpenLoopRecord,
    OpenLoopStatus,
    OpenLoopTransition,
    OpenLoopUpdateRequest,
    PolicyConstraintInput,
    PolicyConstraintRecord,
    PolicyConstraintStatus,
    PolicyEffect,
    PolicyGateDecision,
    PolicyGateRequest,
    ProcessingWatermarkInput,
    RealityLayer,
    RecallUseMode,
    ResolutionStatus,
    ResponseBeatRecord,
    ResponseBeatStatus,
    ResponsePlanInterruptRequest,
    ResponsePlanRecord,
    ResponsePlanRequest,
    ResponsePlanResolutionStatus,
    ResponsePlanStatus,
    RetrievalIntegrityManifest,
    SpeechAct,
    StateQuery,
    StateQueryResult,
    StorageAction,
    StoragePolicyDecision,
    TemporalAnchorInput,
    TemporalAnchorRecord,
    TemporalAnchorStatus,
    TurnDeletionState,
)
from companion_memoryos.semantic_index import (
    TABLES as SEMANTIC_TABLES,
)
from companion_memoryos.semantic_index import (
    SemanticDocument,
    SemanticIndex,
    SemanticKind,
    SemanticQuery,
    SQLiteSemanticIndex,
)


@dataclass
class MemorySearchCandidate:
    memory: MemoryRecord
    lexical_hit: bool = False
    recent_hit: bool = False
    semantic_similarity: float = 0.0


@dataclass
class EventSearchCandidate:
    event: ConversationEventRecord
    lexical_hit: bool = False
    recent_hit: bool = False
    semantic_similarity: float = 0.0


@dataclass
class TurnSearchCandidate:
    turn: ConversationTurnRecord
    lexical_hit: bool = False
    recent_hit: bool = False
    semantic_similarity: float = 0.0


def utc_now() -> datetime:
    return datetime.now(UTC)


def datetime_to_text(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value is not None else None


def datetime_from_text(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value).astimezone(UTC) if value is not None else None


def content_digest(*parts: str) -> str:
    normalized = "\n".join(part.strip().casefold() for part in parts)
    return hashlib.sha256(normalized.encode(DEFAULT_ENCODING)).hexdigest()


def exact_payload_digest(*parts: str) -> str:
    serialized = json.dumps(parts, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(serialized.encode(DEFAULT_ENCODING)).hexdigest()


SCOPE_COLUMNS = ("companion_id", "relationship_id", "conversation_id", "group_id")
CONSENT_DOMAIN_COLUMNS = ("companion_id", "relationship_id", "group_id")


def scope_values(scope: MemoryScope) -> tuple[str | None, ...]:
    return tuple(getattr(scope, column) for column in SCOPE_COLUMNS)


def scope_key(scope: MemoryScope) -> str:
    payload = json.dumps(
        scope.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return content_digest(payload)


def scope_from_row(row: sqlite3.Row) -> MemoryScope:
    return MemoryScope.model_validate({column: row[column] for column in SCOPE_COLUMNS})


class MemoryStore:
    def __init__(self, database: Database, *, semantic_index: SemanticIndex | None = None) -> None:
        self.database = database
        self.semantic_index = semantic_index or SQLiteSemanticIndex(database)

    def find_duplicate(
        self,
        item: MemoryInput,
        stable_key: str | None,
        *,
        allow_candidate_evidence_upgrade: bool,
    ) -> MemoryRecord | None:
        digest = content_digest(item.kind.value, item.title, item.content)
        with self.database.connection() as connection:
            row = connection.execute(
                """
                SELECT * FROM memories
                WHERE user_id = ?
                  AND companion_id IS ? AND relationship_id IS ?
                  AND conversation_id IS ? AND group_id IS ?
                  AND kind = ? AND content_hash = ?
                  AND stable_key IS ?
                  AND reality_layer = ?
                  AND subject_actor_id IS ?
                  AND predicate IS ?
                  AND (
                      (
                          status = ?
                          AND epistemic_kind = ?
                          AND source_actor = ?
                          AND quote_depth = ?
                          AND elicitation_kind = ?
                      )
                      OR (
                          status = ?
                          AND (
                              ?
                              OR (
                                  epistemic_kind = ?
                                  AND source_actor = ?
                                  AND quote_depth = ?
                                  AND elicitation_kind = ?
                              )
                          )
                      )
                  )
                ORDER BY CASE WHEN status = ? THEN 0 ELSE 1 END,
                         created_at DESC
                LIMIT 1
                """,
                (
                    item.user_id,
                    *scope_values(item.scope),
                    item.kind.value,
                    digest,
                    stable_key,
                    item.reality_layer.value,
                    item.subject_actor_id,
                    item.predicate,
                    MemoryStatus.ACTIVE.value,
                    item.epistemic_kind.value,
                    item.source_actor.value,
                    item.quote_depth,
                    item.elicitation_kind.value,
                    MemoryStatus.CANDIDATE.value,
                    allow_candidate_evidence_upgrade,
                    item.epistemic_kind.value,
                    item.source_actor.value,
                    item.quote_depth,
                    item.elicitation_kind.value,
                    MemoryStatus.ACTIVE.value,
                ),
            ).fetchone()
        return self._row_to_memory(cast(sqlite3.Row, row)) if row is not None else None

    def create(
        self,
        item: MemoryInput,
        decision: StoragePolicyDecision,
        stable_key: str | None,
        metadata: dict[str, Any],
        *,
        replace_candidate_id: str | None = None,
    ) -> MemoryRecord:
        if decision.action is StorageAction.DISCARD:
            raise ValueError("discard decisions cannot be persisted")
        now = utc_now()
        memory_id = str(uuid4())
        status = (
            MemoryStatus.ACTIVE
            if decision.action is StorageAction.ACTIVATE
            else MemoryStatus.CANDIDATE
        )
        digest = content_digest(item.kind.value, item.title, item.content)
        evidence_hash = content_digest(item.source_ref, item.source_excerpt or "", item.content)
        with self.database.connection() as connection:
            replacement: sqlite3.Row | None = None
            if replace_candidate_id is not None:
                # Keep the lower-trust candidate until the replacement and
                # all of its evidence checks can commit atomically.
                if not connection.in_transaction:
                    connection.execute("BEGIN IMMEDIATE")
                replacement = self._select_one(
                    connection,
                    replace_candidate_id,
                    item.user_id,
                )
                if (
                    replacement is None
                    or replacement["status"] != MemoryStatus.CANDIDATE.value
                    or replacement["kind"] != item.kind.value
                    or replacement["content_hash"] != digest
                    or replacement["stable_key"] != stable_key
                    or replacement["reality_layer"] != item.reality_layer.value
                    or replacement["subject_actor_id"] != item.subject_actor_id
                    or replacement["predicate"] != item.predicate
                    or any(
                        replacement[column] != getattr(item.scope, column)
                        for column in SCOPE_COLUMNS
                    )
                ):
                    raise ValueError("replacement candidate is no longer eligible")
            if item.evidence_turn_ids:
                placeholders = ", ".join("?" for _ in item.evidence_turn_ids)
                rows = connection.execute(
                    f"SELECT id, companion_id, relationship_id, conversation_id, group_id, "
                    f"actor_id, role, speech_spans_json, deletion_state FROM conversation_turns "
                    f"WHERE user_id = ? AND id IN ({placeholders})",
                    (item.user_id, *item.evidence_turn_ids),
                ).fetchall()
                if {str(row["id"]) for row in rows} != set(item.evidence_turn_ids):
                    raise ValueError("all evidence turns must belong to the same user")
                for row in rows:
                    if row["deletion_state"] != TurnDeletionState.ACTIVE.value:
                        raise ValueError("forgotten turns cannot support a new memory")
                    if not self._evidence_scope_is_compatible(item.scope, row):
                        raise ValueError(
                            "evidence-derived memories cannot widen their consent scope"
                        )
                    if (
                        item.epistemic_kind
                        in {
                            EpistemicKind.DIRECT_SELF_REPORT,
                            EpistemicKind.RELATIONSHIP_CONTRACT,
                        }
                        and row["role"] != ConversationRole.USER.value
                    ):
                        raise ValueError("user state evidence must come from a user-authored turn")
                    if item.epistemic_kind in {
                        EpistemicKind.DIRECT_SELF_REPORT,
                        EpistemicKind.RELATIONSHIP_CONTRACT,
                    } and not self._turn_has_direct_user_evidence(row):
                        raise ValueError(
                            "quoted or fictional speech cannot support direct user state"
                        )
            supersedes_id = None
            if status is MemoryStatus.ACTIVE and stable_key is not None:
                supersedes_id = self._supersede_current(
                    connection,
                    item.user_id,
                    item.scope,
                    item.kind.value,
                    stable_key,
                    now,
                    subject_actor_id=item.subject_actor_id,
                    predicate=item.predicate,
                    reality_layer=item.reality_layer,
                )
            connection.execute(
                """
                INSERT INTO memories (
                    id, user_id, companion_id, relationship_id, conversation_id, group_id,
                    kind, title, content, stable_key, emotions_json,
                    needs_json, status, consent, sensitivity, retention, confidence,
                    salience, event_at, valid_time_start, valid_time_end, valid_from,
                    valid_to, expires_at, supersedes_id, source_ref, content_hash,
                    entities_json, epistemic_kind, resolution_status, reality_layer,
                    source_actor, quote_depth, elicitation_kind, subject_actor_id,
                    predicate, evidence_turn_ids_json, metadata_json, created_at, updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    memory_id,
                    item.user_id,
                    *scope_values(item.scope),
                    item.kind.value,
                    item.title,
                    item.content,
                    stable_key,
                    json.dumps(
                        [emotion.model_dump(mode="json") for emotion in item.emotions],
                        ensure_ascii=False,
                    ),
                    json.dumps(item.needs, ensure_ascii=False),
                    status.value,
                    item.consent.value,
                    item.sensitivity.value,
                    decision.retention.value,
                    item.confidence,
                    item.salience,
                    datetime_to_text(item.event_at),
                    datetime_to_text(item.valid_time_start or item.event_at),
                    datetime_to_text(item.valid_time_end),
                    datetime_to_text(now),
                    None,
                    datetime_to_text(decision.expires_at),
                    supersedes_id,
                    item.source_ref,
                    digest,
                    json.dumps(
                        [entity.model_dump(mode="json") for entity in item.entities],
                        ensure_ascii=False,
                    ),
                    item.epistemic_kind.value,
                    item.resolution_status.value,
                    item.reality_layer.value,
                    item.source_actor.value,
                    item.quote_depth,
                    item.elicitation_kind.value,
                    item.subject_actor_id,
                    item.predicate,
                    json.dumps(item.evidence_turn_ids, ensure_ascii=False),
                    json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                    datetime_to_text(now),
                    datetime_to_text(now),
                ),
            )
            if item.embedding is not None and item.embedding_space is not None:
                self._insert_embedding(
                    connection,
                    "memory_embeddings",
                    "memory_id",
                    memory_id,
                    item.embedding_space,
                    item.embedding,
                    now,
                )
            connection.execute(
                """
                INSERT INTO evidence (
                    memory_id, source_ref, source_excerpt, evidence_hash, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    memory_id,
                    item.source_ref,
                    item.source_excerpt,
                    evidence_hash,
                    datetime_to_text(now),
                ),
            )
            self._audit(
                connection,
                memory_id,
                item.user_id,
                "memory.created",
                {"status": status.value, "reasons": decision.reasons},
                now,
            )
            if replacement is not None:
                candidate_id = cast(str, replace_candidate_id)
                connection.execute(
                    """
                    UPDATE memories
                    SET status = ?, valid_to = ?, updated_at = ?
                    WHERE id = ? AND user_id = ? AND status = ?
                    """,
                    (
                        MemoryStatus.REJECTED.value,
                        datetime_to_text(now),
                        datetime_to_text(now),
                        candidate_id,
                        item.user_id,
                        MemoryStatus.CANDIDATE.value,
                    ),
                )
                self._audit(
                    connection,
                    candidate_id,
                    item.user_id,
                    "memory.replaced_by_direct_evidence",
                    {"replacement_id": memory_id},
                    now,
                )
            row = connection.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
        return self._row_to_memory(cast(sqlite3.Row, row))

    def review(
        self,
        memory_id: str,
        user_id: str,
        confirm: bool,
        confirmed_expires_at: datetime | None = None,
    ) -> MemoryRecord:
        now = utc_now()
        with self.database.connection() as connection:
            current = self._select_one(connection, memory_id, user_id)
            if current is None:
                raise KeyError(memory_id)
            if current["status"] != MemoryStatus.CANDIDATE.value:
                raise ValueError("only candidate memories can be reviewed")
            status = MemoryStatus.ACTIVE if confirm else MemoryStatus.REJECTED
            supersedes_id = None
            if confirm and current["stable_key"] is not None:
                supersedes_id = self._supersede_current(
                    connection,
                    user_id,
                    scope_from_row(current),
                    str(current["kind"]),
                    str(current["stable_key"]),
                    now,
                    exclude_id=memory_id,
                    subject_actor_id=current["subject_actor_id"],
                    predicate=current["predicate"],
                    reality_layer=RealityLayer(current["reality_layer"]),
                )
            connection.execute(
                """
                UPDATE memories
                SET status = ?, consent = ?, valid_to = ?, expires_at = ?,
                    supersedes_id = ?, updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (
                    status.value,
                    (ConsentState.GRANTED.value if confirm else current["consent"]),
                    None if confirm else datetime_to_text(now),
                    datetime_to_text(confirmed_expires_at) if confirm else current["expires_at"],
                    supersedes_id,
                    datetime_to_text(now),
                    memory_id,
                    user_id,
                ),
            )
            self._audit(
                connection,
                memory_id,
                user_id,
                "memory.confirmed" if confirm else "memory.rejected",
                {},
                now,
            )
            row = self._select_one(connection, memory_id, user_id)
        return self._row_to_memory(cast(sqlite3.Row, row))

    def forget(self, memory_id: str, user_id: str) -> MemoryRecord:
        now = utc_now()
        with self.database.connection() as connection:
            row = self._select_one(connection, memory_id, user_id)
            if row is None:
                raise KeyError(memory_id)
            self.semantic_index.delete(SemanticKind.MEMORY, memory_id, user_id)
            connection.execute(
                """
                UPDATE memories
                SET status = ?, valid_to = ?, updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (
                    MemoryStatus.FORGOTTEN.value,
                    datetime_to_text(now),
                    datetime_to_text(now),
                    memory_id,
                    user_id,
                ),
            )
            self._audit(connection, memory_id, user_id, "memory.forgotten", {}, now)
            updated = self._select_one(connection, memory_id, user_id)
        return self._row_to_memory(cast(sqlite3.Row, updated))

    def purge(self, memory_id: str, user_id: str) -> None:
        now = utc_now()
        with self.database.connection() as connection:
            row = self._select_one(connection, memory_id, user_id)
            if row is None:
                raise KeyError(memory_id)
            self.semantic_index.delete(SemanticKind.MEMORY, memory_id, user_id)
            self._clear_audit_history(connection, memory_id, user_id)
            self._audit(
                connection,
                memory_id,
                user_id,
                "memory.purged",
                {},
                now,
            )
            connection.execute(
                "DELETE FROM memory_use_events WHERE memory_id = ? AND user_id = ?",
                (memory_id, user_id),
            )
            connection.execute(
                "UPDATE memories SET supersedes_id = NULL WHERE user_id = ? AND supersedes_id = ?",
                (user_id, memory_id),
            )
            connection.execute(
                "DELETE FROM memories WHERE id = ? AND user_id = ?", (memory_id, user_id)
            )

    def get(self, memory_id: str, user_id: str) -> MemoryRecord:
        with self.database.connection() as connection:
            row = self._select_one(connection, memory_id, user_id)
        if row is None:
            raise KeyError(memory_id)
        return self._row_to_memory(row)

    def list_memories(
        self,
        user_id: str,
        statuses: set[MemoryStatus] | None = None,
        limit: int | None = None,
        scope: MemoryScope | None = None,
    ) -> list[MemoryRecord]:
        clauses = ["user_id = ?"]
        parameters: list[Any] = [user_id]
        if statuses:
            placeholders = ", ".join("?" for _ in statuses)
            clauses.append(f"status IN ({placeholders})")
            parameters.extend(status.value for status in statuses)
        if scope is not None:
            scope_clauses, scope_parameters = self._hierarchical_scope_filter("memories", scope)
            clauses.extend(scope_clauses)
            parameters.extend(scope_parameters)
        query = f"SELECT * FROM memories WHERE {' AND '.join(clauses)} ORDER BY updated_at DESC"
        if limit is not None:
            query += " LIMIT ?"
            parameters.append(limit)
        with self.database.connection() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._row_to_memory(row) for row in rows]

    def create_temporal_anchor(self, item: TemporalAnchorInput) -> TemporalAnchorRecord:
        now = utc_now()
        anchor_id = str(uuid4())
        normalized_name = item.name.casefold()
        with self.database.connection() as connection:
            current = connection.execute(
                """
                SELECT id FROM temporal_anchors
                WHERE user_id = ?
                  AND companion_id IS ? AND relationship_id IS ?
                  AND conversation_id IS ? AND group_id IS ?
                  AND normalized_name = ? AND status = ?
                ORDER BY updated_at DESC LIMIT 1
                """,
                (
                    item.user_id,
                    *scope_values(item.scope),
                    normalized_name,
                    TemporalAnchorStatus.ACTIVE.value,
                ),
            ).fetchone()
            supersedes_id = str(current["id"]) if current is not None else None
            if supersedes_id is not None:
                connection.execute(
                    """
                    UPDATE temporal_anchors
                    SET status = ?, valid_to = ?, updated_at = ?
                    WHERE id = ? AND user_id = ?
                    """,
                    (
                        TemporalAnchorStatus.SUPERSEDED.value,
                        datetime_to_text(now),
                        datetime_to_text(now),
                        supersedes_id,
                        item.user_id,
                    ),
                )
                self._audit(
                    connection,
                    supersedes_id,
                    item.user_id,
                    "temporal_anchor.superseded",
                    {},
                    now,
                )
            connection.execute(
                """
                INSERT INTO temporal_anchors (
                    id, user_id, companion_id, relationship_id, conversation_id, group_id,
                    name, normalized_name, aliases_json, start_at, end_at, status,
                    consent, sensitivity, source_ref, supersedes_id, valid_from,
                    valid_to, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    anchor_id,
                    item.user_id,
                    *scope_values(item.scope),
                    item.name,
                    normalized_name,
                    json.dumps(item.aliases, ensure_ascii=False),
                    datetime_to_text(item.start_at),
                    datetime_to_text(item.end_at),
                    TemporalAnchorStatus.ACTIVE.value,
                    item.consent.value,
                    item.sensitivity.value,
                    item.source_ref,
                    supersedes_id,
                    datetime_to_text(now),
                    None,
                    datetime_to_text(now),
                    datetime_to_text(now),
                ),
            )
            self._audit(
                connection,
                anchor_id,
                item.user_id,
                "temporal_anchor.created",
                {
                    "start_at": datetime_to_text(item.start_at),
                    "end_at": datetime_to_text(item.end_at),
                    "supersedes_id": supersedes_id,
                    "evidence_hash": content_digest(
                        item.source_ref, item.source_excerpt or "", item.name
                    ),
                },
                now,
            )
            row = connection.execute(
                "SELECT * FROM temporal_anchors WHERE id = ?", (anchor_id,)
            ).fetchone()
        return self._row_to_temporal_anchor(cast(sqlite3.Row, row))

    def list_temporal_anchors(
        self,
        user_id: str,
        statuses: set[TemporalAnchorStatus] | None = None,
        limit: int | None = None,
    ) -> list[TemporalAnchorRecord]:
        clauses = ["user_id = ?"]
        parameters: list[Any] = [user_id]
        if statuses:
            placeholders = ", ".join("?" for _ in statuses)
            clauses.append(f"status IN ({placeholders})")
            parameters.extend(status.value for status in statuses)
        query = (
            f"SELECT * FROM temporal_anchors WHERE {' AND '.join(clauses)} ORDER BY updated_at DESC"
        )
        if limit is not None:
            query += " LIMIT ?"
            parameters.append(limit)
        with self.database.connection() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._row_to_temporal_anchor(row) for row in rows]

    def resolve_temporal_anchors(
        self,
        user_id: str,
        scope: MemoryScope,
        query: str,
        as_of: datetime,
        minimum_match_characters: int,
        max_matches: int,
    ) -> list[TemporalAnchorRecord]:
        query_text = query.casefold()
        as_of_text = datetime_to_text(as_of)
        scope_clauses, scope_parameters = self._hierarchical_scope_filter("temporal_anchors", scope)
        with self.database.connection() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM temporal_anchors
                WHERE user_id = ? AND status IN (?, ?)
                  AND valid_from <= ? AND (valid_to IS NULL OR valid_to > ?)
                  AND {" AND ".join(scope_clauses)}
                """,
                (
                    user_id,
                    TemporalAnchorStatus.ACTIVE.value,
                    TemporalAnchorStatus.SUPERSEDED.value,
                    as_of_text,
                    as_of_text,
                    *scope_parameters,
                ),
            ).fetchall()
        matches: list[tuple[int, datetime, TemporalAnchorRecord]] = []
        for row in rows:
            anchor = self._row_to_temporal_anchor(row)
            terms = [anchor.name, *anchor.aliases]
            matched_lengths = [
                len(term)
                for term in terms
                if len(term.strip()) >= minimum_match_characters
                and term.strip().casefold() in query_text
            ]
            if matched_lengths:
                matches.append((max(matched_lengths), anchor.updated_at, anchor))
        if matches:
            strongest_match = max(value[0] for value in matches)
            matches = [value for value in matches if value[0] == strongest_match]
        matches.sort(key=lambda value: (-value[0], -value[1].timestamp(), value[2].id))
        return [value[2] for value in matches[:max_matches]]

    def forget_temporal_anchor(self, anchor_id: str, user_id: str) -> TemporalAnchorRecord:
        now = utc_now()
        with self.database.connection() as connection:
            row = self._select_temporal_anchor(connection, anchor_id, user_id)
            if row is None:
                raise KeyError(anchor_id)
            connection.execute(
                """
                UPDATE temporal_anchors
                SET status = ?, valid_to = ?, updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (
                    TemporalAnchorStatus.FORGOTTEN.value,
                    datetime_to_text(now),
                    datetime_to_text(now),
                    anchor_id,
                    user_id,
                ),
            )
            self._audit(connection, anchor_id, user_id, "temporal_anchor.forgotten", {}, now)
            updated = self._select_temporal_anchor(connection, anchor_id, user_id)
        return self._row_to_temporal_anchor(cast(sqlite3.Row, updated))

    def purge_temporal_anchor(self, anchor_id: str, user_id: str) -> None:
        now = utc_now()
        with self.database.connection() as connection:
            row = self._select_temporal_anchor(connection, anchor_id, user_id)
            if row is None:
                raise KeyError(anchor_id)
            self._clear_audit_history(connection, anchor_id, user_id)
            self._audit(
                connection,
                anchor_id,
                user_id,
                "temporal_anchor.purged",
                {},
                now,
            )
            connection.execute(
                "DELETE FROM temporal_anchors WHERE id = ? AND user_id = ?",
                (anchor_id, user_id),
            )

    def active_pool(
        self,
        user_id: str,
        scope: MemoryScope,
        fts_query: str,
        pool_size: int,
        as_of: datetime,
        *,
        semantic_pool_size: int,
        minimum_semantic_similarity: float,
        entity_ids: list[str],
        emotion_labels: list[str],
        needs: list[str],
        query_embedding: list[float] | None = None,
        embedding_space: str | None = None,
        event_after: datetime | None = None,
        event_before: datetime | None = None,
        reality_layer: RealityLayer | None = None,
    ) -> list[MemorySearchCandidate]:
        self.expire_due(utc_now())
        where, parameters = self._memory_validity_filter(
            user_id,
            scope,
            as_of,
            event_after,
            event_before,
        )
        realm_sql, realm_parameters = self._realm_filter("memories", reality_layer)
        where += realm_sql
        parameters.extend(realm_parameters)
        with self.database.connection() as connection:
            candidates: dict[str, MemorySearchCandidate] = {}
            if fts_query:
                rows = connection.execute(
                    f"""
                    SELECT memories.* FROM memories
                    JOIN memory_fts ON memory_fts.memory_id = memories.id
                    WHERE {where} AND memory_fts MATCH ?
                    ORDER BY bm25(memory_fts) LIMIT ?
                    """,
                    (*parameters, fts_query, pool_size),
                ).fetchall()
                for row in rows:
                    memory = self._row_to_memory(row)
                    candidates[memory.id] = MemorySearchCandidate(
                        memory=memory,
                        lexical_hit=True,
                    )

            recent_rows = connection.execute(
                f"""
                SELECT memories.* FROM memories
                WHERE {where}
                ORDER BY CASE WHEN kind = 'boundary' THEN 0 ELSE 1 END,
                         event_at DESC
                LIMIT ?
                """,
                (*parameters, pool_size),
            ).fetchall()
            for row in recent_rows:
                memory = self._row_to_memory(row)
                candidate = candidates.setdefault(memory.id, MemorySearchCandidate(memory=memory))
                candidate.recent_hit = True

            for json_column, json_path, values in (
                ("entities_json", "$.id", entity_ids),
                ("emotions_json", "$.label", emotion_labels),
            ):
                if not values:
                    continue
                value_placeholders = ", ".join("?" for _ in values)
                signal_rows = connection.execute(
                    f"""
                    SELECT DISTINCT memories.* FROM memories
                    JOIN json_each(memories.{json_column}) AS signal
                    WHERE {where} AND json_extract(signal.value, ?) IN ({value_placeholders})
                    ORDER BY event_at DESC LIMIT ?
                    """,
                    (*parameters, json_path, *values, pool_size),
                ).fetchall()
                for row in signal_rows:
                    memory = self._row_to_memory(row)
                    candidates.setdefault(memory.id, MemorySearchCandidate(memory=memory))

            if needs:
                value_placeholders = ", ".join("?" for _ in needs)
                need_rows = connection.execute(
                    f"""
                    SELECT DISTINCT memories.* FROM memories
                    JOIN json_each(memories.needs_json) AS need
                    WHERE {where} AND need.value IN ({value_placeholders})
                    ORDER BY event_at DESC LIMIT ?
                    """,
                    (*parameters, *needs, pool_size),
                ).fetchall()
                for row in need_rows:
                    memory = self._row_to_memory(row)
                    candidates.setdefault(memory.id, MemorySearchCandidate(memory=memory))

            boundary_where, boundary_parameters = self._memory_validity_filter(
                user_id,
                scope,
                as_of,
                None,
                None,
            )
            boundary_where += realm_sql
            boundary_parameters.extend(realm_parameters)
            boundary_rows = connection.execute(
                f"""
                SELECT memories.* FROM memories
                WHERE {boundary_where} AND kind = ?
                ORDER BY event_at DESC
                """,
                (*boundary_parameters, "boundary"),
            ).fetchall()
            for row in boundary_rows:
                memory = self._row_to_memory(row)
                candidates.setdefault(memory.id, MemorySearchCandidate(memory=memory))

            if query_embedding is not None and embedding_space is not None:
                semantic_query = SemanticQuery(
                    kind=SemanticKind.MEMORY,
                    reality_layer=reality_layer,
                    user_id=user_id,
                    scope=scope,
                    vector=query_embedding,
                    space=embedding_space,
                    as_of=as_of,
                    limit=semantic_pool_size,
                    minimum_similarity=minimum_semantic_similarity,
                    event_after=event_after,
                    event_before=event_before,
                )
                for similarity, row in self._semantic_candidates(
                    connection, semantic_query, where, parameters
                ):
                    memory = self._row_to_memory(row)
                    candidate = candidates.setdefault(
                        memory.id,
                        MemorySearchCandidate(memory=memory),
                    )
                    candidate.semantic_similarity = similarity
        return list(candidates.values())

    def create_event(
        self,
        item: ConversationEventInput,
        expires_at: datetime,
    ) -> ConversationEventRecord:
        now = utc_now()
        event_id = str(uuid4())
        event_scope = item.scope
        if event_scope.conversation_id is None:
            event_scope = event_scope.model_copy(update={"conversation_id": item.session_id})
        entities_json = json.dumps(
            [entity.model_dump(mode="json") for entity in item.entities],
            ensure_ascii=False,
        )
        with self.database.connection() as connection:
            connection.execute(
                """
                INSERT INTO conversation_events (
                    id, user_id, companion_id, relationship_id, conversation_id, group_id,
                    session_id, role, content, status, consent, sensitivity, occurred_at,
                    expires_at, source_ref, entities_json, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    item.user_id,
                    *scope_values(event_scope),
                    item.session_id,
                    item.role.value,
                    item.content,
                    EventStatus.ACTIVE.value,
                    item.consent.value,
                    item.sensitivity.value,
                    datetime_to_text(item.occurred_at),
                    datetime_to_text(expires_at),
                    item.source_ref,
                    entities_json,
                    json.dumps(item.metadata, ensure_ascii=False, sort_keys=True),
                    datetime_to_text(now),
                ),
            )
            if item.embedding is not None and item.embedding_space is not None:
                self._insert_embedding(
                    connection,
                    "event_embeddings",
                    "event_id",
                    event_id,
                    item.embedding_space,
                    item.embedding,
                    now,
                )
            self._audit(
                connection,
                event_id,
                item.user_id,
                "event.created",
                {"session_id": item.session_id, "role": item.role.value},
                now,
            )
            row = connection.execute(
                "SELECT * FROM conversation_events WHERE id = ?",
                (event_id,),
            ).fetchone()
        return self._row_to_event(cast(sqlite3.Row, row))

    def get_event(self, event_id: str, user_id: str) -> ConversationEventRecord:
        self.expire_events(utc_now())
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM conversation_events WHERE id = ? AND user_id = ?",
                (event_id, user_id),
            ).fetchone()
        if row is None:
            raise KeyError(event_id)
        return self._row_to_event(row)

    def list_events(
        self,
        user_id: str,
        statuses: set[EventStatus] | None = None,
        limit: int | None = None,
    ) -> list[ConversationEventRecord]:
        self.expire_events(utc_now())
        clauses = ["user_id = ?"]
        parameters: list[Any] = [user_id]
        if statuses:
            placeholders = ", ".join("?" for _ in statuses)
            clauses.append(f"status IN ({placeholders})")
            parameters.extend(status.value for status in statuses)
        query = (
            f"SELECT * FROM conversation_events WHERE {' AND '.join(clauses)} "
            "ORDER BY occurred_at DESC"
        )
        if limit is not None:
            query += " LIMIT ?"
            parameters.append(limit)
        with self.database.connection() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._row_to_event(row) for row in rows]

    def forget_event(self, event_id: str, user_id: str) -> ConversationEventRecord:
        now = utc_now()
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM conversation_events WHERE id = ? AND user_id = ?",
                (event_id, user_id),
            ).fetchone()
            if row is None:
                raise KeyError(event_id)
            self.semantic_index.delete(SemanticKind.EVENT, event_id, user_id)
            connection.execute(
                "UPDATE conversation_events SET status = ? WHERE id = ? AND user_id = ?",
                (EventStatus.FORGOTTEN.value, event_id, user_id),
            )
            self._audit(connection, event_id, user_id, "event.forgotten", {}, now)
            updated = connection.execute(
                "SELECT * FROM conversation_events WHERE id = ? AND user_id = ?",
                (event_id, user_id),
            ).fetchone()
        return self._row_to_event(cast(sqlite3.Row, updated))

    def purge_event(self, event_id: str, user_id: str) -> None:
        now = utc_now()
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM conversation_events WHERE id = ? AND user_id = ?",
                (event_id, user_id),
            ).fetchone()
            if row is None:
                raise KeyError(event_id)
            self.semantic_index.delete(SemanticKind.EVENT, event_id, user_id)
            self._clear_audit_history(connection, event_id, user_id)
            self._audit(
                connection,
                event_id,
                user_id,
                "event.purged",
                {},
                now,
            )
            connection.execute(
                "DELETE FROM conversation_events WHERE id = ? AND user_id = ?",
                (event_id, user_id),
            )

    def event_pool(
        self,
        user_id: str,
        scope: MemoryScope,
        fts_query: str,
        pool_size: int,
        as_of: datetime,
        *,
        minimum_semantic_similarity: float,
        entity_ids: list[str],
        query_embedding: list[float] | None = None,
        embedding_space: str | None = None,
        event_after: datetime | None = None,
        event_before: datetime | None = None,
        reality_layer: RealityLayer | None = None,
    ) -> list[EventSearchCandidate]:
        self.expire_events(utc_now())
        where, parameters = self._event_validity_filter(
            user_id,
            scope,
            as_of,
            event_after,
            event_before,
        )
        realm_sql, realm_parameters = self._realm_filter("conversation_events", reality_layer)
        where += realm_sql
        parameters.extend(realm_parameters)
        with self.database.connection() as connection:
            candidates: dict[str, EventSearchCandidate] = {}
            if fts_query:
                rows = connection.execute(
                    f"""
                    SELECT conversation_events.* FROM conversation_events
                    JOIN event_fts ON event_fts.event_id = conversation_events.id
                    WHERE {where} AND event_fts MATCH ?
                    ORDER BY bm25(event_fts) LIMIT ?
                    """,
                    (*parameters, fts_query, pool_size),
                ).fetchall()
                for row in rows:
                    event = self._row_to_event(row)
                    candidates[event.id] = EventSearchCandidate(event=event, lexical_hit=True)

            recent_rows = connection.execute(
                f"""
                SELECT conversation_events.* FROM conversation_events
                WHERE {where}
                ORDER BY occurred_at DESC LIMIT ?
                """,
                (*parameters, pool_size),
            ).fetchall()
            for row in recent_rows:
                event = self._row_to_event(row)
                candidate = candidates.setdefault(event.id, EventSearchCandidate(event=event))
                candidate.recent_hit = True

            if entity_ids:
                value_placeholders = ", ".join("?" for _ in entity_ids)
                entity_rows = connection.execute(
                    f"""
                    SELECT DISTINCT conversation_events.* FROM conversation_events
                    JOIN json_each(conversation_events.entities_json) AS entity
                    WHERE {where} AND json_extract(entity.value, '$.id')
                        IN ({value_placeholders})
                    ORDER BY occurred_at DESC LIMIT ?
                    """,
                    (*parameters, *entity_ids, pool_size),
                ).fetchall()
                for row in entity_rows:
                    event = self._row_to_event(row)
                    candidates.setdefault(event.id, EventSearchCandidate(event=event))

            if query_embedding is not None and embedding_space is not None:
                semantic_query = SemanticQuery(
                    kind=SemanticKind.EVENT,
                    reality_layer=reality_layer,
                    user_id=user_id,
                    scope=scope,
                    vector=query_embedding,
                    space=embedding_space,
                    as_of=as_of,
                    limit=pool_size,
                    minimum_similarity=minimum_semantic_similarity,
                    event_after=event_after,
                    event_before=event_before,
                )
                for similarity, row in self._semantic_candidates(
                    connection, semantic_query, where, parameters
                ):
                    event = self._row_to_event(row)
                    candidate = candidates.setdefault(
                        event.id,
                        EventSearchCandidate(event=event),
                    )
                    candidate.semantic_similarity = similarity
        return list(candidates.values())

    def append_turn(
        self, item: ConversationTurnInput
    ) -> tuple[ConversationTurnRecord, str | None, list[str]]:
        now = utc_now()
        turn_id = str(uuid4())
        speech_spans_json = json.dumps(
            [span.model_dump(mode="json") for span in item.speech_spans],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        metadata_json = json.dumps(
            item.metadata,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        retrieval_keys_json = json.dumps(
            item.retrieval_keys,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        embedding_json = json.dumps(
            item.embedding,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        digest = exact_payload_digest(
            item.user_id,
            *(value or "" for value in scope_values(item.scope)),
            item.actor_id,
            item.role.value,
            datetime_to_text(item.occurred_at) or "",
            item.content,
            item.consent.value,
            item.sensitivity.value,
            item.modality.value,
            item.language or "",
            item.reply_to_turn_id or "",
            item.supersedes_turn_id or "",
            item.episode_id or "",
            item.source_ref,
            speech_spans_json,
            retrieval_keys_json,
            item.embedding_space or "",
            embedding_json,
            metadata_json,
        )
        with self.database.connection() as connection:
            # Acquire the writer slot before the idempotency lookup so two
            # concurrent deliveries cannot both observe a missing key.
            if not connection.in_transaction:
                connection.execute("BEGIN IMMEDIATE")
            if item.idempotency_key is not None:
                duplicate = connection.execute(
                    """
                    SELECT * FROM conversation_turns
                    WHERE user_id = ?
                      AND companion_id IS ? AND relationship_id IS ?
                      AND conversation_id IS ? AND group_id IS ?
                      AND idempotency_key = ?
                    ORDER BY server_sequence DESC LIMIT 1
                    """,
                    (
                        item.user_id,
                        *scope_values(item.scope),
                        item.idempotency_key,
                    ),
                ).fetchone()
                if duplicate is not None:
                    if duplicate["content_hash"] != digest:
                        legacy_digest = exact_payload_digest(
                            item.user_id,
                            *(value or "" for value in scope_values(item.scope)),
                            item.actor_id,
                            item.role.value,
                            datetime_to_text(item.occurred_at) or "",
                            item.content,
                            item.consent.value,
                            item.sensitivity.value,
                            item.modality.value,
                            item.language or "",
                            item.reply_to_turn_id or "",
                            item.supersedes_turn_id or "",
                            item.source_ref,
                            speech_spans_json,
                            metadata_json,
                        )
                        if (
                            duplicate["content_hash"] != legacy_digest
                            or item.retrieval_keys
                            or item.embedding is not None
                            or item.embedding_space is not None
                            or item.episode_id is not None
                        ):
                            raise ValueError(
                                "idempotency key cannot be reused for a different turn payload"
                            )
                    if duplicate["deletion_state"] != TurnDeletionState.ACTIVE.value:
                        raise ValueError("idempotency key belongs to a forgotten turn")
                    record = self._row_to_turn(duplicate)
                    return record, record.id, []
            for reference in (item.reply_to_turn_id, item.supersedes_turn_id):
                if reference is None:
                    continue
                referenced = connection.execute(
                    "SELECT user_id, companion_id, relationship_id, conversation_id, group_id "
                    "FROM conversation_turns WHERE id = ?",
                    (reference,),
                ).fetchone()
                if (
                    referenced is None
                    or referenced["user_id"] != item.user_id
                    or any(
                        referenced[column] != getattr(item.scope, column)
                        for column in SCOPE_COLUMNS
                    )
                ):
                    raise ValueError("turn references must remain in the same exact scope")
            connection.execute(
                """
                INSERT INTO conversation_turns (
                    id, user_id, companion_id, relationship_id, conversation_id, group_id,
                    actor_id, role, content, consent, sensitivity, occurred_at, ingested_at,
                    modality, language, reply_to_turn_id, supersedes_turn_id, episode_id,
                    source_ref,
                    idempotency_key, speech_spans_json, retrieval_keys_json, embedding_space,
                    content_hash, deletion_state, metadata_json
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    turn_id,
                    item.user_id,
                    *scope_values(item.scope),
                    item.actor_id,
                    item.role.value,
                    item.content,
                    item.consent.value,
                    item.sensitivity.value,
                    datetime_to_text(item.occurred_at),
                    datetime_to_text(now),
                    item.modality.value,
                    item.language,
                    item.reply_to_turn_id,
                    item.supersedes_turn_id,
                    item.episode_id,
                    item.source_ref,
                    item.idempotency_key,
                    speech_spans_json,
                    retrieval_keys_json,
                    item.embedding_space,
                    digest,
                    TurnDeletionState.ACTIVE.value,
                    metadata_json,
                ),
            )
            if item.embedding is not None and item.embedding_space is not None:
                self._insert_embedding(
                    connection,
                    "turn_embeddings",
                    "turn_id",
                    turn_id,
                    item.embedding_space,
                    item.embedding,
                    now,
                )
            self._audit(
                connection,
                turn_id,
                item.user_id,
                "conversation_turn.appended",
                {
                    "actor_id": item.actor_id,
                    "conversation_id": item.scope.conversation_id,
                    "role": item.role.value,
                },
                now,
            )
            row = connection.execute(
                "SELECT * FROM conversation_turns WHERE id = ?", (turn_id,)
            ).fetchone()
            cancelled_plan_ids = (
                self._cancel_active_response_plans(
                    connection,
                    item.user_id,
                    item.scope,
                    "new_user_turn",
                    now,
                    interrupt_only=True,
                )
                if item.role is ConversationRole.USER
                else []
            )
        return self._row_to_turn(cast(sqlite3.Row, row)), None, cancelled_plan_ids

    def list_turns(
        self,
        user_id: str,
        scope: MemoryScope | None = None,
        limit: int | None = None,
    ) -> list[ConversationTurnRecord]:
        clauses = ["user_id = ?"]
        parameters: list[Any] = [user_id]
        if scope is not None:
            for column in SCOPE_COLUMNS:
                value = getattr(scope, column)
                if value is not None:
                    clauses.append(f"{column} = ?")
                    parameters.append(value)
        query = (
            f"SELECT * FROM conversation_turns WHERE {' AND '.join(clauses)} "
            "ORDER BY server_sequence DESC"
        )
        if limit is not None:
            query += " LIMIT ?"
            parameters.append(limit)
        with self.database.connection() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._row_to_turn(row) for row in rows]

    def get_turn(self, turn_id: str, user_id: str) -> ConversationTurnRecord:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM conversation_turns WHERE id = ? AND user_id = ?",
                (turn_id, user_id),
            ).fetchone()
        if row is None:
            raise KeyError(turn_id)
        return self._row_to_turn(row)

    def forget_turn(
        self,
        turn_id: str,
        user_id: str,
        *,
        revoke_source_policies: bool = False,
    ) -> ConversationTurnRecord:
        now = utc_now()
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM conversation_turns WHERE id = ? AND user_id = ?",
                (turn_id, user_id),
            ).fetchone()
            if row is None:
                raise KeyError(turn_id)
            self._require_source_policy_revocation_ack(
                connection, turn_id, user_id, now, revoke_source_policies
            )
            self._invalidate_turn_descendants(
                connection, turn_id, user_id, now, purge_descendants=False
            )
            connection.execute(
                "UPDATE conversation_turns SET deletion_state = ? WHERE id = ? AND user_id = ?",
                (TurnDeletionState.FORGOTTEN.value, turn_id, user_id),
            )
            self._audit(connection, turn_id, user_id, "conversation_turn.forgotten", {}, now)
            updated = connection.execute(
                "SELECT * FROM conversation_turns WHERE id = ? AND user_id = ?",
                (turn_id, user_id),
            ).fetchone()
        return self._row_to_turn(cast(sqlite3.Row, updated))

    def purge_turn(
        self,
        turn_id: str,
        user_id: str,
        *,
        revoke_source_policies: bool = False,
    ) -> None:
        now = utc_now()
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM conversation_turns WHERE id = ? AND user_id = ?",
                (turn_id, user_id),
            ).fetchone()
            if row is None:
                raise KeyError(turn_id)
            self._require_source_policy_revocation_ack(
                connection, turn_id, user_id, now, revoke_source_policies
            )
            self._invalidate_turn_descendants(
                connection, turn_id, user_id, now, purge_descendants=True
            )
            self._clear_audit_history(connection, turn_id, user_id)
            self._audit(
                connection,
                turn_id,
                user_id,
                "conversation_turn.purged",
                {},
                now,
            )
            connection.execute(
                "DELETE FROM conversation_turns WHERE id = ? AND user_id = ?",
                (turn_id, user_id),
            )

    def turn_pool(
        self,
        user_id: str,
        scope: MemoryScope,
        fts_query: str,
        pool_size: int,
        as_of: datetime,
        *,
        semantic_pool_size: int,
        minimum_semantic_similarity: float,
        query_embedding: list[float] | None = None,
        embedding_space: str | None = None,
        actor_id: str | None = None,
        exclude_turn_ids: list[str] | None = None,
        event_after: datetime | None = None,
        event_before: datetime | None = None,
        reality_layer: RealityLayer | None = None,
    ) -> list[TurnSearchCandidate]:
        clauses = [
            "conversation_turns.user_id = ?",
            "conversation_turns.deletion_state = ?",
            "conversation_turns.occurred_at <= ?",
        ]
        parameters: list[Any] = [
            user_id,
            TurnDeletionState.ACTIVE.value,
            datetime_to_text(as_of),
        ]
        scope_clauses, scope_parameters = self._exact_turn_scope_filter(scope)
        clauses.extend(scope_clauses)
        parameters.extend(scope_parameters)
        if exclude_turn_ids:
            placeholders = ", ".join("?" for _ in exclude_turn_ids)
            clauses.append(f"conversation_turns.id NOT IN ({placeholders})")
            parameters.extend(exclude_turn_ids)
        if actor_id is not None:
            clauses.append("conversation_turns.actor_id = ?")
            parameters.append(actor_id)
        if event_after is not None:
            clauses.append("conversation_turns.occurred_at >= ?")
            parameters.append(datetime_to_text(event_after))
        if event_before is not None:
            clauses.append("conversation_turns.occurred_at < ?")
            parameters.append(datetime_to_text(event_before))
        where = " AND ".join(clauses)
        realm_sql, realm_parameters = self._realm_filter("conversation_turns", reality_layer)
        where += realm_sql
        parameters.extend(realm_parameters)
        with self.database.connection() as connection:
            candidates: dict[str, TurnSearchCandidate] = {}
            if fts_query:
                rows = connection.execute(
                    f"""
                    SELECT conversation_turns.* FROM conversation_turns
                    JOIN turn_fts ON turn_fts.turn_id = conversation_turns.id
                    WHERE {where} AND turn_fts MATCH ?
                    ORDER BY bm25(turn_fts) LIMIT ?
                    """,
                    (*parameters, fts_query, pool_size),
                ).fetchall()
                for row in rows:
                    turn = self._row_to_turn(row)
                    candidates[turn.id] = TurnSearchCandidate(turn=turn, lexical_hit=True)
            recent_rows = connection.execute(
                f"""
                SELECT conversation_turns.* FROM conversation_turns
                WHERE {where} ORDER BY occurred_at DESC LIMIT ?
                """,
                (*parameters, pool_size),
            ).fetchall()
            for row in recent_rows:
                turn = self._row_to_turn(row)
                candidate = candidates.setdefault(turn.id, TurnSearchCandidate(turn=turn))
                candidate.recent_hit = True
            if query_embedding is not None and embedding_space is not None:
                semantic_query = SemanticQuery(
                    kind=SemanticKind.TURN,
                    reality_layer=reality_layer,
                    user_id=user_id,
                    scope=scope,
                    vector=query_embedding,
                    space=embedding_space,
                    as_of=as_of,
                    limit=semantic_pool_size,
                    minimum_similarity=minimum_semantic_similarity,
                    event_after=event_after,
                    event_before=event_before,
                    actor_id=actor_id,
                    exclude_ids=exclude_turn_ids or [],
                )
                for similarity, row in self._semantic_candidates(
                    connection, semantic_query, where, parameters
                ):
                    turn = self._row_to_turn(row)
                    candidate = candidates.setdefault(turn.id, TurnSearchCandidate(turn=turn))
                    candidate.semantic_similarity = similarity
        return list(candidates.values())

    def query_state(self, query: StateQuery) -> StateQueryResult:
        scope_clauses, scope_parameters = self._hierarchical_scope_filter("memories", query.scope)
        clauses = [
            "memories.user_id = ?",
            "memories.predicate = ?",
            "COALESCE(memories.subject_actor_id, memories.user_id) = ?",
            "memories.reality_layer = ?",
            "memories.status IN (?, ?)",
        ]
        parameters: list[Any] = [
            query.user_id,
            query.predicate,
            query.subject_actor_id or query.user_id,
            query.reality_layer.value,
            MemoryStatus.ACTIVE.value,
            MemoryStatus.SUPERSEDED.value,
        ]
        if query.semantics is AnswerSemantics.CHANGE_TRAJECTORY:
            clauses.append("memories.valid_from <= ?")
            parameters.append(datetime_to_text(query.known_at))
        else:
            clauses.extend(
                [
                    "memories.valid_time_start <= ?",
                    "(memories.valid_time_end IS NULL OR memories.valid_time_end > ?)",
                    "memories.valid_from <= ?",
                    "(memories.valid_to IS NULL OR memories.valid_to > ?)",
                ]
            )
            parameters.extend(
                [
                    datetime_to_text(query.valid_at),
                    datetime_to_text(query.valid_at),
                    datetime_to_text(query.known_at),
                    datetime_to_text(query.known_at),
                ]
            )
        clauses.extend(scope_clauses)
        parameters.extend(scope_parameters)
        if query.semantics is AnswerSemantics.LATEST_SELF_REPORT_ABOUT_TIME:
            clauses.append("memories.epistemic_kind = ?")
            parameters.append(EpistemicKind.DIRECT_SELF_REPORT.value)
        elif query.semantics is AnswerSemantics.CONTRACT_AT_TIME:
            clauses.append("memories.epistemic_kind = ?")
            parameters.append(EpistemicKind.RELATIONSHIP_CONTRACT.value)
        with self.database.connection() as connection:
            rows = connection.execute(
                f"SELECT * FROM memories WHERE {' AND '.join(clauses)} "
                "ORDER BY valid_time_start DESC, valid_from DESC",
                parameters,
            ).fetchall()
        memories = [self._row_to_memory(row) for row in rows]
        if not memories:
            resolution = ResolutionStatus.UNKNOWN
            reasons = ["no_qualified_state_evidence"]
        elif any(memory.resolution_status is not ResolutionStatus.RESOLVED for memory in memories):
            resolution = ResolutionStatus.CONTESTED
            reasons = ["state_contains_unresolved_evidence"]
        elif query.semantics is AnswerSemantics.CHANGE_TRAJECTORY:
            resolution = ResolutionStatus.RESOLVED
            reasons = ["state_change_trajectory"]
        elif len({memory.content.strip().casefold() for memory in memories}) > 1:
            resolution = ResolutionStatus.CONTESTED
            reasons = ["multiple_state_values_remain_valid"]
        else:
            resolution = ResolutionStatus.RESOLVED
            reasons = ["qualified_state_evidence"]
        return StateQueryResult(
            query=query,
            resolution_status=resolution,
            memories=memories,
            reasons=reasons,
        )

    def upsert_processing_watermark(self, item: ProcessingWatermarkInput) -> ChannelWatermark:
        now = utc_now()
        key = scope_key(item.scope)
        with self.database.connection() as connection:
            connection.execute(
                """
                INSERT INTO processing_watermarks (
                    user_id, scope_key, scope_json, channel, status, durable_sequence,
                    indexed_sequence, model_fingerprint, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, scope_key, channel) DO UPDATE SET
                    scope_json = excluded.scope_json,
                    status = excluded.status,
                    durable_sequence = excluded.durable_sequence,
                    indexed_sequence = excluded.indexed_sequence,
                    model_fingerprint = excluded.model_fingerprint,
                    updated_at = excluded.updated_at
                """,
                (
                    item.user_id,
                    key,
                    json.dumps(item.scope.model_dump(mode="json"), sort_keys=True),
                    item.channel,
                    item.status.value,
                    item.durable_sequence,
                    item.indexed_sequence,
                    item.model_fingerprint,
                    datetime_to_text(now),
                ),
            )
        return ChannelWatermark(
            channel=item.channel,
            status=item.status,
            durable_sequence=item.durable_sequence,
            indexed_sequence=item.indexed_sequence,
            model_fingerprint=item.model_fingerprint,
            updated_at=now,
        )

    def retrieval_integrity(
        self,
        user_id: str,
        scope: MemoryScope,
        ledger_enabled: bool,
        semantic_query_consumed: bool,
    ) -> RetrievalIntegrityManifest:
        key = scope_key(scope)
        scope_clauses, scope_parameters = self._exact_turn_scope_filter(scope)
        clauses = ["conversation_turns.user_id = ?", *scope_clauses]
        with self.database.connection() as connection:
            durable_row = connection.execute(
                f"SELECT MAX(server_sequence) FROM conversation_turns "
                f"WHERE {' AND '.join(clauses)}",
                (user_id, *scope_parameters),
            ).fetchone()
            rows = connection.execute(
                """
                SELECT * FROM processing_watermarks
                WHERE user_id = ? AND scope_key = ? ORDER BY channel
                """,
                (user_id, key),
            ).fetchall()
        durable_sequence = int(durable_row[0]) if durable_row[0] is not None else None
        channels = [
            ChannelWatermark(
                channel="raw_turn_fts",
                status=ChannelStatus.READY if ledger_enabled else ChannelStatus.DISABLED,
                durable_sequence=durable_sequence,
                indexed_sequence=durable_sequence if ledger_enabled else None,
                updated_at=utc_now(),
            )
        ]
        channels.extend(
            ChannelWatermark(
                channel=str(row["channel"]),
                status=ChannelStatus(str(row["status"])),
                durable_sequence=row["durable_sequence"],
                indexed_sequence=row["indexed_sequence"],
                model_fingerprint=row["model_fingerprint"],
                updated_at=datetime_from_text(row["updated_at"]),
            )
            for row in rows
        )
        semantic = next((item for item in channels if item.channel == "raw_turn_semantic"), None)
        semantic_index_complete = bool(
            semantic is not None
            and semantic.status is ChannelStatus.READY
            and semantic.durable_sequence == semantic.indexed_sequence
            and semantic.durable_sequence == durable_sequence
        )
        reasons: list[str] = []
        if not semantic_query_consumed:
            reasons.append("raw_semantic_query_not_requested")
        if not semantic_index_complete:
            reasons.append("raw_semantic_index_not_proven_complete")
        elif semantic_query_consumed:
            reasons.append("semantic_recall_is_not_proof_of_absence")
        if not ledger_enabled:
            reasons.append("conversation_ledger_disabled")
        return RetrievalIntegrityManifest(
            channels=channels,
            # A caught-up semantic index improves paraphrase recall but does not
            # turn embedding similarity into proof that an event never occurred.
            negative_claim_safe=False,
            reasons=reasons,
        )

    def record_memory_use(self, item: MemoryUseInput) -> MemoryUseRecord:
        memory = self.get(item.memory_id, item.user_id)
        if memory.status not in {MemoryStatus.ACTIVE, MemoryStatus.SUPERSEDED}:
            raise ValueError(
                "only active or historical superseded memories can be recorded as used"
            )
        if (
            memory.resolution_status is not ResolutionStatus.RESOLVED
            and item.use_mode is not RecallUseMode.DO_NOT_ASSERT
        ):
            raise ValueError("unresolved memories cannot be recorded as asserted")
        for column in SCOPE_COLUMNS:
            memory_value = getattr(memory.scope, column)
            if memory_value is not None and memory_value != getattr(item.scope, column):
                raise ValueError("memory cannot be used outside its stored scope")
        now = utc_now()
        use_id = str(uuid4())
        output_hash = (
            content_digest(item.rendered_excerpt) if item.rendered_excerpt is not None else None
        )
        with self.database.connection() as connection:
            connection.execute(
                """
                INSERT INTO memory_use_events (
                    id, user_id, companion_id, relationship_id, conversation_id, group_id,
                    memory_id, response_group_id, use_mode, use_type, purpose, output_hash,
                    used_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    use_id,
                    item.user_id,
                    *scope_values(item.scope),
                    item.memory_id,
                    item.response_group_id,
                    item.use_mode.value,
                    item.use_type.value
                    if item.use_type is not None
                    else MemoryUseType.EXPLICIT_REFERENCE.value,
                    item.purpose,
                    output_hash,
                    datetime_to_text(item.used_at),
                    datetime_to_text(now),
                ),
            )
            row = connection.execute(
                "SELECT * FROM memory_use_events WHERE id = ?", (use_id,)
            ).fetchone()
        return self._row_to_memory_use(cast(sqlite3.Row, row))

    def list_memory_uses(
        self, user_id: str, memory_id: str | None = None, limit: int | None = None
    ) -> list[MemoryUseRecord]:
        clauses = ["user_id = ?"]
        parameters: list[Any] = [user_id]
        if memory_id is not None:
            clauses.append("memory_id = ?")
            parameters.append(memory_id)
        query = (
            f"SELECT * FROM memory_use_events WHERE {' AND '.join(clauses)} ORDER BY used_at DESC"
        )
        if limit is not None:
            query += " LIMIT ?"
            parameters.append(limit)
        with self.database.connection() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._row_to_memory_use(row) for row in rows]

    def memory_use_summaries(self, user_id: str, memory_ids: list[str]) -> list[MemoryUseSummary]:
        if not memory_ids:
            return []
        placeholders = ", ".join("?" for _ in memory_ids)
        with self.database.connection() as connection:
            rows = connection.execute(
                f"""
                SELECT memory_id, COUNT(*) AS use_count, MAX(used_at) AS last_used_at
                FROM memory_use_events
                WHERE user_id = ? AND memory_id IN ({placeholders})
                GROUP BY memory_id
                """,
                (user_id, *memory_ids),
            ).fetchall()
        by_id = {str(row["memory_id"]): row for row in rows}
        return [
            MemoryUseSummary(
                memory_id=memory_id,
                use_count=int(by_id[memory_id]["use_count"]) if memory_id in by_id else 0,
                last_used_at=(
                    datetime_from_text(by_id[memory_id]["last_used_at"])
                    if memory_id in by_id
                    else None
                ),
            )
            for memory_id in memory_ids
        ]

    def used_memory_ids_since(
        self,
        user_id: str,
        scope: MemoryScope,
        memory_ids: list[str],
        since: datetime | None,
        as_of: datetime,
    ) -> set[str]:
        if not memory_ids:
            return set()
        placeholders = ", ".join("?" for _ in memory_ids)
        scope_clauses: list[str] = []
        scope_parameters: list[Any] = []
        for column in SCOPE_COLUMNS:
            scope_clauses.append(f"memory_use_events.{column} IS ?")
            scope_parameters.append(getattr(scope, column))
        time_clause = " AND used_at >= ?" if since is not None else ""
        time_parameters = [datetime_to_text(since)] if since is not None else []
        with self.database.connection() as connection:
            rows = connection.execute(
                f"""
                SELECT DISTINCT memory_id FROM memory_use_events
                WHERE user_id = ? AND {" AND ".join(scope_clauses)}
                  AND use_type != 'silent_influence'
                  AND used_at <= ? {time_clause} AND memory_id IN ({placeholders})
                """,
                (
                    user_id,
                    *scope_parameters,
                    datetime_to_text(as_of),
                    *time_parameters,
                    *memory_ids,
                ),
            ).fetchall()
        return {str(row["memory_id"]) for row in rows}

    def create_open_loop(self, item: OpenLoopInput) -> OpenLoopRecord:
        now = utc_now()
        open_loop_id = str(uuid4())
        with self.database.connection() as connection:
            if item.source_turn_id is not None:
                source = connection.execute(
                    "SELECT * FROM conversation_turns WHERE id = ? AND user_id = ?",
                    (item.source_turn_id, item.user_id),
                ).fetchone()
                if source is None or source["deletion_state"] != TurnDeletionState.ACTIVE.value:
                    raise ValueError("open-loop source turn is unavailable")
                if not self._evidence_scope_is_compatible(item.scope, source):
                    raise ValueError("open loop cannot widen its source turn scope")
            connection.execute(
                """
                INSERT INTO open_loops (
                    id, user_id, companion_id, relationship_id, conversation_id, group_id,
                    kind, summary, topic_keys_json, follow_up_mode, status, follow_up_after,
                    expires_at, source_turn_id, consent, sensitivity, resolution_summary,
                    last_followed_up_at, follow_up_count, last_response_group_id, revision,
                    opened_at, updated_at, resolved_at, metadata_json
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    open_loop_id,
                    item.user_id,
                    *scope_values(item.scope),
                    item.kind.value,
                    item.summary,
                    json.dumps(item.topic_keys, ensure_ascii=False),
                    item.follow_up_mode.value,
                    OpenLoopStatus.OPEN.value,
                    datetime_to_text(item.follow_up_after),
                    datetime_to_text(item.expires_at),
                    item.source_turn_id,
                    item.consent.value,
                    item.sensitivity.value,
                    None,
                    None,
                    0,
                    None,
                    1,
                    datetime_to_text(item.opened_at),
                    datetime_to_text(now),
                    None,
                    json.dumps(item.metadata, ensure_ascii=False, sort_keys=True),
                ),
            )
            self._audit(
                connection,
                open_loop_id,
                item.user_id,
                "open_loop.created",
                {"kind": item.kind.value, "follow_up_mode": item.follow_up_mode.value},
                now,
            )
            row = connection.execute(
                "SELECT * FROM open_loops WHERE id = ?", (open_loop_id,)
            ).fetchone()
        return self._row_to_open_loop(cast(sqlite3.Row, row))

    def get_open_loop(self, open_loop_id: str, user_id: str) -> OpenLoopRecord:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM open_loops WHERE id = ? AND user_id = ?",
                (open_loop_id, user_id),
            ).fetchone()
        if row is None:
            raise KeyError(open_loop_id)
        return self._row_to_open_loop(row)

    def list_open_loops(
        self,
        user_id: str,
        scope: MemoryScope | None = None,
        statuses: set[OpenLoopStatus] | None = None,
        limit: int | None = None,
    ) -> list[OpenLoopRecord]:
        clauses = ["open_loops.user_id = ?"]
        parameters: list[Any] = [user_id]
        if scope is not None:
            scope_clauses, scope_parameters = self._hierarchical_scope_filter("open_loops", scope)
            clauses.extend(scope_clauses)
            parameters.extend(scope_parameters)
        if statuses:
            placeholders = ", ".join("?" for _ in statuses)
            clauses.append(f"open_loops.status IN ({placeholders})")
            parameters.extend(status.value for status in statuses)
        query = (
            f"SELECT * FROM open_loops WHERE {' AND '.join(clauses)} "
            "ORDER BY COALESCE(follow_up_after, opened_at), opened_at, id"
        )
        if limit is not None:
            query += " LIMIT ?"
            parameters.append(limit)
        with self.database.connection() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._row_to_open_loop(row) for row in rows]

    def update_open_loop(self, open_loop_id: str, request: OpenLoopUpdateRequest) -> OpenLoopRecord:
        with self.database.connection() as connection:
            if not connection.in_transaction:
                connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM open_loops WHERE id = ? AND user_id = ?",
                (open_loop_id, request.user_id),
            ).fetchone()
            if row is None:
                raise KeyError(open_loop_id)
            current = self._row_to_open_loop(row)
            if (
                request.expected_revision is not None
                and request.expected_revision != current.revision
            ):
                raise ValueError("open-loop revision is stale")
            if request.source_turn_id is not None:
                source = connection.execute(
                    "SELECT * FROM conversation_turns WHERE id = ? AND user_id = ?",
                    (request.source_turn_id, request.user_id),
                ).fetchone()
                if source is None or source["deletion_state"] != TurnDeletionState.ACTIVE.value:
                    raise ValueError("open-loop update source turn is unavailable")
                if not self._evidence_scope_is_compatible(current.scope, source):
                    raise ValueError("open-loop update source is outside its relationship scope")

            closed = {OpenLoopStatus.RESOLVED, OpenLoopStatus.CANCELLED}
            if current.status in closed and request.transition is not OpenLoopTransition.REOPEN:
                return current
            status: OpenLoopStatus
            follow_up_after: datetime | None
            resolution_summary: str | None
            resolved_at: datetime | None
            last_followed_up_at: datetime | None
            follow_up_count: int
            response_group_id: str | None
            if request.transition is OpenLoopTransition.MARK_FOLLOWED_UP:
                if current.last_response_group_id == request.response_group_id:
                    return current
                if current.status is OpenLoopStatus.WAITING_FOR_REPLY:
                    raise ValueError("open loop is already waiting for the user's reply")
                status = OpenLoopStatus.WAITING_FOR_REPLY
                follow_up_after = current.follow_up_after
                resolution_summary = current.resolution_summary
                resolved_at = current.resolved_at
                last_followed_up_at = request.as_of
                follow_up_count = current.follow_up_count + 1
                response_group_id = request.response_group_id
            elif request.transition is OpenLoopTransition.SNOOZE:
                if (
                    current.expires_at is not None
                    and request.next_follow_up_at is not None
                    and request.next_follow_up_at >= current.expires_at
                ):
                    raise ValueError("cannot snooze beyond the open-loop expiry")
                status = OpenLoopStatus.SNOOZED
                follow_up_after = request.next_follow_up_at
                resolution_summary = current.resolution_summary
                resolved_at = current.resolved_at
                last_followed_up_at = current.last_followed_up_at
                follow_up_count = current.follow_up_count
                response_group_id = current.last_response_group_id
            elif request.transition is OpenLoopTransition.RESOLVE:
                status = OpenLoopStatus.RESOLVED
                follow_up_after = current.follow_up_after
                resolution_summary = request.resolution_summary
                resolved_at = request.as_of
                last_followed_up_at = current.last_followed_up_at
                follow_up_count = current.follow_up_count
                response_group_id = current.last_response_group_id
            elif request.transition is OpenLoopTransition.CANCEL:
                status = OpenLoopStatus.CANCELLED
                follow_up_after = current.follow_up_after
                resolution_summary = request.resolution_summary
                resolved_at = request.as_of
                last_followed_up_at = current.last_followed_up_at
                follow_up_count = current.follow_up_count
                response_group_id = current.last_response_group_id
            else:
                status = OpenLoopStatus.OPEN
                follow_up_after = request.next_follow_up_at or current.follow_up_after
                resolution_summary = None
                resolved_at = None
                last_followed_up_at = current.last_followed_up_at
                follow_up_count = current.follow_up_count
                response_group_id = current.last_response_group_id

            connection.execute(
                """
                UPDATE open_loops
                SET status = ?, follow_up_after = ?, resolution_summary = ?,
                    last_followed_up_at = ?, follow_up_count = ?,
                    last_response_group_id = ?, revision = revision + 1,
                    updated_at = ?, resolved_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (
                    status.value,
                    datetime_to_text(follow_up_after),
                    resolution_summary,
                    datetime_to_text(last_followed_up_at),
                    follow_up_count,
                    response_group_id,
                    datetime_to_text(request.as_of),
                    datetime_to_text(resolved_at),
                    open_loop_id,
                    request.user_id,
                ),
            )
            self._audit(
                connection,
                open_loop_id,
                request.user_id,
                f"open_loop.{request.transition.value}",
                {"status": status.value},
                request.as_of,
            )
            updated = connection.execute(
                "SELECT * FROM open_loops WHERE id = ?", (open_loop_id,)
            ).fetchone()
        return self._row_to_open_loop(cast(sqlite3.Row, updated))

    def record_reference_feedback(
        self, item: MemoryReferenceFeedbackInput
    ) -> MemoryReferenceFeedbackRecord:
        feedback_id = str(uuid4())
        now = utc_now()
        evidence_tables = {
            ExperienceEvidenceKind.MEMORY: "memories",
            ExperienceEvidenceKind.EVENT: "conversation_events",
            ExperienceEvidenceKind.TURN: "conversation_turns",
        }
        table = evidence_tables[item.evidence_kind]
        with self.database.connection() as connection:
            evidence = connection.execute(
                f"SELECT * FROM {table} WHERE id = ? AND user_id = ?",
                (item.evidence_id, item.user_id),
            ).fetchone()
            if evidence is None or not self._evidence_scope_is_compatible(item.scope, evidence):
                raise ValueError("reference-feedback target is unavailable in this scope")
            if item.source_turn_id is not None:
                source = connection.execute(
                    "SELECT * FROM conversation_turns WHERE id = ? AND user_id = ?",
                    (item.source_turn_id, item.user_id),
                ).fetchone()
                if source is None or source["deletion_state"] != TurnDeletionState.ACTIVE.value:
                    raise ValueError("reference-feedback source turn is unavailable")
                if not self._evidence_scope_is_compatible(item.scope, source):
                    raise ValueError("reference feedback cannot widen its source turn scope")
            connection.execute(
                """
                INSERT INTO memory_reference_feedback (
                    id, user_id, companion_id, relationship_id, conversation_id, group_id,
                    memory_id, evidence_kind, evidence_id, kind, source_turn_id, note,
                    recorded_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    feedback_id,
                    item.user_id,
                    *scope_values(item.scope),
                    item.memory_id,
                    item.evidence_kind.value,
                    item.evidence_id,
                    item.kind.value,
                    item.source_turn_id,
                    item.note,
                    datetime_to_text(item.recorded_at),
                    datetime_to_text(now),
                ),
            )
            row = connection.execute(
                "SELECT * FROM memory_reference_feedback WHERE id = ?", (feedback_id,)
            ).fetchone()
        return self._row_to_reference_feedback(cast(sqlite3.Row, row))

    def list_reference_feedback(
        self,
        user_id: str,
        scope: MemoryScope | None = None,
        memory_ids: list[str] | None = None,
        limit: int | None = None,
    ) -> list[MemoryReferenceFeedbackRecord]:
        clauses = ["memory_reference_feedback.user_id = ?"]
        parameters: list[Any] = [user_id]
        if scope is not None:
            scope_clauses, scope_parameters = self._hierarchical_scope_filter(
                "memory_reference_feedback", scope
            )
            clauses.extend(scope_clauses)
            parameters.extend(scope_parameters)
        if memory_ids:
            placeholders = ", ".join("?" for _ in memory_ids)
            clauses.append(f"memory_reference_feedback.memory_id IN ({placeholders})")
            parameters.extend(memory_ids)
        query = (
            f"SELECT * FROM memory_reference_feedback WHERE {' AND '.join(clauses)} "
            "ORDER BY recorded_at DESC, id DESC"
        )
        if limit is not None:
            query += " LIMIT ?"
            parameters.append(limit)
        with self.database.connection() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._row_to_reference_feedback(row) for row in rows]

    def latest_reference_feedback(
        self,
        user_id: str,
        scope: MemoryScope,
        evidence_refs: list[ExperienceEvidenceRef],
        as_of: datetime,
    ) -> dict[tuple[ExperienceEvidenceKind, str], MemoryReferenceFeedbackRecord]:
        if not evidence_refs:
            return {}
        scope_clauses, scope_parameters = self._hierarchical_scope_filter(
            "memory_reference_feedback", scope
        )
        targets = " OR ".join("(evidence_kind = ? AND evidence_id = ?)" for _ in evidence_refs)
        target_parameters = [value for ref in evidence_refs for value in (ref.kind.value, ref.id)]
        with self.database.connection() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM memory_reference_feedback
                WHERE user_id = ? AND {" AND ".join(scope_clauses)}
                  AND recorded_at <= ? AND ({targets})
                ORDER BY recorded_at DESC, created_at DESC, id DESC
                """,
                (user_id, *scope_parameters, datetime_to_text(as_of), *target_parameters),
            ).fetchall()
        latest: dict[tuple[ExperienceEvidenceKind, str], MemoryReferenceFeedbackRecord] = {}
        for row in rows:
            item = self._row_to_reference_feedback(row)
            latest.setdefault((item.evidence_kind, item.evidence_id), item)
        return latest

    def used_experience_evidence_since(
        self,
        user_id: str,
        scope: MemoryScope,
        evidence_refs: list[ExperienceEvidenceRef],
        since: datetime | None,
        as_of: datetime,
    ) -> set[tuple[ExperienceEvidenceKind, str]]:
        if not evidence_refs:
            return set()
        scope_clauses = [f"response_plans.{column} IS ?" for column in SCOPE_COLUMNS]
        targets = " OR ".join("(evidence_kind = ? AND evidence_id = ?)" for _ in evidence_refs)
        target_parameters = [value for ref in evidence_refs for value in (ref.kind.value, ref.id)]
        time_clause = " AND used_at >= ?" if since is not None else ""
        time_parameters = [datetime_to_text(since)] if since is not None else []
        with self.database.connection() as connection:
            rows = connection.execute(
                f"""
                SELECT DISTINCT evidence_kind, evidence_id FROM experience_evidence_uses
                JOIN response_plans ON response_plans.id = experience_evidence_uses.plan_id
                WHERE response_plans.user_id = ? AND {" AND ".join(scope_clauses)}
                  AND used_at <= ? {time_clause} AND ({targets})
                """,
                (
                    user_id,
                    *scope_values(scope),
                    datetime_to_text(as_of),
                    *time_parameters,
                    *target_parameters,
                ),
            ).fetchall()
        return {
            (ExperienceEvidenceKind(row["evidence_kind"]), str(row["evidence_id"])) for row in rows
        }

    def latest_used_experience_evidence(
        self, user_id: str, scope: MemoryScope
    ) -> list[ExperienceEvidenceRef]:
        scope_clauses = [f"response_plans.{column} IS ?" for column in SCOPE_COLUMNS]
        with self.database.connection() as connection:
            latest = connection.execute(
                f"""
                SELECT beat_id FROM experience_evidence_uses
                JOIN response_plans ON response_plans.id = experience_evidence_uses.plan_id
                WHERE response_plans.user_id = ? AND {" AND ".join(scope_clauses)}
                ORDER BY used_at DESC, beat_id DESC
                """,
                (user_id, *scope_values(scope)),
            ).fetchone()
            if latest is None:
                return []
            rows = connection.execute(
                """
                SELECT DISTINCT evidence_kind, evidence_id FROM experience_evidence_uses
                WHERE beat_id = ?
                ORDER BY evidence_kind, evidence_id
                """,
                (latest["beat_id"],),
            ).fetchall()
        return [
            ExperienceEvidenceRef(kind=row["evidence_kind"], id=str(row["evidence_id"]))
            for row in rows
        ]

    def create_response_plan(
        self,
        plan: ResponsePlanRecord,
        resolution_request: ResponsePlanRequest | None = None,
    ) -> ResponsePlanRecord:
        with self.database.connection() as connection:
            if not connection.in_transaction:
                connection.execute("BEGIN IMMEDIATE")
            trigger = connection.execute(
                "SELECT * FROM conversation_turns WHERE id = ? AND user_id = ?",
                (plan.trigger_turn_id, plan.user_id),
            ).fetchone()
            if (
                trigger is None
                or trigger["deletion_state"] != TurnDeletionState.ACTIVE.value
                or trigger["role"] != ConversationRole.USER.value
                or any(trigger[column] != getattr(plan.scope, column) for column in SCOPE_COLUMNS)
            ):
                raise ValueError("response plan trigger must belong to its exact scope")
            scope_clauses = [f"{column} IS ?" for column in SCOPE_COLUMNS]
            newer_turn = connection.execute(
                f"""
                SELECT id FROM conversation_turns
                WHERE user_id = ? AND {" AND ".join(scope_clauses)}
                  AND role = ? AND deletion_state = ? AND server_sequence > ?
                LIMIT 1
                """,
                (
                    plan.user_id,
                    *scope_values(plan.scope),
                    ConversationRole.USER.value,
                    TurnDeletionState.ACTIVE.value,
                    trigger["server_sequence"],
                ),
            ).fetchone()
            if newer_turn is not None:
                raise ValueError("a newer user turn arrived; replan for the current turn")
            self._cancel_active_response_plans(
                connection,
                plan.user_id,
                plan.scope,
                "response_replanned",
                plan.created_at,
                interrupt_only=False,
            )
            connection.execute(
                """
                INSERT INTO response_plans (
                    id, response_group_id, user_id, companion_id, relationship_id,
                    conversation_id, group_id, trigger_turn_id, goal, delivery_mode,
                    status, revision, resolution_status, resolution_request_json,
                    resolution_key, policy_version, config_fingerprint, policy_bundle_json,
                    cancel_on_new_user_turn, recall_action,
                    memory_use_plan_json, follow_up_json, created_at, updated_at,
                    resolved_at, cancelled_at, cancellation_reason
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    plan.id,
                    plan.response_group_id,
                    plan.user_id,
                    *scope_values(plan.scope),
                    plan.trigger_turn_id,
                    plan.goal.value,
                    plan.delivery_mode.value,
                    plan.status.value,
                    plan.revision,
                    plan.resolution_status.value,
                    (
                        json.dumps(resolution_request.model_dump(mode="json"), ensure_ascii=False)
                        if resolution_request is not None
                        else None
                    ),
                    None,
                    plan.policy_version,
                    plan.config_fingerprint,
                    json.dumps(plan.policy_bundle.model_dump(mode="json"), ensure_ascii=False),
                    int(plan.cancel_on_new_user_turn),
                    plan.recall_action.value if plan.recall_action is not None else None,
                    json.dumps(plan.memory_use_plan.model_dump(mode="json"), ensure_ascii=False),
                    (
                        json.dumps(plan.follow_up.model_dump(mode="json"), ensure_ascii=False)
                        if plan.follow_up is not None
                        else None
                    ),
                    datetime_to_text(plan.created_at),
                    datetime_to_text(plan.updated_at),
                    datetime_to_text(plan.resolved_at),
                    datetime_to_text(plan.cancelled_at),
                    plan.cancellation_reason,
                ),
            )
            for beat in plan.beats:
                connection.execute(
                    """
                    INSERT INTO response_beats (
                        id, plan_id, ordinal, kind, source, release_condition, status,
                        guidance, evidence_json, output_hash, sent_at, cancelled_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        beat.id,
                        plan.id,
                        beat.ordinal,
                        beat.kind.value,
                        beat.source.value,
                        beat.release_condition.value,
                        beat.status.value,
                        beat.guidance,
                        json.dumps(
                            [item.model_dump(mode="json") for item in beat.evidence],
                            ensure_ascii=False,
                        ),
                        beat.output_hash,
                        datetime_to_text(beat.sent_at),
                        datetime_to_text(beat.cancelled_at),
                    ),
                )
        return self.get_response_plan(plan.id, plan.user_id)

    def get_response_resolution_request(self, plan_id: str, user_id: str) -> ResponsePlanRequest:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT resolution_request_json FROM response_plans WHERE id = ? AND user_id = ?",
                (plan_id, user_id),
            ).fetchone()
        if row is None:
            raise KeyError(plan_id)
        if row["resolution_request_json"] is None:
            raise ValueError("response plan has no pending resolution request")
        return ResponsePlanRequest.model_validate_json(str(row["resolution_request_json"]))

    def resolve_response_plan(
        self,
        plan_id: str,
        user_id: str,
        expected_revision: int,
        resolution_key: str,
        recall_action: str | None,
        memory_use_plan: MemoryUsePlan,
        follow_up: FollowUpDecision | None,
        continuation_beats: list[ResponseBeatRecord],
        as_of: datetime,
    ) -> ResponsePlanRecord:
        with self.database.connection() as connection:
            if not connection.in_transaction:
                connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM response_plans WHERE id = ? AND user_id = ?",
                (plan_id, user_id),
            ).fetchone()
            if row is None:
                raise KeyError(plan_id)
            if row["resolution_status"] == ResponsePlanResolutionStatus.RESOLVED.value:
                if row["resolution_key"] != resolution_key:
                    raise ValueError("response plan was resolved by a different request")
                beat_rows = connection.execute(
                    "SELECT * FROM response_beats WHERE plan_id = ? ORDER BY ordinal",
                    (plan_id,),
                ).fetchall()
                return self._row_to_response_plan(row, beat_rows)
            if row["status"] != ResponsePlanStatus.ACTIVE.value:
                raise ValueError("cancelled or completed response plans cannot be resolved")
            if int(row["revision"]) != expected_revision:
                raise ValueError("response plan revision changed; discard stale retrieval")
            if int(row["policy_version"]) != self._policy_version(connection, user_id):
                raise ValueError("response plan policy version changed; replan before resolving")
            trigger = connection.execute(
                "SELECT server_sequence FROM conversation_turns WHERE id = ? AND user_id = ?",
                (row["trigger_turn_id"], user_id),
            ).fetchone()
            if trigger is None:
                raise ValueError("response plan trigger no longer exists")
            scope = scope_from_row(row)
            scope_clauses = [f"{column} IS ?" for column in SCOPE_COLUMNS]
            newer = connection.execute(
                "SELECT 1 FROM conversation_turns WHERE user_id = ? AND "
                f"{' AND '.join(scope_clauses)} "
                "AND role = ? AND deletion_state = ? AND server_sequence > ? LIMIT 1",
                (
                    user_id,
                    *scope_values(scope),
                    ConversationRole.USER.value,
                    TurnDeletionState.ACTIVE.value,
                    trigger["server_sequence"],
                ),
            ).fetchone()
            if newer is not None:
                raise ValueError("a newer user turn arrived; discard stale retrieval")
            prior = connection.execute(
                "SELECT status FROM response_beats WHERE plan_id = ? ORDER BY ordinal LIMIT 1",
                (plan_id,),
            ).fetchone()
            first_sent = prior is not None and prior["status"] == ResponseBeatStatus.SENT.value
            for offset, beat in enumerate(continuation_beats, start=1):
                beat_status = (
                    ResponseBeatStatus.READY
                    if offset == 1 and first_sent
                    else ResponseBeatStatus.PENDING
                )
                connection.execute(
                    """
                    INSERT INTO response_beats (
                        id, plan_id, ordinal, kind, source, release_condition, status,
                        guidance, evidence_json, output_hash, sent_at, cancelled_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        beat.id,
                        plan_id,
                        offset,
                        beat.kind.value,
                        beat.source.value,
                        beat.release_condition.value,
                        beat_status.value,
                        beat.guidance,
                        json.dumps(
                            [item.model_dump(mode="json") for item in beat.evidence],
                            ensure_ascii=False,
                        ),
                        None,
                        None,
                        None,
                    ),
                )
            next_revision = expected_revision + 1
            remaining = connection.execute(
                "SELECT 1 FROM response_beats WHERE plan_id = ? AND status IN (?, ?) LIMIT 1",
                (plan_id, ResponseBeatStatus.READY.value, ResponseBeatStatus.PENDING.value),
            ).fetchone()
            plan_status = (
                ResponsePlanStatus.ACTIVE if remaining is not None else ResponsePlanStatus.COMPLETED
            )
            connection.execute(
                """
                UPDATE response_plans
                SET status = ?, revision = ?, resolution_status = ?, resolution_key = ?,
                    recall_action = ?, memory_use_plan_json = ?, follow_up_json = ?,
                    resolution_request_json = NULL, resolved_at = ?, updated_at = ?
                WHERE id = ? AND user_id = ? AND revision = ?
                """,
                (
                    plan_status.value,
                    next_revision,
                    ResponsePlanResolutionStatus.RESOLVED.value,
                    resolution_key,
                    recall_action,
                    json.dumps(memory_use_plan.model_dump(mode="json"), ensure_ascii=False),
                    json.dumps(follow_up.model_dump(mode="json"), ensure_ascii=False)
                    if follow_up is not None
                    else None,
                    datetime_to_text(as_of),
                    datetime_to_text(as_of),
                    plan_id,
                    user_id,
                    expected_revision,
                ),
            )
        return self.get_response_plan(plan_id, user_id)

    def get_response_plan(self, plan_id: str, user_id: str) -> ResponsePlanRecord:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM response_plans WHERE id = ? AND user_id = ?",
                (plan_id, user_id),
            ).fetchone()
            if row is None:
                raise KeyError(plan_id)
            beat_rows = connection.execute(
                "SELECT * FROM response_beats WHERE plan_id = ? ORDER BY ordinal", (plan_id,)
            ).fetchall()
        return self._row_to_response_plan(row, beat_rows)

    def list_response_plans(
        self,
        user_id: str,
        scope: MemoryScope | None = None,
        statuses: set[ResponsePlanStatus] | None = None,
        limit: int | None = None,
    ) -> list[ResponsePlanRecord]:
        clauses = ["user_id = ?"]
        parameters: list[Any] = [user_id]
        if scope is not None:
            for column in SCOPE_COLUMNS:
                clauses.append(f"{column} IS ?")
                parameters.append(getattr(scope, column))
        if statuses:
            placeholders = ", ".join("?" for _ in statuses)
            clauses.append(f"status IN ({placeholders})")
            parameters.extend(status.value for status in statuses)
        query = (
            f"SELECT id FROM response_plans WHERE {' AND '.join(clauses)} ORDER BY created_at DESC"
        )
        if limit is not None:
            query += " LIMIT ?"
            parameters.append(limit)
        with self.database.connection() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self.get_response_plan(str(row["id"]), user_id) for row in rows]

    def interrupt_response_plans(self, request: ResponsePlanInterruptRequest) -> list[str]:
        with self.database.connection() as connection:
            if not connection.in_transaction:
                connection.execute("BEGIN IMMEDIATE")
            return self._cancel_active_response_plans(
                connection,
                request.user_id,
                request.scope,
                request.reason,
                request.as_of,
                interrupt_only=True,
            )

    @staticmethod
    def _cancel_active_response_plans(
        connection: sqlite3.Connection,
        user_id: str,
        scope: MemoryScope,
        reason: str,
        as_of: datetime,
        *,
        interrupt_only: bool,
    ) -> list[str]:
        clauses = ["user_id = ?", "status = ?"]
        if interrupt_only:
            clauses.append("cancel_on_new_user_turn = 1")
        parameters: list[Any] = [user_id, ResponsePlanStatus.ACTIVE.value]
        for column in SCOPE_COLUMNS:
            clauses.append(f"{column} IS ?")
            parameters.append(getattr(scope, column))
        rows = connection.execute(
            f"SELECT id FROM response_plans WHERE {' AND '.join(clauses)}",
            parameters,
        ).fetchall()
        plan_ids = [str(row["id"]) for row in rows]
        if not plan_ids:
            return []
        placeholders = ", ".join("?" for _ in plan_ids)
        connection.execute(
            f"""
            UPDATE response_plans
            SET status = ?, resolution_request_json = NULL,
                updated_at = ?, cancelled_at = ?, cancellation_reason = ?
            WHERE id IN ({placeholders})
            """,
            (
                ResponsePlanStatus.CANCELLED.value,
                datetime_to_text(as_of),
                datetime_to_text(as_of),
                reason,
                *plan_ids,
            ),
        )
        connection.execute(
            f"""
            UPDATE response_beats SET status = ?, cancelled_at = ?
            WHERE plan_id IN ({placeholders}) AND status IN (?, ?)
            """,
            (
                ResponseBeatStatus.CANCELLED.value,
                datetime_to_text(as_of),
                *plan_ids,
                ResponseBeatStatus.READY.value,
                ResponseBeatStatus.PENDING.value,
            ),
        )
        return plan_ids

    def cancel_response_plan(
        self, plan_id: str, user_id: str, reason: str, as_of: datetime
    ) -> ResponsePlanRecord:
        plan = self.get_response_plan(plan_id, user_id)
        if plan.status is not ResponsePlanStatus.ACTIVE:
            return plan
        with self.database.connection() as connection:
            if not connection.in_transaction:
                connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE response_plans
                SET status = ?, resolution_request_json = NULL,
                    updated_at = ?, cancelled_at = ?, cancellation_reason = ?
                WHERE id = ? AND user_id = ? AND status = ?
                """,
                (
                    ResponsePlanStatus.CANCELLED.value,
                    datetime_to_text(as_of),
                    datetime_to_text(as_of),
                    reason,
                    plan_id,
                    user_id,
                    ResponsePlanStatus.ACTIVE.value,
                ),
            )
            connection.execute(
                """
                UPDATE response_beats SET status = ?, cancelled_at = ?
                WHERE plan_id = ? AND status IN (?, ?)
                """,
                (
                    ResponseBeatStatus.CANCELLED.value,
                    datetime_to_text(as_of),
                    plan_id,
                    ResponseBeatStatus.READY.value,
                    ResponseBeatStatus.PENDING.value,
                ),
            )
        return self.get_response_plan(plan_id, user_id)

    def mark_response_beat_sent(
        self,
        plan_id: str,
        beat_id: str,
        user_id: str,
        output_hash: str,
        task_policy_version: int,
        sent_at: datetime,
        host_release_signal: bool = False,
        silently_used_memory_ids: list[str] | None = None,
    ) -> ResponsePlanRecord:
        with self.database.connection() as connection:
            if not connection.in_transaction:
                connection.execute("BEGIN IMMEDIATE")
            plan_row = connection.execute(
                "SELECT * FROM response_plans WHERE id = ? AND user_id = ?",
                (plan_id, user_id),
            ).fetchone()
            if plan_row is None:
                raise KeyError(plan_id)
            beat = connection.execute(
                "SELECT * FROM response_beats WHERE id = ? AND plan_id = ?",
                (beat_id, plan_id),
            ).fetchone()
            if beat is None:
                raise KeyError(beat_id)
            if beat["status"] == ResponseBeatStatus.SENT.value:
                if beat["output_hash"] != output_hash:
                    raise ValueError("a sent beat cannot be acknowledged with different text")
                beat_rows = connection.execute(
                    "SELECT * FROM response_beats WHERE plan_id = ? ORDER BY ordinal",
                    (plan_id,),
                ).fetchall()
                return self._row_to_response_plan(plan_row, beat_rows)
            if plan_row["status"] != ResponsePlanStatus.ACTIVE.value:
                raise ValueError("only active response plans can send beats")
            current_policy_version = self._policy_version(connection, user_id)
            if (
                task_policy_version != int(plan_row["policy_version"])
                or task_policy_version != current_policy_version
            ):
                raise ValueError("response plan policy version is stale")
            if beat["status"] not in {
                ResponseBeatStatus.READY.value,
                ResponseBeatStatus.PENDING.value,
            }:
                raise ValueError("response beat is not sendable")
            if (
                beat["release_condition"] == BeatReleaseCondition.HOST_SIGNAL.value
                and not host_release_signal
            ):
                raise ValueError("this optional beat requires a host release signal")
            earlier = connection.execute(
                """
                SELECT 1 FROM response_beats
                WHERE plan_id = ? AND ordinal < ? AND status NOT IN (?, ?)
                LIMIT 1
                """,
                (
                    plan_id,
                    beat["ordinal"],
                    ResponseBeatStatus.SENT.value,
                    ResponseBeatStatus.CANCELLED.value,
                ),
            ).fetchone()
            if earlier is not None:
                raise ValueError("response beats must be sent in semantic order")
            evidence = self._row_to_response_beat(beat).evidence
            follow_up = (
                FollowUpDecision.model_validate_json(str(plan_row["follow_up_json"]))
                if plan_row["follow_up_json"] is not None
                else None
            )
            for item in evidence:
                if item.kind is not ExperienceEvidenceKind.OPEN_LOOP:
                    continue
                loop_row = connection.execute(
                    "SELECT * FROM open_loops WHERE id = ? AND user_id = ?",
                    (item.id, user_id),
                ).fetchone()
                candidate = follow_up.candidate if follow_up is not None else None
                if (
                    loop_row is None
                    or candidate is None
                    or candidate.id != item.id
                    or int(loop_row["revision"]) != candidate.revision
                    or loop_row["status"]
                    not in {OpenLoopStatus.OPEN.value, OpenLoopStatus.SNOOZED.value}
                ):
                    raise ValueError("follow-up changed after planning; replan before sending")
                expires_at = datetime_from_text(loop_row["expires_at"])
                follow_up_after = datetime_from_text(loop_row["follow_up_after"])
                if (expires_at is not None and expires_at <= sent_at) or (
                    follow_up_after is not None and follow_up_after > sent_at
                ):
                    raise ValueError("follow-up is no longer due")
            connection.execute(
                """
                UPDATE response_beats
                SET status = ?, output_hash = ?, sent_at = ?
                WHERE id = ? AND plan_id = ?
                """,
                (
                    ResponseBeatStatus.SENT.value,
                    output_hash,
                    datetime_to_text(sent_at),
                    beat_id,
                    plan_id,
                ),
            )
            for item in evidence:
                if item.kind is not ExperienceEvidenceKind.OPEN_LOOP:
                    continue
                connection.execute(
                    """
                    UPDATE open_loops
                    SET status = ?, last_followed_up_at = ?,
                        follow_up_count = follow_up_count + 1,
                        last_response_group_id = ?, revision = revision + 1,
                        updated_at = ?
                    WHERE id = ? AND user_id = ?
                    """,
                    (
                        OpenLoopStatus.WAITING_FOR_REPLY.value,
                        datetime_to_text(sent_at),
                        plan_row["response_group_id"],
                        datetime_to_text(sent_at),
                        item.id,
                        user_id,
                    ),
                )

            use_plan = MemoryUsePlan.model_validate_json(str(plan_row["memory_use_plan_json"]))
            reference_modes = {
                decision.evidence.id: decision.mode
                for decision in use_plan.decisions
                if decision.evidence.kind is ExperienceEvidenceKind.MEMORY
            }
            mode_map = {
                MemoryReferenceMode.EXPLICIT_RECALL: RecallUseMode.NATURAL,
                MemoryReferenceMode.SOFT_REFERENCE: RecallUseMode.HEDGE,
                MemoryReferenceMode.CLARIFY: RecallUseMode.DO_NOT_ASSERT,
            }
            type_map = {
                MemoryReferenceMode.EXPLICIT_RECALL: MemoryUseType.EXPLICIT_REFERENCE,
                MemoryReferenceMode.SOFT_REFERENCE: MemoryUseType.SOFT_REFERENCE,
                MemoryReferenceMode.CLARIFY: MemoryUseType.CLARIFICATION,
            }
            plan_scope = scope_from_row(plan_row)
            for item in evidence:
                if not self.database.config.memory_use_ledger.enabled:
                    continue
                connection.execute(
                    """
                    INSERT OR IGNORE INTO experience_evidence_uses
                        (beat_id, plan_id, evidence_kind, evidence_id, used_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (beat_id, plan_id, item.kind.value, item.id, datetime_to_text(sent_at)),
                )
                if item.kind is not ExperienceEvidenceKind.MEMORY:
                    continue
                memory_id = item.id
                reference_mode = reference_modes.get(memory_id, MemoryReferenceMode.SUPPRESS)
                use_mode = mode_map.get(reference_mode)
                if use_mode is None:
                    continue
                connection.execute(
                    """
                    INSERT INTO memory_use_events (
                        id, user_id, companion_id, relationship_id, conversation_id,
                        group_id, memory_id, response_group_id, use_mode, use_type, purpose,
                        output_hash, used_at, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid4()),
                        user_id,
                        *scope_values(plan_scope),
                        memory_id,
                        plan_row["response_group_id"],
                        use_mode.value,
                        type_map[reference_mode].value,
                        f"response_beat:{beat['kind']}",
                        output_hash,
                        datetime_to_text(sent_at),
                        datetime_to_text(sent_at),
                    ),
                )
            for memory_id in dict.fromkeys(silently_used_memory_ids or []):
                if reference_modes.get(memory_id) is not MemoryReferenceMode.SILENT_INFLUENCE:
                    raise ValueError("silent use must refer to a planned silent memory")
                if not self.database.config.memory_use_ledger.enabled:
                    continue
                previous_use = connection.execute(
                    "SELECT 1 FROM memory_use_events WHERE user_id = ? AND memory_id = ? "
                    "AND response_group_id = ? AND use_type = ?",
                    (
                        user_id,
                        memory_id,
                        plan_row["response_group_id"],
                        MemoryUseType.SILENT_INFLUENCE.value,
                    ),
                ).fetchone()
                if previous_use is None:
                    self.record_memory_use(
                        MemoryUseInput(
                            user_id=user_id,
                            scope=plan_scope,
                            memory_id=memory_id,
                            response_group_id=plan_row["response_group_id"],
                            use_mode=RecallUseMode.DO_NOT_ASSERT,
                            use_type=MemoryUseType.SILENT_INFLUENCE,
                            purpose="host_confirmed_response_influence",
                            used_at=sent_at,
                        )
                    )
            connection.execute(
                """
                UPDATE response_beats SET status = ?
                WHERE plan_id = ? AND status = ? AND release_condition = ?
                  AND ordinal = (
                    SELECT MIN(ordinal) FROM response_beats
                    WHERE plan_id = ? AND status = ?
                  )
                """,
                (
                    ResponseBeatStatus.READY.value,
                    plan_id,
                    ResponseBeatStatus.PENDING.value,
                    BeatReleaseCondition.PREVIOUS_BEAT_SENT.value,
                    plan_id,
                    ResponseBeatStatus.PENDING.value,
                ),
            )
            remaining = connection.execute(
                "SELECT 1 FROM response_beats WHERE plan_id = ? AND status IN (?, ?) LIMIT 1",
                (
                    plan_id,
                    ResponseBeatStatus.READY.value,
                    ResponseBeatStatus.PENDING.value,
                ),
            ).fetchone()
            status = (
                ResponsePlanStatus.ACTIVE
                if remaining is not None
                or plan_row["resolution_status"] == ResponsePlanResolutionStatus.PENDING.value
                else ResponsePlanStatus.COMPLETED
            )
            connection.execute(
                "UPDATE response_plans SET status = ?, updated_at = ? WHERE id = ?",
                (status.value, datetime_to_text(sent_at), plan_id),
            )
        return self.get_response_plan(plan_id, user_id)

    def create_policy_constraint(self, item: PolicyConstraintInput) -> PolicyConstraintRecord:
        now = utc_now()
        constraint_id = str(uuid4())
        with self.database.connection() as connection:
            if item.source_turn_id is not None:
                source = connection.execute(
                    "SELECT user_id, companion_id, relationship_id, conversation_id, group_id, "
                    "actor_id, role, speech_spans_json, deletion_state "
                    "FROM conversation_turns WHERE id = ?",
                    (item.source_turn_id,),
                ).fetchone()
                if source is None or source["user_id"] != item.user_id:
                    raise ValueError("policy source turn must belong to the same user")
                if source["deletion_state"] != TurnDeletionState.ACTIVE.value:
                    raise ValueError("forgotten turns cannot create a new policy constraint")
                if source["role"] != ConversationRole.USER.value:
                    raise ValueError(
                        "source-backed policy constraints require a user-authored turn"
                    )
                if not self._turn_has_direct_user_evidence(source):
                    raise ValueError("quoted or fictional speech cannot create a policy constraint")
                if item.scope.is_global:
                    raise ValueError(
                        "source-backed policy constraints require a non-global target scope"
                    )
                if not self._evidence_scope_is_compatible(item.scope, source):
                    raise ValueError("policy source turn cannot widen the target policy scope")
            current = connection.execute(
                """
                SELECT * FROM policy_constraints
                WHERE user_id = ?
                  AND companion_id IS ? AND relationship_id IS ?
                  AND conversation_id IS ? AND group_id IS ?
                  AND action = ? AND channel = ? AND status = ?
                ORDER BY version DESC LIMIT 1
                """,
                (
                    item.user_id,
                    *scope_values(item.scope),
                    item.action.casefold(),
                    item.channel.casefold(),
                    PolicyConstraintStatus.ACTIVE.value,
                ),
            ).fetchone()
            supersedes_id = str(current["id"]) if current is not None else None
            version = self._next_policy_version(connection, item.user_id, now)
            if supersedes_id is not None:
                if item.valid_from > now:
                    existing_until = datetime_from_text(current["valid_until"])
                    replacement_at = (
                        item.valid_from
                        if existing_until is None
                        else min(existing_until, item.valid_from)
                    )
                    connection.execute(
                        "UPDATE policy_constraints SET valid_until = ? WHERE id = ?",
                        (datetime_to_text(replacement_at), supersedes_id),
                    )
                else:
                    connection.execute(
                        "UPDATE policy_constraints SET status = ? WHERE id = ?",
                        (PolicyConstraintStatus.SUPERSEDED.value, supersedes_id),
                    )
            connection.execute(
                """
                INSERT INTO policy_constraints (
                    id, user_id, companion_id, relationship_id, conversation_id, group_id,
                    action, channel, effect, status, version, valid_from, valid_until,
                    source_turn_id, reason_code, supersedes_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    constraint_id,
                    item.user_id,
                    *scope_values(item.scope),
                    item.action.casefold(),
                    item.channel.casefold(),
                    item.effect.value,
                    PolicyConstraintStatus.ACTIVE.value,
                    version,
                    datetime_to_text(item.valid_from),
                    datetime_to_text(item.valid_until),
                    item.source_turn_id,
                    item.reason_code,
                    supersedes_id,
                    datetime_to_text(now),
                ),
            )
            self._audit(
                connection,
                constraint_id,
                item.user_id,
                "policy_constraint.created",
                {"action": item.action.casefold(), "effect": item.effect.value, "version": version},
                now,
            )
            row = connection.execute(
                "SELECT * FROM policy_constraints WHERE id = ?", (constraint_id,)
            ).fetchone()
        return self._row_to_policy_constraint(cast(sqlite3.Row, row))

    def evaluate_policy(
        self, request: PolicyGateRequest, default_allow: bool
    ) -> PolicyGateDecision:
        scope_clauses, scope_parameters = self._hierarchical_scope_filter(
            "policy_constraints", request.scope
        )
        placeholders = ", ".join("?" for _ in request.actions)
        with self.database.connection() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM policy_constraints
                WHERE user_id = ? AND status = ?
                  AND action IN ({placeholders})
                  AND channel IN (?, 'all')
                  AND valid_from <= ?
                  AND (valid_until IS NULL OR valid_until > ?)
                  AND {" AND ".join(scope_clauses)}
                """,
                (
                    request.user_id,
                    PolicyConstraintStatus.ACTIVE.value,
                    *request.actions,
                    request.channel.casefold(),
                    datetime_to_text(request.as_of),
                    datetime_to_text(request.as_of),
                    *scope_parameters,
                ),
            ).fetchall()
            current_version = self._policy_version(connection, request.user_id)
        records = [self._row_to_policy_constraint(row) for row in rows]
        selected: list[PolicyConstraintRecord] = []
        for action in request.actions:
            matching = [record for record in records if record.action == action]
            if not matching:
                continue
            # Policy statements are explicit, versioned user instructions.
            # The newest applicable instruction wins; specificity and channel
            # specificity break ties at the same version.
            matching.sort(
                key=lambda record: (
                    record.version,
                    sum(value is not None for value in record.scope.model_dump().values()),
                    record.channel == request.channel.casefold(),
                ),
                reverse=True,
            )
            selected.append(matching[0])
        blocked = [
            record.action
            for record in selected
            if record.effect in {PolicyEffect.DENY, PolicyEffect.FREEZE}
        ]
        missing = [
            action
            for action in request.actions
            if action not in {record.action for record in selected}
        ]
        stale_task = (
            request.task_policy_version is not None
            and request.task_policy_version != current_version
        )
        if stale_task:
            blocked = list(request.actions)
        allowed = not blocked and (default_allow or not missing)
        reasons = ["policy_constraint_blocked"] if blocked and not stale_task else []
        if stale_task:
            reasons.append("stale_policy_version")
        if missing and not default_allow:
            reasons.append("no_allow_constraint")
        if allowed:
            reasons.append("policy_gate_passed")
        return PolicyGateDecision(
            allowed=allowed,
            policy_version=current_version,
            blocked_actions=blocked,
            applied_constraints=selected,
            reasons=reasons,
        )

    def list_policy_constraints(
        self, user_id: str, limit: int | None = None
    ) -> list[PolicyConstraintRecord]:
        query = "SELECT * FROM policy_constraints WHERE user_id = ? ORDER BY version DESC"
        parameters: list[Any] = [user_id]
        if limit is not None:
            query += " LIMIT ?"
            parameters.append(limit)
        with self.database.connection() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._row_to_policy_constraint(row) for row in rows]

    def revoke_policy_constraint(self, constraint_id: str, user_id: str) -> PolicyConstraintRecord:
        now = utc_now()
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM policy_constraints WHERE id = ? AND user_id = ?",
                (constraint_id, user_id),
            ).fetchone()
            if row is None:
                raise KeyError(constraint_id)
            if row["status"] != PolicyConstraintStatus.ACTIVE.value:
                raise ValueError("only active policy constraints can be revoked")
            version = self._next_policy_version(connection, user_id, now)
            connection.execute(
                "UPDATE policy_constraints SET status = ? WHERE id = ? AND user_id = ?",
                (
                    PolicyConstraintStatus.REVOKED.value,
                    constraint_id,
                    user_id,
                ),
            )
            self._audit(
                connection,
                constraint_id,
                user_id,
                "policy_constraint.revoked",
                {"policy_version": version},
                now,
            )
            updated = connection.execute(
                "SELECT * FROM policy_constraints WHERE id = ? AND user_id = ?",
                (constraint_id, user_id),
            ).fetchone()
        return self._row_to_policy_constraint(cast(sqlite3.Row, updated))

    def purge_policy_constraint(self, constraint_id: str, user_id: str) -> None:
        now = utc_now()
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM policy_constraints WHERE id = ? AND user_id = ?",
                (constraint_id, user_id),
            ).fetchone()
            if row is None:
                raise KeyError(constraint_id)
            still_behavioral = row["status"] == PolicyConstraintStatus.ACTIVE.value and (
                row["valid_until"] is None
                or cast(datetime, datetime_from_text(row["valid_until"])) > now
            )
            version = (
                self._next_policy_version(connection, user_id, now)
                if still_behavioral
                else self._policy_version(connection, user_id)
            )
            connection.execute(
                "UPDATE policy_constraints SET supersedes_id = NULL "
                "WHERE user_id = ? AND supersedes_id = ?",
                (user_id, constraint_id),
            )
            self._clear_audit_history(connection, constraint_id, user_id)
            self._audit(
                connection,
                constraint_id,
                user_id,
                "policy_constraint.purged",
                {"policy_version": version},
                now,
            )
            connection.execute(
                "DELETE FROM policy_constraints WHERE id = ? AND user_id = ?",
                (constraint_id, user_id),
            )

    def current_policy_version(self, user_id: str) -> int:
        with self.database.connection() as connection:
            return self._policy_version(connection, user_id)

    @staticmethod
    def _policy_version(connection: sqlite3.Connection, user_id: str) -> int:
        row = connection.execute(
            """
            SELECT COALESCE(
                (SELECT version FROM policy_versions WHERE user_id = ?),
                (SELECT MAX(version) FROM policy_constraints WHERE user_id = ?),
                0
            )
            """,
            (user_id, user_id),
        ).fetchone()
        return int(row[0])

    @staticmethod
    def _next_policy_version(connection: sqlite3.Connection, user_id: str, now: datetime) -> int:
        # The counter is deliberately separate from policy rows. Purging a
        # source-derived constraint must never make policy versions go
        # backwards or let a later task reuse a previously issued version.
        connection.execute(
            """
            INSERT INTO policy_versions (user_id, version, updated_at)
            VALUES (
                ?,
                COALESCE(
                    (SELECT MAX(version) + 1 FROM policy_constraints WHERE user_id = ?),
                    1
                ),
                ?
            )
            ON CONFLICT(user_id) DO UPDATE SET
                version = MAX(policy_versions.version + 1, excluded.version),
                updated_at = excluded.updated_at
            """,
            (user_id, user_id, datetime_to_text(now)),
        )
        row = connection.execute(
            "SELECT version FROM policy_versions WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        return int(row[0])

    @staticmethod
    def _require_source_policy_revocation_ack(
        connection: sqlite3.Connection,
        turn_id: str,
        user_id: str,
        now: datetime,
        acknowledged: bool,
    ) -> None:
        if acknowledged:
            return
        row = connection.execute(
            "SELECT 1 FROM policy_constraints "
            "WHERE user_id = ? AND source_turn_id = ? AND status = ? "
            "AND (valid_until IS NULL OR valid_until > ?) LIMIT 1",
            (
                user_id,
                turn_id,
                PolicyConstraintStatus.ACTIVE.value,
                datetime_to_text(now),
            ),
        ).fetchone()
        if row is not None:
            raise ValueError(
                "turn deletion would revoke an active policy constraint; "
                "set revoke_source_policies=true only after an explicit user decision"
            )

    def _invalidate_turn_descendants(
        self,
        connection: sqlite3.Connection,
        turn_id: str,
        user_id: str,
        now: datetime,
        *,
        purge_descendants: bool,
    ) -> None:
        self.semantic_index.delete(SemanticKind.TURN, turn_id, user_id)
        connection.execute(
            "DELETE FROM turn_interpretations WHERE turn_id = ? AND user_id = ?",
            (turn_id, user_id),
        )
        # Discard derived labels as well as memberships when their evidence is removed.
        connection.execute(
            "UPDATE episodes SET title = '来源已移除的事件', summary = '', topic_keys_json = '[]', "
            "participant_actor_ids_json = '[]', revision = revision + 1, updated_at = ? "
            "WHERE user_id = ? AND id IN "
            "(SELECT episode_id FROM conversation_turns WHERE id = ? AND user_id = ?)",
            (datetime_to_text(now), user_id, turn_id, user_id),
        )
        rows = connection.execute(
            """
            SELECT DISTINCT memories.id FROM memories
            JOIN json_each(memories.evidence_turn_ids_json) AS evidence_turn
            WHERE memories.user_id = ? AND evidence_turn.value = ?
            """,
            (user_id, turn_id),
        ).fetchall()
        for row in rows:
            memory_id = str(row["id"])
            self.semantic_index.delete(SemanticKind.MEMORY, memory_id, user_id)
            if purge_descendants:
                self._clear_audit_history(connection, memory_id, user_id)
            self._audit(
                connection,
                memory_id,
                user_id,
                ("memory.evidence_purged" if purge_descendants else "memory.evidence_forgotten"),
                {},
                now,
            )
            if purge_descendants:
                connection.execute(
                    "DELETE FROM memory_use_events WHERE memory_id = ? AND user_id = ?",
                    (memory_id, user_id),
                )
                connection.execute(
                    "UPDATE memories SET supersedes_id = NULL "
                    "WHERE user_id = ? AND supersedes_id = ?",
                    (user_id, memory_id),
                )
                connection.execute(
                    "DELETE FROM memories WHERE id = ? AND user_id = ?",
                    (memory_id, user_id),
                )
            else:
                connection.execute(
                    """
                    UPDATE memories
                    SET status = ?, resolution_status = ?, valid_to = ?, updated_at = ?
                    WHERE id = ? AND user_id = ?
                    """,
                    (
                        MemoryStatus.FORGOTTEN.value,
                        ResolutionStatus.CONTESTED.value,
                        datetime_to_text(now),
                        datetime_to_text(now),
                        memory_id,
                        user_id,
                    ),
                )

        open_loop_rows = connection.execute(
            "SELECT id FROM open_loops WHERE user_id = ? AND source_turn_id = ? "
            "AND status IN (?, ?, ?)",
            (
                user_id,
                turn_id,
                OpenLoopStatus.OPEN.value,
                OpenLoopStatus.SNOOZED.value,
                OpenLoopStatus.WAITING_FOR_REPLY.value,
            ),
        ).fetchall()
        for row in open_loop_rows:
            open_loop_id = str(row["id"])
            self._audit(
                connection,
                open_loop_id,
                user_id,
                ("open_loop.source_purged" if purge_descendants else "open_loop.source_forgotten"),
                {},
                now,
            )
        connection.execute(
            """
            UPDATE open_loops
            SET status = ?, resolution_summary = ?, resolved_at = ?, updated_at = ?,
                revision = revision + 1
            WHERE user_id = ? AND source_turn_id = ? AND status IN (?, ?, ?)
            """,
            (
                OpenLoopStatus.CANCELLED.value,
                "source_turn_unavailable",
                datetime_to_text(now),
                datetime_to_text(now),
                user_id,
                turn_id,
                OpenLoopStatus.OPEN.value,
                OpenLoopStatus.SNOOZED.value,
                OpenLoopStatus.WAITING_FOR_REPLY.value,
            ),
        )

        response_plan_rows = connection.execute(
            "SELECT id FROM response_plans WHERE user_id = ? AND trigger_turn_id = ? "
            "AND status = ?",
            (user_id, turn_id, ResponsePlanStatus.ACTIVE.value),
        ).fetchall()
        response_plan_ids = [str(row["id"]) for row in response_plan_rows]
        if response_plan_ids:
            placeholders = ", ".join("?" for _ in response_plan_ids)
            connection.execute(
                f"""
                UPDATE response_plans
                SET status = ?, resolution_request_json = NULL,
                    cancellation_reason = ?, cancelled_at = ?, updated_at = ?
                WHERE id IN ({placeholders})
                """,
                (
                    ResponsePlanStatus.CANCELLED.value,
                    "trigger_turn_unavailable",
                    datetime_to_text(now),
                    datetime_to_text(now),
                    *response_plan_ids,
                ),
            )
            connection.execute(
                f"""
                UPDATE response_beats SET status = ?, cancelled_at = ?
                WHERE plan_id IN ({placeholders}) AND status IN (?, ?)
                """,
                (
                    ResponseBeatStatus.CANCELLED.value,
                    datetime_to_text(now),
                    *response_plan_ids,
                    ResponseBeatStatus.READY.value,
                    ResponseBeatStatus.PENDING.value,
                ),
            )

        policy_rows = connection.execute(
            "SELECT id, status, valid_until FROM policy_constraints "
            "WHERE user_id = ? AND source_turn_id = ?",
            (user_id, turn_id),
        ).fetchall()
        if not policy_rows:
            return
        active_policy_changed = any(
            row["status"] == PolicyConstraintStatus.ACTIVE.value
            and (
                row["valid_until"] is None
                or cast(datetime, datetime_from_text(row["valid_until"])) > now
            )
            for row in policy_rows
        )
        policy_version = (
            self._next_policy_version(connection, user_id, now)
            if active_policy_changed
            else self._policy_version(connection, user_id)
        )
        for row in policy_rows:
            constraint_id = str(row["id"])
            if purge_descendants:
                self._clear_audit_history(connection, constraint_id, user_id)
            self._audit(
                connection,
                constraint_id,
                user_id,
                (
                    "policy_constraint.source_purged"
                    if purge_descendants
                    else "policy_constraint.source_forgotten"
                ),
                {
                    "policy_version": policy_version,
                },
                now,
            )
        if purge_descendants:
            constraint_ids = [str(row["id"]) for row in policy_rows]
            placeholders = ", ".join("?" for _ in constraint_ids)
            connection.execute(
                f"UPDATE policy_constraints SET supersedes_id = NULL "
                f"WHERE user_id = ? AND supersedes_id IN ({placeholders})",
                (user_id, *constraint_ids),
            )
            connection.execute(
                f"DELETE FROM policy_constraints WHERE user_id = ? AND id IN ({placeholders})",
                (user_id, *constraint_ids),
            )
        else:
            connection.execute(
                "UPDATE policy_constraints SET status = ? "
                "WHERE user_id = ? AND source_turn_id = ? AND status = ?",
                (
                    PolicyConstraintStatus.REVOKED.value,
                    user_id,
                    turn_id,
                    PolicyConstraintStatus.ACTIVE.value,
                ),
            )

    def pending_count(self, user_id: str) -> int:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT COUNT(*) FROM memories WHERE user_id = ? AND status = ?",
                (user_id, MemoryStatus.CANDIDATE.value),
            ).fetchone()
        return int(row[0])

    def expire_due(self, as_of: datetime) -> int:
        now_text = datetime_to_text(as_of)
        with self.database.connection() as connection:
            cursor = connection.execute(
                """
                UPDATE memories
                SET status = ?, valid_to = ?, updated_at = ?
                WHERE status IN (?, ?) AND expires_at IS NOT NULL AND expires_at <= ?
                """,
                (
                    MemoryStatus.EXPIRED.value,
                    now_text,
                    now_text,
                    MemoryStatus.ACTIVE.value,
                    MemoryStatus.CANDIDATE.value,
                    now_text,
                ),
            )
            return cursor.rowcount

    def expire_events(self, as_of: datetime) -> int:
        now = utc_now()
        with self.database.connection() as connection:
            rows = connection.execute(
                """
                SELECT id, user_id
                FROM conversation_events
                WHERE expires_at <= ?
                """,
                (datetime_to_text(as_of),),
            ).fetchall()
            for row in rows:
                self._clear_audit_history(connection, str(row["id"]), str(row["user_id"]))
                self._audit(
                    connection,
                    str(row["id"]),
                    str(row["user_id"]),
                    "event.expired_and_purged",
                    {},
                    now,
                )
                connection.execute(
                    "DELETE FROM conversation_events WHERE id = ?",
                    (row["id"],),
                )
            return len(rows)

    @staticmethod
    def _hierarchical_scope_filter(table: str, scope: MemoryScope) -> tuple[list[str], list[Any]]:
        if table not in {
            "memories",
            "temporal_anchors",
            "policy_constraints",
            "open_loops",
            "memory_reference_feedback",
        }:
            raise ValueError("unsupported hierarchical scope table")
        clauses: list[str] = []
        parameters: list[Any] = []
        for column in SCOPE_COLUMNS:
            value = getattr(scope, column)
            if value is None:
                clauses.append(f"{table}.{column} IS NULL")
            else:
                clauses.append(f"({table}.{column} IS NULL OR {table}.{column} = ?)")
                parameters.append(value)
        return clauses, parameters

    @staticmethod
    def _evidence_scope_is_compatible(target: MemoryScope, source: sqlite3.Row) -> bool:
        # Derived memories may drop the conversation dimension only when they
        # retain every non-null parent consent domain carried by the evidence.
        # This supports relationship-long memory without allowing a private
        # relationship turn to become companion-wide or user-global data.
        for column in CONSENT_DOMAIN_COLUMNS:
            source_value = source[column]
            if source_value is not None and getattr(target, column) != source_value:
                return False
        source_conversation = source["conversation_id"]
        target_conversation = target.conversation_id
        if target_conversation is not None:
            return bool(target_conversation == source_conversation)
        return bool(
            source_conversation is None
            or any(source[column] is not None for column in CONSENT_DOMAIN_COLUMNS)
        )

    @staticmethod
    def _turn_has_direct_user_evidence(source: sqlite3.Row) -> bool:
        raw_spans: Any = json.loads(str(source["speech_spans_json"]))
        if not raw_spans:
            # Legacy or trusted-host turns without proposition spans remain
            # admissible, but callers must not claim that the core verified
            # their speaker attribution.
            return True
        if not isinstance(raw_spans, list) or not all(isinstance(span, dict) for span in raw_spans):
            return False
        spans: list[dict[str, Any]] = raw_spans
        direct_acts = {
            SpeechAct.ASSERTION.value,
            SpeechAct.SELF_REPORT.value,
            SpeechAct.COMMAND.value,
            SpeechAct.CORRECTION.value,
            SpeechAct.WITHDRAWAL.value,
        }
        actor_id = str(source["actor_id"])
        # evidence_turn_ids currently point to a whole turn, not a specific
        # proposition span. Mixed-speaker turns therefore remain ineligible
        # for state or policy promotion until claim-level anchors exist.
        return all(
            int(span.get("quote_depth", 0)) == 0
            and span.get("reality_layer", RealityLayer.REAL_WORLD.value)
            not in {RealityLayer.QUOTE.value, RealityLayer.FICTION.value}
            and span.get("attributed_speaker_id") in {None, actor_id}
            and span.get("speech_act", SpeechAct.OTHER.value) in direct_acts
            for span in spans
        )

    @staticmethod
    def _realm_filter(table: str, layer: RealityLayer | None) -> tuple[str, list[Any]]:
        if layer is None:
            return "", []
        if table == "memories":
            return " AND memories.reality_layer = ?", [layer.value]
        if table == "conversation_turns":
            return (
                " AND companion_turn_reality(conversation_turns.content, "
                "conversation_turns.metadata_json, conversation_turns.speech_spans_json) = ?",
                [layer.value],
            )
        if table == "conversation_events":
            return (
                " AND COALESCE(json_extract(conversation_events.metadata_json, "
                "'$.reality_layer'), 'real_world') = ?",
                [layer.value],
            )
        raise ValueError("unknown evidence table")

    @staticmethod
    def _exact_turn_scope_filter(scope: MemoryScope) -> tuple[list[str], list[Any]]:
        clauses: list[str] = []
        parameters: list[Any] = []
        for column in SCOPE_COLUMNS:
            value = getattr(scope, column)
            clauses.append(f"conversation_turns.{column} IS ?")
            parameters.append(value)
        return clauses, parameters

    @staticmethod
    def _memory_validity_filter(
        user_id: str,
        scope: MemoryScope,
        as_of: datetime,
        event_after: datetime | None,
        event_before: datetime | None,
    ) -> tuple[str, list[Any]]:
        clauses = [
            "memories.user_id = ?",
            "memories.status IN (?, ?)",
            "memories.valid_from <= ?",
            "(memories.valid_to IS NULL OR memories.valid_to > ?)",
            "(memories.expires_at IS NULL OR memories.expires_at > ?)",
        ]
        as_of_text = datetime_to_text(as_of)
        parameters: list[Any] = [
            user_id,
            MemoryStatus.ACTIVE.value,
            MemoryStatus.SUPERSEDED.value,
            as_of_text,
            as_of_text,
            as_of_text,
        ]
        scope_clauses, scope_parameters = MemoryStore._hierarchical_scope_filter("memories", scope)
        clauses.extend(scope_clauses)
        parameters.extend(scope_parameters)
        if event_after is not None:
            clauses.append("memories.event_at >= ?")
            parameters.append(datetime_to_text(event_after))
        if event_before is not None:
            clauses.append("memories.event_at < ?")
            parameters.append(datetime_to_text(event_before))
        return " AND ".join(clauses), parameters

    @staticmethod
    def _event_validity_filter(
        user_id: str,
        scope: MemoryScope,
        as_of: datetime,
        event_after: datetime | None,
        event_before: datetime | None,
    ) -> tuple[str, list[Any]]:
        clauses = [
            "conversation_events.user_id = ?",
            "conversation_events.status = ?",
            "conversation_events.occurred_at <= ?",
            "conversation_events.expires_at > ?",
        ]
        as_of_text = datetime_to_text(as_of)
        parameters: list[Any] = [
            user_id,
            EventStatus.ACTIVE.value,
            as_of_text,
            as_of_text,
        ]
        for column in SCOPE_COLUMNS:
            value = getattr(scope, column)
            clauses.append(f"conversation_events.{column} IS ?")
            parameters.append(value)
        if event_after is not None:
            clauses.append("conversation_events.occurred_at >= ?")
            parameters.append(datetime_to_text(event_after))
        if event_before is not None:
            clauses.append("conversation_events.occurred_at < ?")
            parameters.append(datetime_to_text(event_before))
        return " AND ".join(clauses), parameters

    def _semantic_candidates(
        self,
        connection: sqlite3.Connection,
        query: SemanticQuery,
        where: str,
        parameters: list[Any],
    ) -> list[tuple[float, sqlite3.Row]]:
        parent = SEMANTIC_TABLES[query.kind][2]
        result: list[tuple[float, sqlite3.Row]] = []
        for hit in self.semantic_index.search(query)[: query.limit]:
            if not math.isfinite(hit.similarity) or hit.similarity < query.minimum_similarity:
                continue
            row = connection.execute(
                f"SELECT {parent}.* FROM {parent} WHERE {where} AND {parent}.id = ?",
                (*parameters, hit.id),
            ).fetchone()
            if row is not None:
                result.append((min(1.0, max(0.0, hit.similarity)), row))
        return result

    def _insert_embedding(
        self,
        connection: sqlite3.Connection,
        table: str,
        id_column: str,
        record_id: str,
        space: str,
        embedding: list[float],
        now: datetime,
    ) -> None:
        kind = next(
            (kind for kind, target in SEMANTIC_TABLES.items() if target[:2] == (table, id_column)),
            None,
        )
        if kind is None:
            raise ValueError("unsupported embedding target")
        parent = SEMANTIC_TABLES[kind][2]
        row = connection.execute(f"SELECT * FROM {parent} WHERE id = ?", (record_id,)).fetchone()
        if row is None:
            raise ValueError("embedding source is unavailable")
        self.semantic_index.upsert(
            SemanticDocument(
                kind=kind,
                id=record_id,
                user_id=row["user_id"],
                scope=scope_from_row(row),
                space=space,
                vector=embedding,
            )
        )

    def _supersede_current(
        self,
        connection: sqlite3.Connection,
        user_id: str,
        scope: MemoryScope,
        kind: str,
        stable_key: str,
        now: datetime,
        exclude_id: str | None = None,
        *,
        subject_actor_id: str | None = None,
        predicate: str | None = None,
        reality_layer: RealityLayer = RealityLayer.REAL_WORLD,
    ) -> str | None:
        query = """
            SELECT id FROM memories
            WHERE user_id = ?
              AND companion_id IS ? AND relationship_id IS ?
              AND conversation_id IS ? AND group_id IS ?
              AND kind = ? AND stable_key = ? AND status = ?
              AND COALESCE(subject_actor_id, user_id) = ?
              AND predicate IS ? AND reality_layer = ?
        """
        parameters: list[Any] = [
            user_id,
            *scope_values(scope),
            kind,
            stable_key,
            MemoryStatus.ACTIVE.value,
            subject_actor_id or user_id,
            predicate,
            reality_layer.value,
        ]
        if exclude_id is not None:
            query += " AND id != ?"
            parameters.append(exclude_id)
        query += " ORDER BY updated_at DESC LIMIT 1"
        row = connection.execute(query, parameters).fetchone()
        if row is None:
            return None
        old_id = str(row["id"])
        connection.execute(
            """
            UPDATE memories
            SET status = ?, valid_to = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                MemoryStatus.SUPERSEDED.value,
                datetime_to_text(now),
                datetime_to_text(now),
                old_id,
            ),
        )
        self._audit(connection, old_id, user_id, "memory.superseded", {}, now)
        return old_id

    @staticmethod
    def _select_one(
        connection: sqlite3.Connection, memory_id: str, user_id: str
    ) -> sqlite3.Row | None:
        return cast(
            sqlite3.Row | None,
            connection.execute(
                "SELECT * FROM memories WHERE id = ? AND user_id = ?",
                (memory_id, user_id),
            ).fetchone(),
        )

    @staticmethod
    def _select_temporal_anchor(
        connection: sqlite3.Connection, anchor_id: str, user_id: str
    ) -> sqlite3.Row | None:
        return cast(
            sqlite3.Row | None,
            connection.execute(
                "SELECT * FROM temporal_anchors WHERE id = ? AND user_id = ?",
                (anchor_id, user_id),
            ).fetchone(),
        )

    @staticmethod
    def _audit(
        connection: sqlite3.Connection,
        memory_id: str,
        user_id: str,
        event_type: str,
        payload: dict[str, Any],
        now: datetime,
    ) -> None:
        connection.execute(
            """
            INSERT INTO audit_events (memory_id, user_id, event_type, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                memory_id,
                user_id,
                event_type,
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                datetime_to_text(now),
            ),
        )

    @staticmethod
    def _clear_audit_history(connection: sqlite3.Connection, object_id: str, user_id: str) -> None:
        # A primary-store purge replaces verbose lifecycle audit metadata with
        # one minimal deletion receipt. This avoids leaving actor, session, or
        # policy-action metadata behind after the source object is removed.
        connection.execute(
            "DELETE FROM audit_events WHERE memory_id = ? AND user_id = ?",
            (object_id, user_id),
        )

    @staticmethod
    def _row_to_memory(row: sqlite3.Row) -> MemoryRecord:
        return MemoryRecord.model_validate(
            {
                "id": row["id"],
                "user_id": row["user_id"],
                "scope": scope_from_row(row),
                "kind": row["kind"],
                "title": row["title"],
                "content": row["content"],
                "stable_key": row["stable_key"],
                "emotions": json.loads(row["emotions_json"]),
                "needs": json.loads(row["needs_json"]),
                "status": row["status"],
                "consent": row["consent"],
                "sensitivity": row["sensitivity"],
                "retention": row["retention"],
                "confidence": row["confidence"],
                "salience": row["salience"],
                "event_at": datetime_from_text(row["event_at"]),
                "valid_time_start": datetime_from_text(row["valid_time_start"]),
                "valid_time_end": datetime_from_text(row["valid_time_end"]),
                "valid_from": datetime_from_text(row["valid_from"]),
                "valid_to": datetime_from_text(row["valid_to"]),
                "expires_at": datetime_from_text(row["expires_at"]),
                "supersedes_id": row["supersedes_id"],
                "source_ref": row["source_ref"],
                "content_hash": row["content_hash"],
                "entities": json.loads(row["entities_json"]),
                "epistemic_kind": row["epistemic_kind"],
                "resolution_status": row["resolution_status"],
                "reality_layer": row["reality_layer"],
                "source_actor": row["source_actor"],
                "quote_depth": row["quote_depth"],
                "elicitation_kind": row["elicitation_kind"],
                "subject_actor_id": row["subject_actor_id"],
                "predicate": row["predicate"],
                "evidence_turn_ids": json.loads(row["evidence_turn_ids_json"]),
                "metadata": json.loads(row["metadata_json"]),
                "created_at": datetime_from_text(row["created_at"]),
                "updated_at": datetime_from_text(row["updated_at"]),
            }
        )

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> ConversationEventRecord:
        return ConversationEventRecord.model_validate(
            {
                "id": row["id"],
                "user_id": row["user_id"],
                "scope": scope_from_row(row),
                "session_id": row["session_id"],
                "role": row["role"],
                "content": row["content"],
                "status": row["status"],
                "consent": row["consent"],
                "sensitivity": row["sensitivity"],
                "occurred_at": datetime_from_text(row["occurred_at"]),
                "expires_at": datetime_from_text(row["expires_at"]),
                "source_ref": row["source_ref"],
                "entities": json.loads(row["entities_json"]),
                "metadata": json.loads(row["metadata_json"]),
                "created_at": datetime_from_text(row["created_at"]),
            }
        )

    @staticmethod
    def _row_to_temporal_anchor(row: sqlite3.Row) -> TemporalAnchorRecord:
        return TemporalAnchorRecord.model_validate(
            {
                "id": row["id"],
                "user_id": row["user_id"],
                "scope": scope_from_row(row),
                "name": row["name"],
                "aliases": json.loads(row["aliases_json"]),
                "start_at": datetime_from_text(row["start_at"]),
                "end_at": datetime_from_text(row["end_at"]),
                "status": row["status"],
                "consent": row["consent"],
                "sensitivity": row["sensitivity"],
                "source_ref": row["source_ref"],
                "supersedes_id": row["supersedes_id"],
                "valid_from": datetime_from_text(row["valid_from"]),
                "valid_to": datetime_from_text(row["valid_to"]),
                "created_at": datetime_from_text(row["created_at"]),
                "updated_at": datetime_from_text(row["updated_at"]),
            }
        )

    @staticmethod
    def _row_to_turn(row: sqlite3.Row) -> ConversationTurnRecord:
        return ConversationTurnRecord.model_validate(
            {
                "id": row["id"],
                "server_sequence": row["server_sequence"],
                "user_id": row["user_id"],
                "scope": scope_from_row(row),
                "actor_id": row["actor_id"],
                "role": row["role"],
                "content": row["content"],
                "consent": row["consent"],
                "sensitivity": row["sensitivity"],
                "occurred_at": datetime_from_text(row["occurred_at"]),
                "ingested_at": datetime_from_text(row["ingested_at"]),
                "modality": row["modality"],
                "language": row["language"],
                "reply_to_turn_id": row["reply_to_turn_id"],
                "supersedes_turn_id": row["supersedes_turn_id"],
                "episode_id": row["episode_id"],
                "source_ref": row["source_ref"],
                "idempotency_key": row["idempotency_key"],
                "speech_spans": json.loads(row["speech_spans_json"]),
                "retrieval_keys": json.loads(row["retrieval_keys_json"]),
                "embedding_space": row["embedding_space"],
                "content_hash": row["content_hash"],
                "deletion_state": row["deletion_state"],
                "metadata": json.loads(row["metadata_json"]),
            }
        )

    @staticmethod
    def _row_to_memory_use(row: sqlite3.Row) -> MemoryUseRecord:
        return MemoryUseRecord.model_validate(
            {
                "id": row["id"],
                "user_id": row["user_id"],
                "scope": scope_from_row(row),
                "memory_id": row["memory_id"],
                "response_group_id": row["response_group_id"],
                "use_mode": row["use_mode"],
                "use_type": row["use_type"],
                "purpose": row["purpose"],
                "output_hash": row["output_hash"],
                "used_at": datetime_from_text(row["used_at"]),
                "created_at": datetime_from_text(row["created_at"]),
            }
        )

    @staticmethod
    def _row_to_policy_constraint(row: sqlite3.Row) -> PolicyConstraintRecord:
        return PolicyConstraintRecord.model_validate(
            {
                "id": row["id"],
                "user_id": row["user_id"],
                "scope": scope_from_row(row),
                "action": row["action"],
                "channel": row["channel"],
                "effect": row["effect"],
                "status": row["status"],
                "version": row["version"],
                "valid_from": datetime_from_text(row["valid_from"]),
                "valid_until": datetime_from_text(row["valid_until"]),
                "source_turn_id": row["source_turn_id"],
                "reason_code": row["reason_code"],
                "supersedes_id": row["supersedes_id"],
                "created_at": datetime_from_text(row["created_at"]),
            }
        )

    @staticmethod
    def _row_to_open_loop(row: sqlite3.Row) -> OpenLoopRecord:
        return OpenLoopRecord.model_validate(
            {
                "id": row["id"],
                "user_id": row["user_id"],
                "scope": scope_from_row(row),
                "kind": row["kind"],
                "summary": row["summary"],
                "topic_keys": json.loads(row["topic_keys_json"]),
                "follow_up_mode": row["follow_up_mode"],
                "status": row["status"],
                "follow_up_after": datetime_from_text(row["follow_up_after"]),
                "expires_at": datetime_from_text(row["expires_at"]),
                "source_turn_id": row["source_turn_id"],
                "consent": row["consent"],
                "sensitivity": row["sensitivity"],
                "resolution_summary": row["resolution_summary"],
                "last_followed_up_at": datetime_from_text(row["last_followed_up_at"]),
                "follow_up_count": row["follow_up_count"],
                "last_response_group_id": row["last_response_group_id"],
                "revision": row["revision"],
                "opened_at": datetime_from_text(row["opened_at"]),
                "updated_at": datetime_from_text(row["updated_at"]),
                "resolved_at": datetime_from_text(row["resolved_at"]),
                "metadata": json.loads(row["metadata_json"]),
            }
        )

    @staticmethod
    def _row_to_reference_feedback(row: sqlite3.Row) -> MemoryReferenceFeedbackRecord:
        return MemoryReferenceFeedbackRecord.model_validate(
            {
                "id": row["id"],
                "user_id": row["user_id"],
                "scope": scope_from_row(row),
                "memory_id": row["memory_id"],
                "evidence_kind": row["evidence_kind"],
                "evidence_id": row["evidence_id"],
                "kind": row["kind"],
                "source_turn_id": row["source_turn_id"],
                "note": row["note"],
                "recorded_at": datetime_from_text(row["recorded_at"]),
                "created_at": datetime_from_text(row["created_at"]),
            }
        )

    @staticmethod
    def _row_to_response_beat(row: sqlite3.Row) -> ResponseBeatRecord:
        return ResponseBeatRecord.model_validate(
            {
                "id": row["id"],
                "ordinal": row["ordinal"],
                "kind": row["kind"],
                "source": row["source"],
                "release_condition": row["release_condition"],
                "status": row["status"],
                "guidance": row["guidance"],
                "evidence": json.loads(row["evidence_json"]),
                "output_hash": row["output_hash"],
                "sent_at": datetime_from_text(row["sent_at"]),
                "cancelled_at": datetime_from_text(row["cancelled_at"]),
            }
        )

    @classmethod
    def _row_to_response_plan(
        cls, row: sqlite3.Row, beat_rows: list[sqlite3.Row]
    ) -> ResponsePlanRecord:
        return ResponsePlanRecord.model_validate(
            {
                "id": row["id"],
                "response_group_id": row["response_group_id"],
                "user_id": row["user_id"],
                "scope": scope_from_row(row),
                "trigger_turn_id": row["trigger_turn_id"],
                "goal": row["goal"],
                "delivery_mode": row["delivery_mode"],
                "status": row["status"],
                "revision": row["revision"],
                "resolution_status": row["resolution_status"],
                "policy_version": row["policy_version"],
                "config_fingerprint": row["config_fingerprint"],
                "policy_bundle": json.loads(row["policy_bundle_json"]),
                "cancel_on_new_user_turn": bool(row["cancel_on_new_user_turn"]),
                "recall_action": row["recall_action"],
                "memory_use_plan": json.loads(row["memory_use_plan_json"]),
                "follow_up": (
                    json.loads(row["follow_up_json"]) if row["follow_up_json"] is not None else None
                ),
                "beats": [cls._row_to_response_beat(beat) for beat in beat_rows],
                "created_at": datetime_from_text(row["created_at"]),
                "updated_at": datetime_from_text(row["updated_at"]),
                "resolved_at": datetime_from_text(row["resolved_at"]),
                "cancelled_at": datetime_from_text(row["cancelled_at"]),
                "cancellation_reason": row["cancellation_reason"],
            }
        )
