"""Developer-authored fiction, stored separately from user-derived memory evidence."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from companion_agent.persona.models import CharacterMemorySeed, PersonaDefinition, PersonaModel
from companion_memoryos.database import Database
from companion_memoryos.schemas import RealityLayer


class CharacterMemoryRecord(PersonaModel):
    source: Literal["canonical_backstory"] = "canonical_backstory"
    persona_id: str
    persona_version: str
    companion_id: str
    actor_id: str
    subject_actor_id: str
    reality_layer: RealityLayer = RealityLayer.FICTION
    seed: CharacterMemorySeed


class CharacterMemoryStore:
    """Versioned seeds in the MemoryOS database; no user facts or fabricated timestamps."""

    def __init__(self, database: Database) -> None:
        self.database = database
        with database.atomic() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS agent_persona_sources ("
                "companion_id TEXT NOT NULL, persona_id TEXT NOT NULL, version TEXT NOT NULL, "
                "source_hash TEXT NOT NULL, seeds_json TEXT NOT NULL, "
                "PRIMARY KEY (companion_id, persona_id, version))"
            )

    def install(self, persona: PersonaDefinition, companion_id: str) -> None:
        if not companion_id.strip():
            raise ValueError("companion_id cannot be blank")
        source = persona.model_dump(mode="json")
        # Adding a schema default or renaming the legacy stage must not invalidate the
        # content hash of an unchanged v0.1/v0.2 persona file.
        if not source["identity_styles"]:
            source.pop("identity_styles")
        source["relationship_styles"]["close"] = source["relationship_styles"].pop("established")
        canonical = json.dumps(source, sort_keys=True, ensure_ascii=False)
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        seeds = json.dumps([item.model_dump(mode="json") for item in persona.character_memories])
        with self.database.atomic() as connection:
            previous = connection.execute(
                "SELECT source_hash FROM agent_persona_sources "
                "WHERE companion_id = ? AND persona_id = ? AND version = ?",
                (companion_id, persona.persona_id, persona.version),
            ).fetchone()
            if previous is not None:
                if previous["source_hash"] != digest:
                    raise ValueError(
                        "persona content changed: increment version before installation"
                    )
                return
            connection.execute(
                "INSERT INTO agent_persona_sources VALUES (?, ?, ?, ?, ?)",
                (companion_id, persona.persona_id, persona.version, digest, seeds),
            )

    def recall(
        self,
        persona_id: str,
        persona_version: str,
        companion_id: str,
        query: str,
        *,
        limit: int = 3,
    ) -> list[CharacterMemoryRecord]:
        if limit < 0:
            raise ValueError("limit cannot be negative")
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT seeds_json FROM agent_persona_sources "
                "WHERE companion_id = ? AND persona_id = ? AND version = ?",
                (companion_id, persona_id, persona_version),
            ).fetchone()
        if row is None:
            return []
        seeds = [CharacterMemorySeed.model_validate(item) for item in json.loads(row["seeds_json"])]
        matches = [
            seed
            for seed in seeds
            if any(topic.casefold() in query.casefold() for topic in seed.topic_keys)
        ]
        matches.sort(key=lambda seed: (-seed.salience, seed.id))
        return [
            CharacterMemoryRecord(
                persona_id=persona_id,
                persona_version=persona_version,
                companion_id=companion_id,
                actor_id=companion_id,
                subject_actor_id=companion_id,
                seed=seed,
            )
            for seed in matches[:limit]
        ]
