from __future__ import annotations

import json
from typing import Any

from companion_agent.experience.models import (
    ExperienceCandidate,
    ExperienceDecision,
    ExperienceRecord,
)
from companion_agent.relationship.models import RelationshipKey, now_utc
from companion_agent.relationship.store import KEY_SQL, RelationshipConflictError
from companion_memoryos.database import Database


class ExperienceStore:
    def __init__(self, database: Database) -> None:
        self.database = database
        with database.atomic() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS agent_schema_versions "
                "(component TEXT PRIMARY KEY, version INTEGER NOT NULL)"
            )
            version = connection.execute(
                "SELECT version FROM agent_schema_versions WHERE component='experience'"
            ).fetchone()
            if version and version["version"] > 1:
                raise ValueError("experience database schema is newer than this runtime")
            domain = (
                "user_id TEXT NOT NULL, companion_id TEXT NOT NULL, relationship_id TEXT NOT NULL"
            )
            connection.execute(
                f"CREATE TABLE IF NOT EXISTS agent_experiences ({domain}, "
                "experience_id TEXT NOT NULL, anchor_id TEXT NOT NULL, type TEXT NOT NULL, "
                "status TEXT NOT NULL, revision INTEGER NOT NULL, data_json TEXT NOT NULL, "
                "PRIMARY KEY(user_id, companion_id, relationship_id, experience_id))"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_agent_experiences_anchor "
                "ON agent_experiences(user_id, companion_id, relationship_id, anchor_id, type)"
            )
            connection.execute(
                f"CREATE TABLE IF NOT EXISTS agent_experience_candidates ({domain}, "
                "candidate_id TEXT NOT NULL, data_json TEXT NOT NULL, decision_json TEXT, "
                "PRIMARY KEY(user_id, companion_id, relationship_id, candidate_id))"
            )
            connection.execute(
                f"CREATE TABLE IF NOT EXISTS agent_experience_revisions ({domain}, "
                "experience_id TEXT NOT NULL, revision INTEGER NOT NULL, data_json TEXT NOT NULL, "
                "PRIMARY KEY(user_id, companion_id, relationship_id, experience_id, revision))"
            )
            connection.execute(
                "INSERT OR IGNORE INTO agent_schema_versions VALUES ('experience', 1)"
            )

    def get(self, key: RelationshipKey, experience_id: str) -> ExperienceRecord:
        with self.database.connection() as connection:
            row = connection.execute(
                f"SELECT data_json FROM agent_experiences WHERE {KEY_SQL} AND experience_id=?",
                (*key.values, experience_id),
            ).fetchone()
        if row is None:
            raise KeyError(experience_id)
        return ExperienceRecord.model_validate_json(row["data_json"])

    def list_experiences(self, key: RelationshipKey) -> list[ExperienceRecord]:
        with self.database.connection() as connection:
            rows = connection.execute(
                f"SELECT data_json FROM agent_experiences WHERE {KEY_SQL} ORDER BY rowid",
                key.values,
            ).fetchall()
        return [ExperienceRecord.model_validate_json(row["data_json"]) for row in rows]

    def save(
        self, record: ExperienceRecord, before: ExperienceRecord | None, action: str
    ) -> ExperienceRecord:
        record = record.model_copy(deep=True)
        record.revision = before.revision + 1 if before else 1
        record.updated_at = now_utc()
        with self.database.atomic() as connection:
            if before:
                changed = connection.execute(
                    f"UPDATE agent_experiences SET anchor_id=?, status=?, revision=?, data_json=? "
                    f"WHERE {KEY_SQL} AND experience_id=? AND revision=?",
                    (
                        record.anchor_id,
                        record.status.value,
                        record.revision,
                        record.model_dump_json(),
                        *record.key.values,
                        record.experience_id,
                        before.revision,
                    ),
                ).rowcount
                if changed != 1:
                    raise RelationshipConflictError("experience revision changed")
            else:
                connection.execute(
                    "INSERT INTO agent_experiences VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        *record.key.values,
                        record.experience_id,
                        record.anchor_id,
                        record.type.value,
                        record.status.value,
                        record.revision,
                        record.model_dump_json(),
                    ),
                )
            receipt = {
                "revision": record.revision,
                "action": action,
                "created_at": record.updated_at.isoformat(),
                "before": before.model_dump(mode="json") if before else None,
                "after": record.model_dump(mode="json"),
            }
            connection.execute(
                "INSERT INTO agent_experience_revisions VALUES (?, ?, ?, ?, ?, ?)",
                (
                    *record.key.values,
                    record.experience_id,
                    record.revision,
                    json.dumps(receipt, ensure_ascii=False),
                ),
            )
        return record

    def stage(self, candidate: ExperienceCandidate) -> ExperienceDecision | None:
        with self.database.atomic() as connection:
            row = connection.execute(
                f"SELECT * FROM agent_experience_candidates WHERE {KEY_SQL} AND candidate_id=?",
                (*candidate.key.values, candidate.candidate_id),
            ).fetchone()
            if row:
                if ExperienceCandidate.model_validate_json(row["data_json"]) != candidate:
                    raise ValueError("experience candidate id reused with different data")
                return (
                    ExperienceDecision.model_validate_json(row["decision_json"])
                    if row["decision_json"]
                    else None
                )
            connection.execute(
                "INSERT INTO agent_experience_candidates VALUES (?, ?, ?, ?, ?, NULL)",
                (*candidate.key.values, candidate.candidate_id, candidate.model_dump_json()),
            )
        return None

    def acknowledge(self, key: RelationshipKey, decision: ExperienceDecision) -> None:
        with self.database.atomic() as connection:
            connection.execute(
                "UPDATE agent_experience_candidates SET decision_json=? "
                f"WHERE {KEY_SQL} AND candidate_id=?",
                (decision.model_dump_json(), *key.values, decision.candidate_id),
            )

    def candidates(self, key: RelationshipKey) -> list[dict[str, Any]]:
        with self.database.connection() as connection:
            rows = connection.execute(
                f"SELECT data_json, decision_json FROM agent_experience_candidates WHERE {KEY_SQL}",
                key.values,
            ).fetchall()
        return [
            {
                "candidate": json.loads(row["data_json"]),
                "decision": json.loads(row["decision_json"]) if row["decision_json"] else None,
            }
            for row in rows
        ]

    def history(self, key: RelationshipKey, experience_id: str) -> list[dict[str, Any]]:
        with self.database.connection() as connection:
            rows = connection.execute(
                f"SELECT data_json FROM agent_experience_revisions WHERE {KEY_SQL} "
                "AND experience_id=? ORDER BY revision",
                (*key.values, experience_id),
            ).fetchall()
        return [json.loads(row["data_json"]) for row in rows]
