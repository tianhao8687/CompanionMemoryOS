from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from pathlib import Path

from companion_memoryos.config import CompanionConfig
from companion_memoryos.constants import DATABASE_SCHEMA_VERSION, SQLITE_INTEGRITY_OK
from companion_memoryos.scoring import build_search_document
from companion_memoryos.turn_layers import turn_reality_layer


class Database:
    def __init__(self, data_dir: Path, config: CompanionConfig) -> None:
        self.data_dir = data_dir.expanduser().resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.data_dir / "companion-memoryos.db"
        self.config = config
        self._active_connection: ContextVar[sqlite3.Connection | None] = ContextVar(
            f"companion_connection_{id(self)}", default=None
        )

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        active = self._active_connection.get()
        if active is not None:
            yield active
            return
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
        connection.create_function(
            "companion_turn_reality",
            3,
            turn_reality_layer,
            deterministic=True,
        )
        token = self._active_connection.set(connection)
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            self._active_connection.reset(token)
            connection.close()

    @contextmanager
    def atomic(self) -> Iterator[sqlite3.Connection]:
        """Reuse one local transaction across a group of existing core operations."""
        with self.connection() as connection:
            if not connection.in_transaction:
                connection.execute("BEGIN IMMEDIATE")
            yield connection

    def initialize(self) -> None:
        with self.connection() as connection:
            current = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if current not in set(range(DATABASE_SCHEMA_VERSION + 1)):
                raise RuntimeError(f"unsupported database schema version: {current}")
            if current == 1:
                connection.executescript(_MIGRATION_1_TO_2)
            if current in set(range(1, DATABASE_SCHEMA_VERSION + 1)):
                self._ensure_current_columns(connection)
            if current in {1, 2, 3}:
                connection.execute("DROP INDEX IF EXISTS idx_temporal_anchors_active_name")
            connection.executescript(_DROP_REFRESHED_TRIGGERS)
            connection.executescript(_SCHEMA)
            connection.execute(_BACKFILL_POLICY_VERSIONS)
            if current == 1:
                connection.execute(_BACKFILL_MEMORY_FTS)
            connection.execute(f"PRAGMA user_version = {DATABASE_SCHEMA_VERSION}")

    @staticmethod
    def _ensure_current_columns(connection: sqlite3.Connection) -> None:
        migrations: dict[str, dict[str, str]] = {
            "memories": {
                "companion_id": "TEXT",
                "relationship_id": "TEXT",
                "conversation_id": "TEXT",
                "group_id": "TEXT",
                "valid_time_start": "TEXT",
                "valid_time_end": "TEXT",
                "epistemic_kind": "TEXT NOT NULL DEFAULT 'observation'",
                "resolution_status": "TEXT NOT NULL DEFAULT 'resolved'",
                "reality_layer": "TEXT NOT NULL DEFAULT 'real_world'",
                "source_actor": "TEXT NOT NULL DEFAULT 'authenticated_user'",
                "quote_depth": "INTEGER NOT NULL DEFAULT 0",
                "elicitation_kind": "TEXT NOT NULL DEFAULT 'spontaneous'",
                "subject_actor_id": "TEXT",
                "predicate": "TEXT",
                "evidence_turn_ids_json": "TEXT NOT NULL DEFAULT '[]'",
            },
            "conversation_events": {
                "companion_id": "TEXT",
                "relationship_id": "TEXT",
                "conversation_id": "TEXT",
                "group_id": "TEXT",
            },
            "temporal_anchors": {
                "companion_id": "TEXT",
                "relationship_id": "TEXT",
                "conversation_id": "TEXT",
                "group_id": "TEXT",
            },
            "conversation_turns": {
                "speech_spans_json": "TEXT NOT NULL DEFAULT '[]'",
                "idempotency_key": "TEXT",
                "retrieval_keys_json": "TEXT NOT NULL DEFAULT '[]'",
                "embedding_space": "TEXT",
                "episode_id": "TEXT",
            },
            "response_plans": {
                "revision": "INTEGER NOT NULL DEFAULT 0",
                "resolution_status": "TEXT NOT NULL DEFAULT 'resolved'",
                "resolution_request_json": "TEXT",
                "resolution_key": "TEXT",
                "resolved_at": "TEXT",
            },
            "memory_use_events": {
                "use_type": "TEXT NOT NULL DEFAULT 'explicit_reference'",
            },
        }
        for table, columns in migrations.items():
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table,),
            ).fetchone()
            if exists is None:
                continue
            existing = {
                str(row["name"]) for row in connection.execute(f"PRAGMA table_info({table})")
            }
            for column, definition in columns.items():
                if column not in existing:
                    connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
                    if table == "memory_use_events" and column == "use_type":
                        connection.execute(
                            "UPDATE memory_use_events SET use_type = CASE use_mode "
                            "WHEN 'hedge' THEN 'soft_reference' "
                            "WHEN 'do_not_assert' THEN 'clarification' "
                            "ELSE 'explicit_reference' END"
                        )
        memory_exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'memories'"
        ).fetchone()
        if memory_exists is not None:
            connection.execute(
                "UPDATE memories SET valid_time_start = event_at WHERE valid_time_start IS NULL"
            )
        event_exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'conversation_events'"
        ).fetchone()
        if event_exists is not None:
            connection.execute(
                "UPDATE conversation_events SET conversation_id = session_id "
                "WHERE conversation_id IS NULL"
            )

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
    companion_id TEXT,
    relationship_id TEXT,
    conversation_id TEXT,
    group_id TEXT,
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
    valid_time_start TEXT NOT NULL,
    valid_time_end TEXT,
    valid_from TEXT NOT NULL,
    valid_to TEXT,
    expires_at TEXT,
    supersedes_id TEXT,
    source_ref TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    entities_json TEXT NOT NULL,
    epistemic_kind TEXT NOT NULL,
    resolution_status TEXT NOT NULL,
    reality_layer TEXT NOT NULL,
    source_actor TEXT NOT NULL,
    quote_depth INTEGER NOT NULL,
    elicitation_kind TEXT NOT NULL,
    subject_actor_id TEXT,
    predicate TEXT,
    evidence_turn_ids_json TEXT NOT NULL,
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
    companion_id TEXT,
    relationship_id TEXT,
    conversation_id TEXT,
    group_id TEXT,
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

CREATE TABLE IF NOT EXISTS temporal_anchors (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    companion_id TEXT,
    relationship_id TEXT,
    conversation_id TEXT,
    group_id TEXT,
    name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    aliases_json TEXT NOT NULL,
    start_at TEXT NOT NULL,
    end_at TEXT NOT NULL,
    status TEXT NOT NULL,
    consent TEXT NOT NULL,
    sensitivity TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    supersedes_id TEXT,
    valid_from TEXT NOT NULL,
    valid_to TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (supersedes_id) REFERENCES temporal_anchors(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS conversation_turns (
    server_sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    user_id TEXT NOT NULL,
    companion_id TEXT,
    relationship_id TEXT,
    conversation_id TEXT NOT NULL,
    group_id TEXT,
    actor_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    consent TEXT NOT NULL,
    sensitivity TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    modality TEXT NOT NULL,
    language TEXT,
    reply_to_turn_id TEXT,
    supersedes_turn_id TEXT,
    episode_id TEXT,
    source_ref TEXT NOT NULL,
    idempotency_key TEXT,
    speech_spans_json TEXT NOT NULL,
    retrieval_keys_json TEXT NOT NULL,
    embedding_space TEXT,
    content_hash TEXT NOT NULL,
    deletion_state TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    FOREIGN KEY (reply_to_turn_id) REFERENCES conversation_turns(id) ON DELETE SET NULL,
    FOREIGN KEY (supersedes_turn_id) REFERENCES conversation_turns(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS turn_embeddings (
    turn_id TEXT PRIMARY KEY,
    space TEXT NOT NULL,
    dimensions INTEGER NOT NULL,
    vector BLOB NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (turn_id) REFERENCES conversation_turns(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS processing_watermarks (
    user_id TEXT NOT NULL,
    scope_key TEXT NOT NULL,
    scope_json TEXT NOT NULL,
    channel TEXT NOT NULL,
    status TEXT NOT NULL,
    durable_sequence INTEGER,
    indexed_sequence INTEGER,
    model_fingerprint TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, scope_key, channel)
);

CREATE TABLE IF NOT EXISTS episodes (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    companion_id TEXT,
    relationship_id TEXT NOT NULL,
    conversation_id TEXT,
    group_id TEXT,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    topic_keys_json TEXT NOT NULL,
    participant_actor_ids_json TEXT NOT NULL,
    reality_layer TEXT NOT NULL,
    started_at TEXT NOT NULL,
    last_event_at TEXT NOT NULL,
    status TEXT NOT NULL,
    merged_into_id TEXT,
    revision INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (merged_into_id) REFERENCES episodes(id)
);
CREATE INDEX IF NOT EXISTS idx_episodes_scope
    ON episodes(user_id, companion_id, relationship_id, group_id, last_event_at);
CREATE INDEX IF NOT EXISTS idx_turns_episode ON conversation_turns(user_id, episode_id);

CREATE TABLE IF NOT EXISTS turn_interpretations (
    id TEXT PRIMARY KEY,
    turn_id TEXT NOT NULL UNIQUE,
    user_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    record_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (turn_id) REFERENCES conversation_turns(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_interpretations_user ON turn_interpretations(user_id, created_at);

CREATE TABLE IF NOT EXISTS memory_use_events (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    companion_id TEXT,
    relationship_id TEXT,
    conversation_id TEXT,
    group_id TEXT,
    memory_id TEXT NOT NULL,
    response_group_id TEXT NOT NULL,
    use_mode TEXT NOT NULL,
    use_type TEXT NOT NULL DEFAULT 'explicit_reference',
    purpose TEXT NOT NULL,
    output_hash TEXT,
    used_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS policy_constraints (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    companion_id TEXT,
    relationship_id TEXT,
    conversation_id TEXT,
    group_id TEXT,
    action TEXT NOT NULL,
    channel TEXT NOT NULL,
    effect TEXT NOT NULL,
    status TEXT NOT NULL,
    version INTEGER NOT NULL,
    valid_from TEXT NOT NULL,
    valid_until TEXT,
    source_turn_id TEXT,
    reason_code TEXT NOT NULL,
    supersedes_id TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (source_turn_id) REFERENCES conversation_turns(id) ON DELETE SET NULL,
    FOREIGN KEY (supersedes_id) REFERENCES policy_constraints(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS policy_versions (
    user_id TEXT PRIMARY KEY,
    version INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS open_loops (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    companion_id TEXT,
    relationship_id TEXT NOT NULL,
    conversation_id TEXT,
    group_id TEXT,
    kind TEXT NOT NULL,
    summary TEXT NOT NULL,
    topic_keys_json TEXT NOT NULL,
    follow_up_mode TEXT NOT NULL,
    status TEXT NOT NULL,
    follow_up_after TEXT,
    expires_at TEXT,
    source_turn_id TEXT,
    consent TEXT NOT NULL,
    sensitivity TEXT NOT NULL,
    resolution_summary TEXT,
    last_followed_up_at TEXT,
    follow_up_count INTEGER NOT NULL,
    last_response_group_id TEXT,
    revision INTEGER NOT NULL,
    opened_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    resolved_at TEXT,
    metadata_json TEXT NOT NULL,
    FOREIGN KEY (source_turn_id) REFERENCES conversation_turns(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS memory_reference_feedback (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    companion_id TEXT,
    relationship_id TEXT,
    conversation_id TEXT,
    group_id TEXT,
    memory_id TEXT,
    evidence_kind TEXT NOT NULL,
    evidence_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    source_turn_id TEXT,
    note TEXT,
    recorded_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE,
    FOREIGN KEY (source_turn_id) REFERENCES conversation_turns(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS response_plans (
    id TEXT PRIMARY KEY,
    response_group_id TEXT NOT NULL UNIQUE,
    user_id TEXT NOT NULL,
    companion_id TEXT,
    relationship_id TEXT,
    conversation_id TEXT NOT NULL,
    group_id TEXT,
    trigger_turn_id TEXT NOT NULL,
    goal TEXT NOT NULL,
    delivery_mode TEXT NOT NULL,
    status TEXT NOT NULL,
    revision INTEGER NOT NULL,
    resolution_status TEXT NOT NULL,
    resolution_request_json TEXT,
    resolution_key TEXT,
    policy_version INTEGER NOT NULL,
    config_fingerprint TEXT NOT NULL,
    policy_bundle_json TEXT NOT NULL,
    cancel_on_new_user_turn INTEGER NOT NULL,
    recall_action TEXT,
    memory_use_plan_json TEXT NOT NULL,
    follow_up_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    resolved_at TEXT,
    cancelled_at TEXT,
    cancellation_reason TEXT,
    FOREIGN KEY (trigger_turn_id) REFERENCES conversation_turns(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS response_beats (
    id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    kind TEXT NOT NULL,
    source TEXT NOT NULL,
    release_condition TEXT NOT NULL,
    status TEXT NOT NULL,
    guidance TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    output_hash TEXT,
    sent_at TEXT,
    cancelled_at TEXT,
    FOREIGN KEY (plan_id) REFERENCES response_plans(id) ON DELETE CASCADE,
    UNIQUE (plan_id, ordinal)
);

CREATE TABLE IF NOT EXISTS experience_evidence_uses (
    beat_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    evidence_kind TEXT NOT NULL,
    evidence_id TEXT NOT NULL,
    used_at TEXT NOT NULL,
    PRIMARY KEY (beat_id, evidence_kind, evidence_id),
    FOREIGN KEY (beat_id) REFERENCES response_beats(id) ON DELETE CASCADE,
    FOREIGN KEY (plan_id) REFERENCES response_plans(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_experience_evidence_uses_lookup
    ON experience_evidence_uses(evidence_kind, evidence_id, used_at);
CREATE INDEX IF NOT EXISTS idx_reference_feedback_evidence
    ON memory_reference_feedback(user_id, evidence_kind, evidence_id, recorded_at DESC);

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
CREATE INDEX IF NOT EXISTS idx_turn_embeddings_space
    ON turn_embeddings(space, dimensions);
CREATE INDEX IF NOT EXISTS idx_temporal_anchors_user_status
    ON temporal_anchors(user_id, status, updated_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_temporal_anchors_active_name
    ON temporal_anchors(
        user_id,
        COALESCE(companion_id, ''),
        COALESCE(relationship_id, ''),
        COALESCE(conversation_id, ''),
        COALESCE(group_id, ''),
        normalized_name
    )
    WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_memories_scope_predicate
    ON memories(user_id, companion_id, relationship_id, predicate, status);
CREATE INDEX IF NOT EXISTS idx_turns_scope_time
    ON conversation_turns(
        user_id, companion_id, relationship_id, conversation_id, occurred_at DESC
    );
CREATE INDEX IF NOT EXISTS idx_turns_hash
    ON conversation_turns(user_id, conversation_id, content_hash);
CREATE INDEX IF NOT EXISTS idx_turns_episode
    ON conversation_turns(user_id, relationship_id, episode_id, occurred_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_turns_idempotency
    ON conversation_turns(
        user_id,
        COALESCE(companion_id, ''),
        COALESCE(relationship_id, ''),
        conversation_id,
        COALESCE(group_id, ''),
        idempotency_key
    )
    WHERE idempotency_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_memory_use_memory_time
    ON memory_use_events(user_id, memory_id, used_at DESC);
CREATE INDEX IF NOT EXISTS idx_policy_scope_action
    ON policy_constraints(
        user_id, companion_id, relationship_id, conversation_id,
        action, channel, status, version DESC
    );
CREATE UNIQUE INDEX IF NOT EXISTS idx_policy_user_version
    ON policy_constraints(user_id, version);
CREATE INDEX IF NOT EXISTS idx_open_loops_scope_status
    ON open_loops(user_id, companion_id, relationship_id, status, follow_up_after);
CREATE INDEX IF NOT EXISTS idx_reference_feedback_memory_time
    ON memory_reference_feedback(user_id, memory_id, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_response_plans_scope_status
    ON response_plans(
        user_id, companion_id, relationship_id, conversation_id, status, created_at DESC
    );
CREATE INDEX IF NOT EXISTS idx_response_beats_plan_order
    ON response_beats(plan_id, ordinal);

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

CREATE VIRTUAL TABLE IF NOT EXISTS turn_fts USING fts5(
    turn_id UNINDEXED,
    content,
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

CREATE TRIGGER IF NOT EXISTS turns_fts_insert
AFTER INSERT ON conversation_turns
WHEN new.deletion_state = 'active'
BEGIN
    INSERT INTO turn_fts(turn_id, content, search_terms)
    VALUES (
        new.id,
        new.content,
        companion_search_terms('', new.content, new.retrieval_keys_json, '[]')
    );
END;

CREATE TRIGGER IF NOT EXISTS turns_fts_update
AFTER UPDATE ON conversation_turns
BEGIN
    DELETE FROM turn_fts WHERE turn_id = old.id;
    INSERT INTO turn_fts(turn_id, content, search_terms)
    SELECT
        new.id,
        new.content,
        companion_search_terms('', new.content, new.retrieval_keys_json, '[]')
    WHERE new.deletion_state = 'active';
END;

CREATE TRIGGER IF NOT EXISTS turns_fts_delete
AFTER DELETE ON conversation_turns
BEGIN
    DELETE FROM turn_fts WHERE turn_id = old.id;
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


_BACKFILL_POLICY_VERSIONS = """
INSERT OR IGNORE INTO policy_versions(user_id, version, updated_at)
SELECT user_id, MAX(version), MAX(created_at)
FROM policy_constraints
GROUP BY user_id
"""


_DROP_REFRESHED_TRIGGERS = """
DROP TRIGGER IF EXISTS turns_fts_insert;
DROP TRIGGER IF EXISTS turns_fts_update;
DROP TRIGGER IF EXISTS turns_fts_delete;
"""
