"""Replaceable semantic candidate lookup; SQLite remains the only bundled implementation.

Implementations MUST restrict user/scope/model/dimension before scoring. Returned IDs are
revalidated by the store. No external ANN backend or model client is installed by this module.
"""

from __future__ import annotations

import heapq
import math
import sys
from array import array
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from companion_memoryos.constants import FLOAT32_BYTES
from companion_memoryos.database import Database
from companion_memoryos.schemas import MemoryScope, RealityLayer


class SemanticKind(StrEnum):
    MEMORY = "memory"
    EVENT = "event"
    TURN = "turn"


TABLES = {
    SemanticKind.MEMORY: ("memory_embeddings", "memory_id", "memories"),
    SemanticKind.EVENT: ("event_embeddings", "event_id", "conversation_events"),
    SemanticKind.TURN: ("turn_embeddings", "turn_id", "conversation_turns"),
}


@dataclass(frozen=True)
class SemanticDocument:
    kind: SemanticKind
    id: str
    user_id: str
    scope: MemoryScope
    space: str
    vector: list[float]


@dataclass(frozen=True)
class SemanticQuery:
    kind: SemanticKind
    user_id: str
    scope: MemoryScope
    space: str
    vector: list[float]
    as_of: datetime
    limit: int
    minimum_similarity: float
    event_after: datetime | None = None
    event_before: datetime | None = None
    actor_id: str | None = None
    exclude_ids: list[str] = field(default_factory=list)
    reality_layer: RealityLayer | None = None


@dataclass(frozen=True)
class SemanticHit:
    id: str
    similarity: float


class SemanticIndex(Protocol):
    def upsert(self, document: SemanticDocument) -> None: ...

    def delete(self, kind: SemanticKind, record_id: str, user_id: str) -> None: ...

    def search(self, query: SemanticQuery) -> list[SemanticHit]: ...


class SQLiteSemanticIndex:
    """Exact scoped scan of existing vector tables; not a large-scale ANN claim."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def upsert(self, document: SemanticDocument) -> None:
        from companion_memoryos.store import datetime_to_text, scope_from_row, utc_now

        table, id_column, parent = TABLES[document.kind]
        if not document.vector or not all(math.isfinite(value) for value in document.vector):
            raise ValueError("semantic vectors must contain finite values")
        with self.database.connection() as connection:
            row = connection.execute(
                f"SELECT * FROM {parent} WHERE id = ? AND user_id = ?",
                (document.id, document.user_id),
            ).fetchone()
            if row is None or scope_from_row(row) != document.scope:
                raise ValueError("semantic document does not match its stored source")
            connection.execute(
                f"INSERT INTO {table} ({id_column}, space, dimensions, vector, created_at) "
                f"VALUES (?, ?, ?, ?, ?) ON CONFLICT({id_column}) DO UPDATE SET "
                "space = excluded.space, dimensions = excluded.dimensions, "
                "vector = excluded.vector, created_at = excluded.created_at",
                (
                    document.id,
                    document.space,
                    len(document.vector),
                    pack_vector(document.vector),
                    datetime_to_text(utc_now()),
                ),
            )

    def delete(self, kind: SemanticKind, record_id: str, user_id: str) -> None:
        table, id_column, parent = TABLES[kind]
        with self.database.connection() as connection:
            connection.execute(
                f"DELETE FROM {table} WHERE {id_column} IN "
                f"(SELECT id FROM {parent} WHERE id = ? AND user_id = ?)",
                (record_id, user_id),
            )

    def search(self, query: SemanticQuery) -> list[SemanticHit]:
        from companion_memoryos.store import MemoryStore, datetime_to_text

        if query.limit <= 0 or not query.vector:
            return []
        if not all(math.isfinite(value) for value in query.vector):
            raise ValueError("semantic query must contain finite values")
        if query.kind is SemanticKind.MEMORY:
            where, parameters = MemoryStore._memory_validity_filter(
                query.user_id,
                query.scope,
                query.as_of,
                query.event_after,
                query.event_before,
            )
        elif query.kind is SemanticKind.EVENT:
            where, parameters = MemoryStore._event_validity_filter(
                query.user_id,
                query.scope,
                query.as_of,
                query.event_after,
                query.event_before,
            )
        else:
            clauses = [
                "conversation_turns.user_id = ?",
                "conversation_turns.deletion_state = 'active'",
                "conversation_turns.occurred_at <= ?",
            ]
            parameters = [query.user_id, datetime_to_text(query.as_of)]
            scope_clauses, scope_parameters = MemoryStore._exact_turn_scope_filter(query.scope)
            clauses.extend(scope_clauses)
            parameters.extend(scope_parameters)
            if query.actor_id is not None:
                clauses.append("conversation_turns.actor_id = ?")
                parameters.append(query.actor_id)
            if query.event_after is not None:
                clauses.append("conversation_turns.occurred_at >= ?")
                parameters.append(datetime_to_text(query.event_after))
            if query.event_before is not None:
                clauses.append("conversation_turns.occurred_at < ?")
                parameters.append(datetime_to_text(query.event_before))
            where = " AND ".join(clauses)
        table, id_column, parent = TABLES[query.kind]
        realm_sql, realm_parameters = MemoryStore._realm_filter(parent, query.reality_layer)
        where += realm_sql
        parameters.extend(realm_parameters)
        if query.exclude_ids:
            placeholders = ", ".join("?" for _ in query.exclude_ids)
            where += f" AND {parent}.id NOT IN ({placeholders})"
            parameters.extend(query.exclude_ids)
        with self.database.connection() as connection:
            rows = connection.execute(
                f"SELECT {parent}.id, {table}.vector FROM {parent} "
                f"JOIN {table} ON {table}.{id_column} = {parent}.id "
                f"WHERE {where} AND {table}.space = ? AND {table}.dimensions = ?",
                (*parameters, query.space, len(query.vector)),
            )

            def scored() -> Iterator[tuple[float, str]]:
                for row in rows:
                    similarity = cosine(query.vector, unpack_vector(row["vector"]))
                    if similarity >= query.minimum_similarity:
                        yield (-similarity, str(row["id"]))

            # Keep only the requested candidate heap, not all vectors in Python memory.
            ranked = heapq.nsmallest(query.limit, scored())
        return [SemanticHit(id=record_id, similarity=-negative) for negative, record_id in ranked]


def pack_vector(values: list[float]) -> bytes:
    vector = array("f", values)
    if sys.byteorder != "little":
        vector.byteswap()
    return vector.tobytes()


def unpack_vector(blob: bytes) -> list[float]:
    if len(blob) % FLOAT32_BYTES:
        raise ValueError("corrupt embedding vector")
    vector = array("f")
    vector.frombytes(blob)
    if sys.byteorder != "little":
        vector.byteswap()
    return vector.tolist()


def cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0
