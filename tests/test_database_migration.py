from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from companion_memoryos.config import CompanionConfig
from companion_memoryos.constants import DATABASE_SCHEMA_VERSION
from companion_memoryos.database import Database
from companion_memoryos.schemas import RecallRequest
from companion_memoryos.service import CompanionMemoryService
from companion_memoryos.store import MemoryStore, datetime_to_text

V1_SCHEMA = """
CREATE TABLE memories (
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
CREATE VIRTUAL TABLE memory_fts USING fts5(
    memory_id UNINDEXED,
    title,
    content,
    needs,
    tokenize = 'unicode61 remove_diacritics 2'
);
CREATE TRIGGER memories_fts_insert
AFTER INSERT ON memories
WHEN new.status = 'active'
BEGIN
    INSERT INTO memory_fts(memory_id, title, content, needs)
    VALUES (new.id, new.title, new.content, new.needs_json);
END;
CREATE TRIGGER memories_fts_update
AFTER UPDATE ON memories
BEGIN
    DELETE FROM memory_fts WHERE memory_id = old.id;
    INSERT INTO memory_fts(memory_id, title, content, needs)
    SELECT new.id, new.title, new.content, new.needs_json
    WHERE new.status = 'active';
END;
CREATE TRIGGER memories_fts_delete
AFTER DELETE ON memories
BEGIN
    DELETE FROM memory_fts WHERE memory_id = old.id;
END;
PRAGMA user_version = 1;
"""


def test_v1_database_is_upgraded_and_chinese_index_is_rebuilt(
    tmp_path: Path,
    config: CompanionConfig,
) -> None:
    path = tmp_path / "companion-memoryos.db"
    now = datetime.now(UTC)
    with sqlite3.connect(path) as connection:
        connection.executescript(V1_SCHEMA)
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
                "legacy-memory",
                "alice",
                "shared_moment",
                "旧版小事",
                "在虹桥公园见过一只橘色小猫",
                None,
                json.dumps([]),
                json.dumps([]),
                "active",
                "granted",
                "normal",
                "long_term",
                1.0,
                1.0,
                datetime_to_text(now),
                datetime_to_text(now),
                None,
                None,
                None,
                "conversation",
                "legacy-hash",
                json.dumps({}),
                datetime_to_text(now),
                datetime_to_text(now),
            ),
        )

    database = Database(tmp_path, config)
    database.initialize()
    database.initialize()
    service = CompanionMemoryService(MemoryStore(database), config)
    context = service.recall(RecallRequest(user_id="alice", query="虹桥公园的橘猫"))

    with database.connection() as connection:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    assert version == DATABASE_SCHEMA_VERSION
    assert context.sections["shared_history"][0].memory.id == "legacy-memory"
