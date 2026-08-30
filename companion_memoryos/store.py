from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import sys
from array import array
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

from companion_memoryos.constants import DEFAULT_ENCODING, FLOAT32_BYTES
from companion_memoryos.database import Database
from companion_memoryos.schemas import (
    ConversationEventInput,
    ConversationEventRecord,
    EventStatus,
    MemoryInput,
    MemoryRecord,
    MemoryStatus,
    StorageAction,
    StoragePolicyDecision,
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


def utc_now() -> datetime:
    return datetime.now(UTC)


def datetime_to_text(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value is not None else None


def datetime_from_text(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value).astimezone(UTC) if value is not None else None


def content_digest(*parts: str) -> str:
    normalized = "\n".join(part.strip().casefold() for part in parts)
    return hashlib.sha256(normalized.encode(DEFAULT_ENCODING)).hexdigest()


class MemoryStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    def find_duplicate(self, item: MemoryInput) -> MemoryRecord | None:
        digest = content_digest(item.kind.value, item.title, item.content)
        with self.database.connection() as connection:
            row = connection.execute(
                """
                SELECT * FROM memories
                WHERE user_id = ? AND kind = ? AND content_hash = ?
                  AND status IN (?, ?)
                ORDER BY created_at DESC LIMIT 1
                """,
                (
                    item.user_id,
                    item.kind.value,
                    digest,
                    MemoryStatus.ACTIVE.value,
                    MemoryStatus.CANDIDATE.value,
                ),
            ).fetchone()
        return self._row_to_memory(cast(sqlite3.Row, row)) if row is not None else None

    def create(
        self,
        item: MemoryInput,
        decision: StoragePolicyDecision,
        stable_key: str | None,
        metadata: dict[str, Any],
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
            supersedes_id = None
            if status is MemoryStatus.ACTIVE and stable_key is not None:
                supersedes_id = self._supersede_current(
                    connection,
                    item.user_id,
                    item.kind.value,
                    stable_key,
                    now,
                )
            connection.execute(
                """
                INSERT INTO memories (
                    id, user_id, kind, title, content, stable_key, emotions_json,
                    needs_json, status, consent, sensitivity, retention, confidence,
                    salience, event_at, valid_from, valid_to, expires_at, supersedes_id,
                    source_ref, content_hash, entities_json, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    memory_id,
                    item.user_id,
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
                    str(current["kind"]),
                    str(current["stable_key"]),
                    now,
                    exclude_id=memory_id,
                )
            connection.execute(
                """
                UPDATE memories
                SET status = ?, valid_to = ?, expires_at = ?, supersedes_id = ?, updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (
                    status.value,
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
            self._audit(
                connection,
                memory_id,
                user_id,
                "memory.purged",
                {"kind": row["kind"], "content_hash": row["content_hash"]},
                now,
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
    ) -> list[MemoryRecord]:
        clauses = ["user_id = ?"]
        parameters: list[Any] = [user_id]
        if statuses:
            placeholders = ", ".join("?" for _ in statuses)
            clauses.append(f"status IN ({placeholders})")
            parameters.extend(status.value for status in statuses)
        query = f"SELECT * FROM memories WHERE {' AND '.join(clauses)} ORDER BY updated_at DESC"
        if limit is not None:
            query += " LIMIT ?"
            parameters.append(limit)
        with self.database.connection() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._row_to_memory(row) for row in rows]

    def active_pool(
        self,
        user_id: str,
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
    ) -> list[MemorySearchCandidate]:
        self.expire_due(utc_now())
        where, parameters = self._memory_validity_filter(
            user_id,
            as_of,
            event_after,
            event_before,
        )
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
                as_of,
                None,
                None,
            )
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
                semantic_rows = connection.execute(
                    f"""
                    SELECT memories.*, memory_embeddings.vector, memory_embeddings.dimensions
                    FROM memories
                    JOIN memory_embeddings ON memory_embeddings.memory_id = memories.id
                    WHERE {where} AND memory_embeddings.space = ?
                      AND memory_embeddings.dimensions = ?
                    """,
                    (*parameters, embedding_space, len(query_embedding)),
                ).fetchall()
                ranked: list[tuple[float, sqlite3.Row]] = []
                for row in semantic_rows:
                    similarity = _cosine(query_embedding, _unpack_vector(row["vector"]))
                    if similarity >= minimum_semantic_similarity:
                        ranked.append((similarity, row))
                ranked.sort(key=lambda value: (-value[0], str(value[1]["id"])))
                for similarity, row in ranked[:semantic_pool_size]:
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
        entities_json = json.dumps(
            [entity.model_dump(mode="json") for entity in item.entities],
            ensure_ascii=False,
        )
        with self.database.connection() as connection:
            connection.execute(
                """
                INSERT INTO conversation_events (
                    id, user_id, session_id, role, content, status, consent, sensitivity,
                    occurred_at, expires_at, source_ref, entities_json, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    item.user_id,
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
            self._audit(
                connection,
                event_id,
                user_id,
                "event.purged",
                {
                    "session_id": row["session_id"],
                    "content_hash": content_digest(str(row["content"])),
                },
                now,
            )
            connection.execute(
                "DELETE FROM conversation_events WHERE id = ? AND user_id = ?",
                (event_id, user_id),
            )

    def event_pool(
        self,
        user_id: str,
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
    ) -> list[EventSearchCandidate]:
        self.expire_events(utc_now())
        where, parameters = self._event_validity_filter(
            user_id,
            as_of,
            event_after,
            event_before,
        )
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
                rows = connection.execute(
                    f"""
                    SELECT conversation_events.*, event_embeddings.vector,
                           event_embeddings.dimensions
                    FROM conversation_events
                    JOIN event_embeddings ON event_embeddings.event_id = conversation_events.id
                    WHERE {where} AND event_embeddings.space = ?
                      AND event_embeddings.dimensions = ?
                    """,
                    (*parameters, embedding_space, len(query_embedding)),
                ).fetchall()
                ranked: list[tuple[float, sqlite3.Row]] = []
                for row in rows:
                    similarity = _cosine(query_embedding, _unpack_vector(row["vector"]))
                    if similarity >= minimum_semantic_similarity:
                        ranked.append((similarity, row))
                ranked.sort(key=lambda value: (-value[0], str(value[1]["id"])))
                for similarity, row in ranked[:pool_size]:
                    event = self._row_to_event(row)
                    candidate = candidates.setdefault(
                        event.id,
                        EventSearchCandidate(event=event),
                    )
                    candidate.semantic_similarity = similarity
        return list(candidates.values())

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
                SELECT id, user_id, session_id, status, content
                FROM conversation_events
                WHERE expires_at <= ?
                """,
                (datetime_to_text(as_of),),
            ).fetchall()
            for row in rows:
                self._audit(
                    connection,
                    str(row["id"]),
                    str(row["user_id"]),
                    "event.expired_and_purged",
                    {
                        "content_hash": content_digest(str(row["content"])),
                        "previous_status": row["status"],
                        "session_id": row["session_id"],
                    },
                    now,
                )
                connection.execute(
                    "DELETE FROM conversation_events WHERE id = ?",
                    (row["id"],),
                )
            return len(rows)

    @staticmethod
    def _memory_validity_filter(
        user_id: str,
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
        if event_after is not None:
            clauses.append("conversation_events.occurred_at >= ?")
            parameters.append(datetime_to_text(event_after))
        if event_before is not None:
            clauses.append("conversation_events.occurred_at < ?")
            parameters.append(datetime_to_text(event_before))
        return " AND ".join(clauses), parameters

    @staticmethod
    def _insert_embedding(
        connection: sqlite3.Connection,
        table: str,
        id_column: str,
        record_id: str,
        space: str,
        embedding: list[float],
        now: datetime,
    ) -> None:
        if table not in {"memory_embeddings", "event_embeddings"}:
            raise ValueError("unsupported embedding table")
        if id_column not in {"memory_id", "event_id"}:
            raise ValueError("unsupported embedding id column")
        connection.execute(
            f"""
            INSERT INTO {table} ({id_column}, space, dimensions, vector, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                record_id,
                space,
                len(embedding),
                _pack_vector(embedding),
                datetime_to_text(now),
            ),
        )

    def _supersede_current(
        self,
        connection: sqlite3.Connection,
        user_id: str,
        kind: str,
        stable_key: str,
        now: datetime,
        exclude_id: str | None = None,
    ) -> str | None:
        query = """
            SELECT id FROM memories
            WHERE user_id = ? AND kind = ? AND stable_key = ? AND status = ?
        """
        parameters: list[Any] = [user_id, kind, stable_key, MemoryStatus.ACTIVE.value]
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
    def _row_to_memory(row: sqlite3.Row) -> MemoryRecord:
        return MemoryRecord.model_validate(
            {
                "id": row["id"],
                "user_id": row["user_id"],
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
                "valid_from": datetime_from_text(row["valid_from"]),
                "valid_to": datetime_from_text(row["valid_to"]),
                "expires_at": datetime_from_text(row["expires_at"]),
                "supersedes_id": row["supersedes_id"],
                "source_ref": row["source_ref"],
                "content_hash": row["content_hash"],
                "entities": json.loads(row["entities_json"]),
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


def _pack_vector(values: list[float]) -> bytes:
    vector = array("f", values)
    if sys.byteorder != "little":
        vector.byteswap()
    return vector.tobytes()


def _unpack_vector(blob: bytes) -> list[float]:
    if len(blob) % FLOAT32_BYTES:
        raise ValueError("corrupt embedding vector")
    vector = array("f")
    vector.frombytes(blob)
    if sys.byteorder != "little":
        vector.byteswap()
    return vector.tolist()


def _cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    dot = sum(left_value * right_value for left_value, right_value in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)
