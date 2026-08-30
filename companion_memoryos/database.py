from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path

from companion_memoryos.config import CompanionConfig
from companion_memoryos.constants import DATABASE_SCHEMA_VERSION, SQLITE_INTEGRITY_OK
from companion_memoryos.scoring import build_search_document


class Database:
    def __init__(self, data_dir: Path, config: CompanionConfig) -> None:
        self.data_dir = data_dir.expanduser().resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.data_dir / "companion-memoryos.db"
        self.config = config

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        connection.execute(f"PRAGMA busy_timeout = {self.config.database.busy_timeout_ms}")
        connection.create_function(
            "companion_search_terms",
            4,
            self._search_terms,
            deterministic=True,
        )
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connection() as connection:
            current = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if current not in {0, 1, DATABASE_SCHEMA_VERSION}:
                raise RuntimeError(f"unsupported database schema version: {current}")
            if current == 1:
                connection.executescript(_MIGRATION_1_TO_2)
            connection.executescript(_SCHEMA)
            if current == 1:
                connection.execute(_BACKFILL_MEMORY_FTS)
            connection.execute(f"PRAGMA user_version = {DATABASE_SCHEMA_VERSION}")

    def integrity_check(self) -> None:
        with self.connection() as connection:
            result = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        if result != SQLITE_INTEGRITY_OK:
            raise RuntimeError(f"database integrity check failed: {result}")

    def _search_terms(
        self,
        title: str | None,
        content: str | None,
        needs_json: str | None,
        entities_json: str | None,
    ) -> str:
        texts = [title or "", content or ""]
        with suppress(json.JSONDecodeError, TypeError):
            texts.extend(str(value) for value in json.loads(needs_json or "[]"))
        try:
            for entity in json.loads(entities_json or "[]"):
                if not isinstance(entity, dict):
                    continue
                texts.extend(
                    [
                        str(entity.get("id", "")),
                        str(entity.get("name", "")),
                        *(str(alias) for alias in entity.get("aliases", [])),
                    ]
                )
        except (json.JSONDecodeError, TypeError):
            pass
        return build_search_document(texts, self.config)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    stable_key TEXT,
    emotions_json TEXT NOT NULL,
    needs_json TEXT NOT NULL,
    status TEXT NOT NULL,
    consent TEXT NOT NULL,
    sensitivity TEXT NOT NULL,
    retention TEXT NOT NULL,
    confidence REAL NOT NULL,
    salience REAL NOT NULL,
    event_at TEXT NOT NULL,
    valid_from TEXT NOT NULL,
    valid_to TEXT,
    expires_at TEXT,
    supersedes_id TEXT,
    source_ref TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    entities_json TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (supersedes_id) REFERENCES memories(id)
);

CREATE TABLE IF NOT EXISTS evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    source_excerpt TEXT,
    evidence_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id TEXT,
    user_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_embeddings (
    memory_id TEXT PRIMARY KEY,
    space TEXT NOT NULL,
    dimensions INTEGER NOT NULL,
    vector BLOB NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS conversation_events (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    status TEXT NOT NULL,
    consent TEXT NOT NULL,
    sensitivity TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    entities_json TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS event_embeddings (
    event_id TEXT PRIMARY KEY,
    space TEXT NOT NULL,
    dimensions INTEGER NOT NULL,
    vector BLOB NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (event_id) REFERENCES conversation_events(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_memories_user_status
    ON memories(user_id, status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_memories_user_kind
    ON memories(user_id, kind, status);
CREATE INDEX IF NOT EXISTS idx_memories_stable
    ON memories(user_id, kind, stable_key, status);
CREATE INDEX IF NOT EXISTS idx_memories_expiry
    ON memories(status, expires_at);
CREATE INDEX IF NOT EXISTS idx_memories_hash
    ON memories(user_id, kind, content_hash, status);
CREATE INDEX IF NOT EXISTS idx_audit_user
    ON audit_events(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_memory_embeddings_space
    ON memory_embeddings(space, dimensions);
CREATE INDEX IF NOT EXISTS idx_events_user_status_time
    ON conversation_events(user_id, status, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_expiry
    ON conversation_events(status, expires_at);
CREATE INDEX IF NOT EXISTS idx_event_embeddings_space
    ON event_embeddings(space, dimensions);

CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
    memory_id UNINDEXED,
    title,
    content,
    needs,
    entities,
    search_terms,
    tokenize = 'unicode61 remove_diacritics 2'
);

CREATE VIRTUAL TABLE IF NOT EXISTS event_fts USING fts5(
    event_id UNINDEXED,
    content,
    entities,
    search_terms,
    tokenize = 'unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS memories_fts_insert
AFTER INSERT ON memories
WHEN new.status IN ('active', 'superseded')
BEGIN
    INSERT INTO memory_fts(memory_id, title, content, needs, entities, search_terms)
    VALUES (
        new.id,
        new.title,
        new.content,
        new.needs_json,
        new.entities_json,
        companion_search_terms(new.title, new.content, new.needs_json, new.entities_json)
    );
END;

CREATE TRIGGER IF NOT EXISTS memories_fts_update
AFTER UPDATE ON memories
BEGIN
    DELETE FROM memory_fts WHERE memory_id = old.id;
    INSERT INTO memory_fts(memory_id, title, content, needs, entities, search_terms)
    SELECT
        new.id,
        new.title,
        new.content,
        new.needs_json,
        new.entities_json,
        companion_search_terms(new.title, new.content, new.needs_json, new.entities_json)
    WHERE new.status IN ('active', 'superseded');
END;

CREATE TRIGGER IF NOT EXISTS memories_fts_delete
AFTER DELETE ON memories
BEGIN
    DELETE FROM memory_fts WHERE memory_id = old.id;
END;

CREATE TRIGGER IF NOT EXISTS events_fts_insert
AFTER INSERT ON conversation_events
WHEN new.status = 'active'
BEGIN
    INSERT INTO event_fts(event_id, content, entities, search_terms)
    VALUES (
        new.id,
        new.content,
        new.entities_json,
        companion_search_terms('', new.content, '[]', new.entities_json)
    );
END;

CREATE TRIGGER IF NOT EXISTS events_fts_update
AFTER UPDATE ON conversation_events
BEGIN
    DELETE FROM event_fts WHERE event_id = old.id;
    INSERT INTO event_fts(event_id, content, entities, search_terms)
    SELECT
        new.id,
        new.content,
        new.entities_json,
        companion_search_terms('', new.content, '[]', new.entities_json)
    WHERE new.status = 'active';
END;

CREATE TRIGGER IF NOT EXISTS events_fts_delete
AFTER DELETE ON conversation_events
BEGIN
    DELETE FROM event_fts WHERE event_id = old.id;
END;
"""


_MIGRATION_1_TO_2 = """
DROP TRIGGER IF EXISTS memories_fts_insert;
DROP TRIGGER IF EXISTS memories_fts_update;
DROP TRIGGER IF EXISTS memories_fts_delete;
DROP TABLE IF EXISTS memory_fts;
ALTER TABLE memories ADD COLUMN entities_json TEXT NOT NULL DEFAULT '[]';
"""


_BACKFILL_MEMORY_FTS = """
INSERT INTO memory_fts(memory_id, title, content, needs, entities, search_terms)
SELECT
    id,
    title,
    content,
    needs_json,
    entities_json,
    companion_search_terms(title, content, needs_json, entities_json)
FROM memories
WHERE status IN ('active', 'superseded')
"""
