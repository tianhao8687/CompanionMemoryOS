"""Additive SQLite migration, atomic snapshots, item indexes and candidate receipts."""

from __future__ import annotations

import json
from datetime import datetime

from companion_agent.relationship.models import (
    RelationshipChangeType,
    RelationshipDecision,
    RelationshipKey,
    RelationshipModel,
    RelationshipRevision,
    RelationshipUpdateCandidate,
)
from companion_memoryos.database import Database

KEY_SQL = "user_id = ? AND companion_id = ? AND relationship_id = ?"
ITEM_TABLES = {
    "patterns": "agent_relationship_patterns",
    "milestones": "agent_relationship_milestones",
    "unresolved_threads": "agent_relationship_threads",
    "boundaries": "agent_relationship_boundaries",
}


class RelationshipConflictError(ValueError):
    """The caller must reread the current revision before trying again."""


class RelationshipStore:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.migrate()

    def migrate(self) -> None:
        # Do not change MemoryOS PRAGMA user_version or its existing tables.
        with self.database.atomic() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS agent_schema_versions "
                "(component TEXT PRIMARY KEY, version INTEGER NOT NULL)"
            )
            row = connection.execute(
                "SELECT version FROM agent_schema_versions WHERE component = 'relationship'"
            ).fetchone()
            if row and row["version"] > 2:
                raise ValueError("relationship database schema is newer than this runtime")
            key = "user_id TEXT NOT NULL, companion_id TEXT NOT NULL, relationship_id TEXT NOT NULL"
            connection.execute(
                f"CREATE TABLE IF NOT EXISTS agent_relationship_models ({key}, "
                "revision INTEGER NOT NULL, data_json TEXT NOT NULL, "
                "PRIMARY KEY (user_id, companion_id, relationship_id))"
            )
            for table in ITEM_TABLES.values():
                connection.execute(
                    f"CREATE TABLE IF NOT EXISTS {table} ({key}, "
                    "id TEXT NOT NULL, data_json TEXT NOT NULL, "
                    "PRIMARY KEY (user_id, companion_id, relationship_id, id))"
                )
            connection.execute(
                f"CREATE TABLE IF NOT EXISTS agent_relationship_revisions ({key}, "
                "revision INTEGER NOT NULL, data_json TEXT NOT NULL, "
                "PRIMARY KEY (user_id, companion_id, relationship_id, revision))"
            )
            connection.execute(
                f"CREATE TABLE IF NOT EXISTS agent_relationship_candidates ({key}, "
                "candidate_id TEXT NOT NULL, data_json TEXT NOT NULL, "
                "decision_json TEXT, PRIMARY KEY "
                "(user_id, companion_id, relationship_id, candidate_id))"
            )
            connection.execute(
                f"CREATE TABLE IF NOT EXISTS agent_relationship_identity_configs ({key}, "
                "id TEXT NOT NULL, data_json TEXT NOT NULL, PRIMARY KEY "
                "(user_id, companion_id, relationship_id, id))"
            )
            if row is None or row["version"] < 2:
                for old in connection.execute(
                    "SELECT rowid, data_json FROM agent_relationship_models"
                ).fetchall():
                    model = RelationshipModel.model_validate_json(old["data_json"])
                    connection.execute(
                        "UPDATE agent_relationship_models SET data_json = ? WHERE rowid = ?",
                        (model.model_dump_json(), old["rowid"]),
                    )
                for old in connection.execute(
                    "SELECT rowid, data_json FROM agent_relationship_revisions"
                ).fetchall():
                    revision = RelationshipRevision.model_validate_json(old["data_json"])
                    for field in ("before", "after"):
                        snapshot = getattr(revision, field)
                        if snapshot:
                            setattr(
                                revision,
                                field,
                                RelationshipModel.model_validate(snapshot).model_dump(mode="json"),
                            )
                    connection.execute(
                        "UPDATE agent_relationship_revisions SET data_json = ? WHERE rowid = ?",
                        (revision.model_dump_json(), old["rowid"]),
                    )
                connection.execute(
                    "INSERT INTO agent_schema_versions VALUES ('relationship', 2) "
                    "ON CONFLICT(component) DO UPDATE SET version=excluded.version"
                )

    def get(self, key: RelationshipKey) -> RelationshipModel | None:
        with self.database.connection() as connection:
            row = connection.execute(
                f"SELECT data_json FROM agent_relationship_models WHERE {KEY_SQL}", key.values
            ).fetchone()
        return RelationshipModel.model_validate_json(row["data_json"]) if row else None

    def create(self, model: RelationshipModel) -> RelationshipModel:
        with self.database.atomic() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO agent_relationship_models VALUES (?, ?, ?, ?, ?)",
                (*model.key.values, model.revision, model.model_dump_json()),
            )
        stored = self.get(model.key)
        assert stored is not None
        return stored

    def save(
        self,
        before: RelationshipModel,
        after: RelationshipModel,
        change: RelationshipChangeType,
        summary: str,
        evidence_ids: list[str],
        as_of: datetime,
    ) -> RelationshipModel:
        if before.key != after.key:
            raise ValueError("cannot move relationship state across owners")
        after = after.model_copy(deep=True)
        after.revision = before.revision + 1
        after.updated_at = max(before.updated_at, as_of)
        after = RelationshipModel.model_validate(after.model_dump())
        revision = RelationshipRevision(
            revision=after.revision,
            created_at=after.updated_at,
            change_type=change,
            summary=summary,
            evidence_ids=list(dict.fromkeys(evidence_ids)),
            before=before.model_dump(mode="json"),
            after=after.model_dump(mode="json"),
        )
        with self.database.atomic() as connection:
            changed = connection.execute(
                f"UPDATE agent_relationship_models SET revision = ?, data_json = ? WHERE {KEY_SQL} "
                "AND revision = ?",
                (after.revision, after.model_dump_json(), *after.key.values, before.revision),
            ).rowcount
            if changed != 1:
                raise RelationshipConflictError(
                    "relationship revision changed; reread before update"
                )
            for field, table in ITEM_TABLES.items():
                connection.execute(f"DELETE FROM {table} WHERE {KEY_SQL}", after.key.values)
                connection.executemany(
                    f"INSERT INTO {table} VALUES (?, ?, ?, ?, ?)",
                    [
                        (*after.key.values, item.id, item.model_dump_json())
                        for item in getattr(after, field)
                    ],
                )
            connection.execute(
                "INSERT INTO agent_relationship_revisions VALUES (?, ?, ?, ?, ?)",
                (*after.key.values, revision.revision, revision.model_dump_json()),
            )
        return after

    def stage_candidate(self, key: RelationshipKey, candidate: RelationshipUpdateCandidate) -> None:
        with self.database.atomic() as connection:
            row = connection.execute(
                "SELECT data_json FROM agent_relationship_candidates "
                f"WHERE {KEY_SQL} AND candidate_id = ?",
                (*key.values, candidate.candidate_id),
            ).fetchone()
            if row is not None:
                prior = RelationshipUpdateCandidate.model_validate_json(row["data_json"])
                if prior != candidate:
                    raise ValueError("candidate_id reused with different content")
                return
            connection.execute(
                "INSERT INTO agent_relationship_candidates VALUES (?, ?, ?, ?, ?, NULL)",
                (*key.values, candidate.candidate_id, candidate.model_dump_json()),
            )

    def candidates(
        self, key: RelationshipKey
    ) -> list[tuple[RelationshipUpdateCandidate, RelationshipDecision | None]]:
        with self.database.connection() as connection:
            rows = connection.execute(
                f"SELECT * FROM agent_relationship_candidates WHERE {KEY_SQL} ORDER BY rowid",
                key.values,
            ).fetchall()
        return [
            (
                RelationshipUpdateCandidate.model_validate_json(row["data_json"]),
                RelationshipDecision.model_validate_json(row["decision_json"])
                if row["decision_json"]
                else None,
            )
            for row in rows
        ]

    def acknowledge(self, key: RelationshipKey, decision: RelationshipDecision) -> None:
        with self.database.atomic() as connection:
            connection.execute(
                "UPDATE agent_relationship_candidates SET decision_json = ? "
                f"WHERE {KEY_SQL} AND candidate_id = ?",
                (decision.model_dump_json(), *key.values, decision.candidate_id),
            )

    def history(self, key: RelationshipKey) -> list[RelationshipRevision]:
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT data_json FROM agent_relationship_revisions "
                f"WHERE {KEY_SQL} ORDER BY revision",
                key.values,
            ).fetchall()
        return [RelationshipRevision.model_validate_json(row["data_json"]) for row in rows]

    def delete(self, key: RelationshipKey) -> None:
        with self.database.atomic() as connection:
            for table in [
                *ITEM_TABLES.values(),
                "agent_relationship_revisions",
                "agent_relationship_candidates",
                "agent_relationship_models",
                "agent_relationship_identity_configs",
            ]:
                connection.execute(f"DELETE FROM {table} WHERE {KEY_SQL}", key.values)

    def export(self, key: RelationshipKey) -> str:
        model = self.get(key)
        return json.dumps(
            {
                "model": model.model_dump(mode="json") if model else None,
                "revisions": [item.model_dump(mode="json") for item in self.history(key)],
            },
            ensure_ascii=False,
        )
