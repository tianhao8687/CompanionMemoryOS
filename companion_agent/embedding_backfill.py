"""Derived embedding maintenance. SQLite source versions always win publication races."""

from __future__ import annotations

import hashlib
from datetime import datetime
from threading import Event
from typing import TYPE_CHECKING

from companion_agent.evidence_policy import filter_recent_turns, restricted_evidence
from companion_agent.passages import passage_spans
from companion_agent.relationship.models import RelationshipKey
from companion_memoryos.schemas import (
    ConsentState,
    ConversationRole,
    ConversationTurnRecord,
    ExperienceEvidenceKind,
    ExperienceEvidenceRef,
    MemoryRecord,
    MemoryScope,
    MemoryStatus,
    MemoryUsePlan,
    Sensitivity,
)
from companion_memoryos.semantic_index import (
    CacheableSemanticIndex,
    PassageSemanticIndex,
    SemanticDocument,
    SemanticKind,
)
from companion_memoryos.store import utc_now

if TYPE_CHECKING:
    from companion_agent.cognition import ApplicationMemory, Embeddings


class EmbeddingBackfill:
    def __init__(
        self,
        memory: ApplicationMemory,
        embeddings: Embeddings,
        user_id: str,
        scope: MemoryScope,
        as_of: datetime,
        cancelled: Event,
        limit: int = 32,
    ) -> None:
        self.memory, self.embeddings = memory, embeddings
        self.user_id, self.scope, self.as_of = user_id, scope, as_of
        self.cancelled, self.remaining = cancelled, limit
        self.index = memory.store.semantic_index
        self.key = RelationshipKey(
            user_id=user_id,
            companion_id=scope.companion_id or "",
            relationship_id=scope.relationship_id or "",
        )

    def usable(self, source: MemoryRecord | ConversationTurnRecord) -> bool:
        if (
            self.cancelled.is_set()
            or self.memory.embeddings is not self.embeddings
            or self.memory.store.semantic_index is not self.index
        ):
            return False
        try:
            current = (
                self.memory.store.get_turn(source.id, self.user_id)
                if isinstance(source, ConversationTurnRecord)
                else self.memory.store.get(source.id, self.user_id)
            )
        except KeyError:
            return False
        if current.content_hash != source.content_hash:
            return False
        source = current
        if source.scope.group_id != self.scope.group_id:
            return False
        checked_at = max(self.as_of, utc_now())
        if isinstance(source, ConversationTurnRecord):
            return bool(
                filter_recent_turns(self.memory, self.key, [source], MemoryUsePlan(), checked_at)
            )
        if (
            source.status is not MemoryStatus.ACTIVE
            or source.consent is not ConsentState.GRANTED
            or source.sensitivity is not Sensitivity.NORMAL
            or source.valid_time_start > self.as_of
            or (source.valid_time_end is not None and source.valid_time_end <= self.as_of)
            or (source.expires_at is not None and source.expires_at <= self.as_of)
        ):
            return False
        if restricted_evidence(
            self.memory,
            self.key,
            [ExperienceEvidenceRef(kind=ExperienceEvidenceKind.MEMORY, id=source.id)],
            checked_at,
            conversation_id=self.scope.conversation_id,
        ):
            return False
        try:
            turns = [
                self.memory.store.get_turn(ref, self.user_id) for ref in source.evidence_turn_ids
            ]
        except KeyError:
            return False
        return len(
            filter_recent_turns(self.memory, self.key, turns, MemoryUsePlan(), checked_at)
        ) == len(turns)

    def cached(self, kind: SemanticKind) -> dict[str, str]:
        if not isinstance(self.index, CacheableSemanticIndex):
            return {}
        resident = self.index.indexed_ids(kind, self.user_id, self.embeddings.space)
        with self.memory.store.database.connection() as db:
            return {
                row["id"]: row["digest"]
                for row in db.execute(
                    "SELECT id, digest FROM agent_embedding_cache WHERE space=?",
                    (self.embeddings.space,),
                )
                if row["id"] in resident
            }

    def digest(self, source: MemoryRecord | ConversationTurnRecord) -> str | None:
        if not isinstance(self.index, CacheableSemanticIndex):
            return None
        mode = "passages-v1" if isinstance(self.index, PassageSemanticIndex) else "document-v1"
        return hashlib.sha256(
            (self.index.cache_namespace + ":" + mode + ":" + source.content_hash).encode()
        ).hexdigest()

    def publish(
        self,
        source: MemoryRecord | ConversationTurnRecord,
        vector: list[float],
        span: tuple[int, int] | None,
        digest: str | None,
    ) -> bool:
        is_turn = isinstance(source, ConversationTurnRecord)
        with self.memory.store.database.atomic() as db:
            try:
                current = (
                    self.memory.store.get_turn(source.id, self.user_id)
                    if is_turn
                    else self.memory.store.get(source.id, self.user_id)
                )
            except KeyError:
                return False
            if current.content_hash != source.content_hash or not self.usable(current):
                return False
            document = SemanticDocument(
                SemanticKind.TURN if is_turn else SemanticKind.MEMORY,
                source.id,
                self.user_id,
                source.scope,
                self.embeddings.space,
                vector,
                source_hash=source.content_hash,
            )
            if span is not None:
                if not isinstance(self.index, PassageSemanticIndex):
                    raise TypeError("passage publication requires a passage-capable index")
                self.index.upsert_passage(document, *span)
            else:
                self.index.upsert(document)
            if digest is not None:
                db.execute(
                    "INSERT OR REPLACE INTO agent_embedding_cache VALUES (?, ?, ?)",
                    (source.id, self.embeddings.space, digest),
                )
            return True

    def memories(self) -> bool:
        cached = self.cached(SemanticKind.MEMORY)
        for source in self.memory.store.list_memories(
            self.user_id, {MemoryStatus.ACTIVE}, scope=self.scope
        ):
            digest = self.digest(source)
            if (digest is not None and cached.get(source.id) == digest) or not self.usable(source):
                continue
            if self.remaining <= 0:
                return False
            self.remaining -= 1
            self.publish(source, self.embeddings.encode(source.content), None, digest)
        return not self.cancelled.is_set()

    def turns(self) -> bool:
        if not self.scope.companion_id or not self.scope.relationship_id:
            return True
        cached = self.cached(SemanticKind.TURN)
        domain = self.scope.model_copy(update={"conversation_id": None})
        for source in self.memory.store.list_turns(self.user_id, domain):
            if (
                source.role is not ConversationRole.USER
                or source.scope.group_id != self.scope.group_id
            ):
                continue
            digest = self.digest(source)
            if (digest is not None and cached.get(source.id) == digest) or not self.usable(source):
                continue
            if not isinstance(self.index, PassageSemanticIndex):
                if self.remaining <= 0:
                    return False
                self.remaining -= 1
                if not self.publish(source, self.embeddings.encode(source.content), None, digest):
                    return False
                continue
            spans = passage_spans(source.content)
            existing = {
                (start, end)
                for start, end, _ in self.index.passage_vectors(
                    source.id, self.user_id, self.embeddings.space, source.content_hash
                )
            }
            for span in spans:
                if span in existing:
                    continue
                if self.remaining <= 0 or not self.usable(source):
                    return False
                self.remaining -= 1
                vector = self.embeddings.encode(source.content[slice(*span)])
                if not self.publish(source, vector, span, digest if span == spans[-1] else None):
                    return False
        return not self.cancelled.is_set()
