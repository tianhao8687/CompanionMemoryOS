from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from companion_memoryos.config import CompanionConfig
from companion_memoryos.constants import DATABASE_SCHEMA_VERSION
from companion_memoryos.database import Database
from companion_memoryos.schemas import (
    ConsentState,
    ConversationRole,
    ConversationTurnInput,
    MemoryScope,
    RecallRequest,
)
from companion_memoryos.service import CompanionMemoryService
from companion_memoryos.store import (
    MemoryStore,
    datetime_to_text,
    exact_payload_digest,
    scope_values,
)

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


def test_v6_response_plans_gain_staged_resolution_columns(
    tmp_path: Path, config: CompanionConfig
) -> None:
    database = Database(tmp_path, config)
    database.initialize()
    with database.connection() as connection:
        connection.executescript(
            """
            ALTER TABLE response_plans DROP COLUMN revision;
            ALTER TABLE response_plans DROP COLUMN resolution_status;
            ALTER TABLE response_plans DROP COLUMN resolution_request_json;
            ALTER TABLE response_plans DROP COLUMN resolution_key;
            ALTER TABLE response_plans DROP COLUMN resolved_at;
            PRAGMA user_version = 6;
            """
        )

    database.initialize()

    with database.connection() as connection:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        columns = {
            str(row["name"]) for row in connection.execute("PRAGMA table_info(response_plans)")
        }
    assert version == DATABASE_SCHEMA_VERSION
    assert {
        "revision",
        "resolution_status",
        "resolution_request_json",
        "resolution_key",
        "resolved_at",
    } <= columns


def test_v2_database_is_upgraded_with_relationship_ledger_storage(
    tmp_path: Path,
    config: CompanionConfig,
) -> None:
    path = tmp_path / "companion-memoryos.db"
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version = 2")

    database = Database(tmp_path, config)
    database.initialize()

    with database.connection() as connection:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'temporal_anchors'"
        ).fetchone()
        turn_table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'conversation_turns'"
        ).fetchone()
        policy_version_table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'policy_versions'"
        ).fetchone()
        memory_columns = {
            str(row["name"]) for row in connection.execute("PRAGMA table_info(memories)")
        }
    assert version == DATABASE_SCHEMA_VERSION
    assert table is not None
    assert turn_table is not None
    assert policy_version_table is not None
    assert {"relationship_id", "epistemic_kind", "valid_time_start"} <= memory_columns


def test_v3_database_is_accepted_and_upgraded(tmp_path: Path, config: CompanionConfig) -> None:
    path = tmp_path / "companion-memoryos.db"
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version = 3")
    database = Database(tmp_path, config)
    database.initialize()
    with database.connection() as connection:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        policy_table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'policy_constraints'"
        ).fetchone()
    assert version == DATABASE_SCHEMA_VERSION
    assert policy_table is not None


def test_v4_database_adds_explicit_turn_idempotency_key(
    tmp_path: Path,
    config: CompanionConfig,
) -> None:
    database = Database(tmp_path, config)
    database.initialize()
    with database.connection() as connection:
        connection.execute("DROP INDEX idx_turns_idempotency")
        connection.execute("ALTER TABLE conversation_turns DROP COLUMN idempotency_key")
        connection.execute("PRAGMA user_version = 4")

    database.initialize()

    with database.connection() as connection:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        columns = {
            str(row["name"]) for row in connection.execute("PRAGMA table_info(conversation_turns)")
        }
        index = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND name = 'idx_turns_idempotency'"
        ).fetchone()
    assert version == DATABASE_SCHEMA_VERSION
    assert "idempotency_key" in columns
    assert index is not None


def test_v5_database_adds_companion_experience_storage(
    tmp_path: Path,
    config: CompanionConfig,
) -> None:
    database = Database(tmp_path, config)
    database.initialize()
    service = CompanionMemoryService(MemoryStore(database), config)
    delivery = ConversationTurnInput(
        user_id="alice",
        scope=MemoryScope(relationship_id="relationship-a", conversation_id="conversation-a"),
        actor_id="alice",
        role=ConversationRole.USER,
        content="迁移前保存的原始小事",
        consent=ConsentState.GRANTED,
        idempotency_key="legacy-provider-message",
    )
    stored = service.append_turn(delivery)
    assert stored.turn is not None
    legacy_digest = exact_payload_digest(
        delivery.user_id,
        *(value or "" for value in scope_values(delivery.scope)),
        delivery.actor_id,
        delivery.role.value,
        datetime_to_text(delivery.occurred_at) or "",
        delivery.content,
        delivery.consent.value,
        delivery.sensitivity.value,
        delivery.modality.value,
        delivery.language or "",
        delivery.reply_to_turn_id or "",
        delivery.supersedes_turn_id or "",
        delivery.source_ref,
        "[]",
        "{}",
    )
    with database.connection() as connection:
        connection.execute(
            "UPDATE conversation_turns SET content_hash = ? WHERE id = ?",
            (legacy_digest, stored.turn.id),
        )
        connection.executescript(
            """
            DROP TRIGGER turns_fts_insert;
            DROP TRIGGER turns_fts_update;
            DROP TRIGGER turns_fts_delete;
            DROP INDEX idx_turns_episode;
            DROP TABLE experience_evidence_uses;
            DROP TABLE response_beats;
            DROP TABLE response_plans;
            DROP TABLE memory_reference_feedback;
            DROP TABLE open_loops;
            DROP TABLE turn_embeddings;
            ALTER TABLE conversation_turns DROP COLUMN retrieval_keys_json;
            ALTER TABLE conversation_turns DROP COLUMN embedding_space;
            ALTER TABLE conversation_turns DROP COLUMN episode_id;
            PRAGMA user_version = 5;
            """
        )

    database.initialize()

    with database.connection() as connection:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        turn_columns = {
            str(row["name"]) for row in connection.execute("PRAGMA table_info(conversation_turns)")
        }
        tables = {
            str(row["name"])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert version == DATABASE_SCHEMA_VERSION
    assert {"retrieval_keys_json", "embedding_space", "episode_id"} <= turn_columns
    assert {
        "turn_embeddings",
        "open_loops",
        "memory_reference_feedback",
        "response_plans",
        "response_beats",
        "experience_evidence_uses",
    } <= tables
    replayed = service.append_turn(delivery)
    assert replayed.duplicate_of == stored.turn.id
    assert replayed.cancelled_response_plan_ids == []


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
        anchor_table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'temporal_anchors'"
        ).fetchone()
    assert version == DATABASE_SCHEMA_VERSION
    assert anchor_table is not None
    assert context.sections["shared_history"][0].memory.id == "legacy-memory"
