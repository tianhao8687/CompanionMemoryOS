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
from typing import Protocol, runtime_checkable

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
    source_hash: str | None = None


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
    include_relationship_turns: bool = False


@dataclass(frozen=True)
class SemanticHit:
    id: str
    similarity: float


class SemanticIndex(Protocol):
    def upsert(self, document: SemanticDocument) -> None: ...

    def delete(self, kind: SemanticKind, record_id: str, user_id: str) -> None: ...

    def search(self, query: SemanticQuery) -> list[SemanticHit]: ...


@runtime_checkable
class PassageSemanticIndex(SemanticIndex, Protocol):
    """Optional source-addressed passages, served by the same candidate backend."""

    def upsert_passage(self, document: SemanticDocument, start: int, end: int) -> None: ...

    def passage_vectors(
        self, turn_id: str, user_id: str, space: str, source_hash: str
    ) -> list[tuple[int, int, list[float]]]: ...


@runtime_checkable
class CacheableSemanticIndex(SemanticIndex, Protocol):
    """Receipts may be reused only for this backend's namespace and resident IDs.

    A namespace identifies one persistent index, not just its implementation class.
    Backends without this capability are still writable, without persistent receipts.
    """

    @property
    def cache_namespace(self) -> str: ...

    def indexed_ids(self, kind: SemanticKind, user_id: str, space: str) -> set[str]: ...


class SQLiteSemanticIndex:
    """Exact scoped scan of existing vector tables; not a large-scale ANN claim."""

    def __init__(self, database: Database) -> None:
        self.database = database

    @property
    def cache_namespace(self) -> str:
        return "sqlite:" + str(self.database.path)

    def indexed_ids(self, kind: SemanticKind, user_id: str, space: str) -> set[str]:
        table, id_column, parent = TABLES[kind]
        with self.database.connection() as connection:
            return {
                str(row["id"])
                for row in connection.execute(
                    f"SELECT p.id FROM {parent} p JOIN {table} e ON e.{id_column}=p.id "
                    "WHERE p.user_id=? AND e.space=?",
                    (user_id, space),
                )
            }

    def upsert(self, document: SemanticDocument) -> None:
        from companion_memoryos.store import datetime_to_text, scope_from_row, utc_now

        table, id_column, parent = TABLES[document.kind]
        if not document.vector or not all(math.isfinite(value) for value in document.vector):
            raise ValueError("semantic vectors must contain finite values")
        with self.database.atomic() as connection:
            row = connection.execute(
                f"SELECT * FROM {parent} WHERE id = ? AND user_id = ?",
                (document.id, document.user_id),
            ).fetchone()
            if row is None or scope_from_row(row) != document.scope:
                raise ValueError("semantic document does not match its stored source")
            if document.source_hash is not None and (
                row["content_hash"] != document.source_hash
                or row["consent"] != "granted"
                or row["deletion_state" if document.kind is SemanticKind.TURN else "status"]
                != "active"
            ):
                raise ValueError("semantic source changed during encoding")
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

    def upsert_passage(self, document: SemanticDocument, start: int, end: int) -> None:
        if document.kind is not SemanticKind.TURN or document.source_hash is None:
            raise ValueError("passages require a versioned original turn")
        with self.database.atomic() as connection:
            self.upsert(document)
            row = connection.execute(
                "SELECT length(content) AS size FROM conversation_turns WHERE id=?",
                (document.id,),
            ).fetchone()
            if row is None or not 0 <= start < end <= row["size"]:
                raise ValueError("passage is outside its source")
            connection.execute(
                "INSERT OR REPLACE INTO turn_embedding_passages VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    document.id,
                    start,
                    end,
                    document.source_hash,
                    document.space,
                    len(document.vector),
                    pack_vector(document.vector),
                ),
            )

    def passage_vectors(
        self, turn_id: str, user_id: str, space: str, source_hash: str
    ) -> list[tuple[int, int, list[float]]]:
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT p.start_offset, p.end_offset, p.vector FROM turn_embedding_passages p "
                "JOIN conversation_turns t ON t.id=p.turn_id "
                "WHERE t.id=? AND t.user_id=? AND t.deletion_state='active' "
                "AND t.consent='granted' AND t.content_hash=p.source_hash "
                "AND p.source_hash=? AND p.space=? ORDER BY p.start_offset",
                (turn_id, user_id, source_hash, space),
            ).fetchall()
        return [(r["start_offset"], r["end_offset"], unpack_vector(r["vector"])) for r in rows]

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
            scope_clauses, scope_parameters = MemoryStore._exact_turn_scope_filter(
                query.scope, relationship_wide=query.include_relationship_turns
            )
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
        query_norm = math.sqrt(math.sumprod(query.vector, query.vector))
        with self.database.connection() as connection:
            rows = connection.execute(
                f"SELECT {parent}.id, {table}.vector FROM {parent} "
                f"JOIN {table} ON {table}.{id_column} = {parent}.id "
                f"WHERE {where} AND {table}.space = ? AND {table}.dimensions = ?",
                (*parameters, query.space, len(query.vector)),
            )

            def scored() -> Iterator[tuple[float, str]]:
                for row in rows:
                    similarity = cosine(
                        query.vector, unpack_vector(row["vector"]), left_norm=query_norm
                    )
                    if similarity >= query.minimum_similarity:
                        yield (-similarity, str(row["id"]))

            if query.kind is SemanticKind.TURN:
                # A long turn occupies one candidate slot, regardless of passage count.
                best = {identifier: -negative for negative, identifier in scored()}
                passages = connection.execute(
                    "SELECT conversation_turns.id, p.vector FROM conversation_turns "
                    "JOIN turn_embedding_passages p ON p.turn_id=conversation_turns.id "
                    f"WHERE {where} AND p.space=? AND p.dimensions=? "
                    "AND conversation_turns.content_hash=p.source_hash "
                    "AND conversation_turns.consent='granted'",
                    (*parameters, query.space, len(query.vector)),
                )
                for row in passages:
                    similarity = cosine(
                        query.vector, unpack_vector(row["vector"]), left_norm=query_norm
                    )
                    identifier = str(row["id"])
                    if similarity >= query.minimum_similarity:
                        best[identifier] = max(best.get(identifier, 0.0), similarity)
                ranked = heapq.nsmallest(
                    query.limit, ((-score, identifier) for identifier, score in best.items())
                )
            else:
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


def cosine(left: list[float], right: list[float], *, left_norm: float | None = None) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    dot = math.sumprod(left, right)
    if left_norm is None:
        left_norm = math.sqrt(math.sumprod(left, left))
    right_norm = math.sqrt(math.sumprod(right, right))
    return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0
