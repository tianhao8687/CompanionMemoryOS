from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from companion_memoryos.config import CompanionConfig
from companion_memoryos.constants import DATABASE_SCHEMA_VERSION, SQLITE_INTEGRITY_OK


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
            if current not in {0, DATABASE_SCHEMA_VERSION}:
                raise RuntimeError(f"unsupported database schema version: {current}")
            connection.executescript(_SCHEMA)
            connection.execute(f"PRAGMA user_version = {DATABASE_SCHEMA_VERSION}")

    def integrity_check(self) -> None:
        with self.connection() as connection:
            result = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        if result != SQLITE_INTEGRITY_OK:
            raise RuntimeError(f"database integrity check failed: {result}")


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

CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
    memory_id UNINDEXED,
    title,
    content,
    needs,
    tokenize = 'unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS memories_fts_insert
AFTER INSERT ON memories
WHEN new.status = 'active'
BEGIN
    INSERT INTO memory_fts(memory_id, title, content, needs)
    VALUES (new.id, new.title, new.content, new.needs_json);
END;

CREATE TRIGGER IF NOT EXISTS memories_fts_update
AFTER UPDATE ON memories
BEGIN
    DELETE FROM memory_fts WHERE memory_id = old.id;
    INSERT INTO memory_fts(memory_id, title, content, needs)
    SELECT new.id, new.title, new.content, new.needs_json
    WHERE new.status = 'active';
END;

CREATE TRIGGER IF NOT EXISTS memories_fts_delete
AFTER DELETE ON memories
BEGIN
    DELETE FROM memory_fts WHERE memory_id = old.id;
END;
"""
