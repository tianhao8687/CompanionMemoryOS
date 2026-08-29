from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

from companion_memoryos.constants import DEFAULT_ENCODING
from companion_memoryos.database import Database
from companion_memoryos.schemas import (
    MemoryInput,
    MemoryRecord,
    MemoryStatus,
    StorageAction,
    StoragePolicyDecision,
)


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
                    source_ref, content_hash, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                    datetime_to_text(now),
                    datetime_to_text(now),
                ),
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

    def review(self, memory_id: str, user_id: str, confirm: bool) -> MemoryRecord:
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
                SET status = ?, valid_to = ?, supersedes_id = ?, updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (
                    status.value,
                    None if confirm else datetime_to_text(now),
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
    ) -> list[MemoryRecord]:
        self.expire_due(as_of)
        parameters = (
            user_id,
            MemoryStatus.ACTIVE.value,
            datetime_to_text(as_of),
            datetime_to_text(as_of),
            pool_size,
        )
        with self.database.connection() as connection:
            rows: list[sqlite3.Row] = []
            if fts_query:
                rows.extend(
                    connection.execute(
                        """
                        SELECT memories.* FROM memories
                        JOIN memory_fts ON memory_fts.memory_id = memories.id
                        WHERE memories.user_id = ? AND memories.status = ?
                          AND memories.valid_from <= ?
                          AND (memories.expires_at IS NULL OR memories.expires_at > ?)
                          AND memory_fts MATCH ?
                        ORDER BY bm25(memory_fts) LIMIT ?
                        """,
                        (*parameters[:-1], fts_query, parameters[-1]),
                    ).fetchall()
                )
            rows.extend(
                connection.execute(
                    """
                    SELECT * FROM memories
                    WHERE user_id = ? AND status = ? AND valid_from <= ?
                      AND (expires_at IS NULL OR expires_at > ?)
                    ORDER BY CASE WHEN kind = 'boundary' THEN 0 ELSE 1 END,
                             event_at DESC
                    LIMIT ?
                    """,
                    parameters,
                ).fetchall()
            )
        deduplicated: dict[str, sqlite3.Row] = {}
        for row in rows:
            deduplicated.setdefault(str(row["id"]), row)
        return [self._row_to_memory(row) for row in deduplicated.values()]

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
                "metadata": json.loads(row["metadata_json"]),
                "created_at": datetime_from_text(row["created_at"]),
                "updated_at": datetime_from_text(row["updated_at"]),
            }
        )
