from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from companion_memoryos.config import CompanionConfig
from companion_memoryos.constants import (
    DEFAULT_ENCODING,
    EMPTY_SCORE,
    MEMORY_SCHEMA_VERSION,
    MINIMUM_RESULT_LIMIT,
    STABLE_KEY_DIGEST_PREFIX_LENGTH,
)
from companion_memoryos.policy import decide_storage
from companion_memoryos.schemas import (
    CompanionContext,
    ExportBundle,
    MemoryInput,
    MemoryKind,
    MemoryRecord,
    MemoryStatus,
    ProfileSnapshot,
    RecallItem,
    RecallRequest,
    ReviewDecision,
    StorageAction,
    StorageResult,
)
from companion_memoryos.scoring import build_fts_query, score_memory
from companion_memoryos.store import MemoryStore

PINNED_KINDS = {MemoryKind.BOUNDARY}
STABLE_KINDS = {
    MemoryKind.IDENTITY,
    MemoryKind.PREFERENCE,
    MemoryKind.BOUNDARY,
    MemoryKind.SUPPORT_STRATEGY,
    MemoryKind.RITUAL,
}

SECTION_BY_KIND: dict[MemoryKind, str] = {
    MemoryKind.IDENTITY: "profile",
    MemoryKind.PREFERENCE: "profile",
    MemoryKind.BOUNDARY: "boundaries",
    MemoryKind.SUPPORT_STRATEGY: "support",
    MemoryKind.COMMITMENT: "continuity",
    MemoryKind.RITUAL: "continuity",
    MemoryKind.EMOTION_EPISODE: "emotional_context",
    MemoryKind.SHARED_MOMENT: "shared_history",
    MemoryKind.WELLBEING_SIGNAL: "wellbeing",
}

RESPONSE_GUIDANCE = [
    "始终遵守已确认的边界，即使它们与更高分的记忆冲突。",
    "记忆中的情绪只是过去的证据，不能覆盖用户此刻的表达。",
    "候选或推断信息不是事实；确认前不得当作用户身份或偏好。",
    "如果当前消息与旧记忆冲突，以当前消息为准并提出更正记忆。",
    "不得用内疚、排他、依赖、威胁离开或情绪施压来提高留存。",
]


class CompanionMemoryService:
    def __init__(self, store: MemoryStore, config: CompanionConfig) -> None:
        self.store = store
        self.config = config

    def remember(self, item: MemoryInput) -> StorageResult:
        decision = decide_storage(item, self.config)
        if decision.action is StorageAction.DISCARD:
            return StorageResult(action=decision.action, memory=None, reasons=decision.reasons)
        if self.config.policy.exact_duplicate_detection:
            duplicate = self.store.find_duplicate(item)
            if duplicate is not None:
                return StorageResult(
                    action=decision.action,
                    memory=duplicate,
                    duplicate_of=duplicate.id,
                    reasons=[*decision.reasons, "exact_duplicate"],
                )
        stable_key = item.stable_key
        if stable_key is None and item.kind in STABLE_KINDS:
            digest = hashlib.sha256(item.title.casefold().encode(DEFAULT_ENCODING)).hexdigest()
            stable_key = f"{item.kind.value}:{digest[:STABLE_KEY_DIGEST_PREFIX_LENGTH]}"
        metadata = {
            **item.metadata,
            "memory_schema_version": MEMORY_SCHEMA_VERSION,
            "policy_reasons": decision.reasons,
        }
        memory = self.store.create(item, decision, stable_key, metadata)
        return StorageResult(action=decision.action, memory=memory, reasons=decision.reasons)

    def review(
        self,
        memory_id: str,
        user_id: str,
        decision: ReviewDecision,
    ) -> MemoryRecord:
        return self.store.review(memory_id, user_id, decision is ReviewDecision.CONFIRM)

    def recall(self, request: RecallRequest) -> CompanionContext:
        limit = request.limit or self.config.retrieval.default_limit
        limit = max(MINIMUM_RESULT_LIMIT, min(limit, self.config.retrieval.max_limit))
        budget = request.max_characters or self.config.retrieval.default_max_characters
        budget = max(MINIMUM_RESULT_LIMIT, min(budget, self.config.retrieval.max_characters))
        fts_query = build_fts_query(request.query, self.config)
        pool = self.store.active_pool(
            request.user_id,
            fts_query,
            self.config.retrieval.candidate_pool,
            request.as_of,
        )
        items = [self._recall_item(memory, request) for memory in pool]
        items.sort(key=lambda item: (not item.pinned, -item.score.total, item.memory.id))
        pinned = [item for item in items if item.pinned]
        selected = [*pinned]
        selected_ids = {item.memory.id for item in selected}
        for item in items:
            if item.memory.id in selected_ids or len(selected) >= limit:
                continue
            selected.append(item)
            selected_ids.add(item.memory.id)

        rendered = sum(self._rendered_length(item) for item in pinned)
        budgeted = [*pinned]
        for item in selected:
            if item.pinned:
                continue
            item_length = self._rendered_length(item)
            if rendered + item_length <= budget:
                budgeted.append(item)
                rendered += item_length
        sections: dict[str, list[RecallItem]] = {}
        for item in budgeted:
            sections.setdefault(SECTION_BY_KIND[item.memory.kind], []).append(item)
        return CompanionContext(
            user_id=request.user_id,
            intent=request.intent,
            sections=sections,
            guidance=RESPONSE_GUIDANCE,
            pending_review_count=self.store.pending_count(request.user_id),
            config_fingerprint=self.config.fingerprint(),
            generated_at=datetime.now(UTC),
            character_budget=budget,
            rendered_characters=rendered,
            safety_budget_exceeded=rendered > budget,
        )

    def profile(self, user_id: str) -> ProfileSnapshot:
        active = self.store.list_memories(user_id, {MemoryStatus.ACTIVE})
        return ProfileSnapshot(
            user_id=user_id,
            identity=self._of_kind(active, MemoryKind.IDENTITY),
            preferences=self._of_kind(active, MemoryKind.PREFERENCE),
            boundaries=self._of_kind(active, MemoryKind.BOUNDARY),
            support_strategies=self._of_kind(active, MemoryKind.SUPPORT_STRATEGY),
            rituals=self._of_kind(active, MemoryKind.RITUAL),
            pending_review_count=self.store.pending_count(user_id),
        )

    def list_memories(
        self,
        user_id: str,
        statuses: set[MemoryStatus] | None = None,
        limit: int | None = None,
    ) -> list[MemoryRecord]:
        return self.store.list_memories(user_id, statuses, limit)

    def forget(self, memory_id: str, user_id: str) -> MemoryRecord:
        return self.store.forget(memory_id, user_id)

    def purge(self, memory_id: str, user_id: str) -> None:
        self.store.purge(memory_id, user_id)

    def export(self, user_id: str) -> ExportBundle:
        return ExportBundle(
            schema_version=MEMORY_SCHEMA_VERSION,
            exported_at=datetime.now(UTC),
            user_id=user_id,
            memories=self.store.list_memories(user_id),
        )

    def _recall_item(self, memory: MemoryRecord, request: RecallRequest) -> RecallItem:
        score = score_memory(memory, request, self.config, request.as_of)
        reasons = []
        if score.lexical > EMPTY_SCORE:
            reasons.append("query_match")
        if score.emotion > EMPTY_SCORE:
            reasons.append("emotion_match")
        if score.need > EMPTY_SCORE:
            reasons.append("need_match")
        if memory.kind in PINNED_KINDS:
            reasons.append("safety_boundary")
        return RecallItem(
            memory=memory,
            score=score,
            reasons=reasons,
            pinned=memory.kind in PINNED_KINDS,
        )

    @staticmethod
    def _rendered_length(item: RecallItem) -> int:
        return len(item.memory.title) + len(item.memory.content)

    @staticmethod
    def _of_kind(memories: list[MemoryRecord], kind: MemoryKind) -> list[MemoryRecord]:
        return [memory for memory in memories if memory.kind is kind]
