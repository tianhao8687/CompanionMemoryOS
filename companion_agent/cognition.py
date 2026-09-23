"""Grounded application learning and replaceable embedding transport.

The bundled vectorizer is lexical feature hashing, not a pretrained embedding model.
Memory adoption runs in the background; uncertain proposals never interrupt conversation.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from itertools import pairwise
from typing import Literal

from pydantic import Field, model_validator

from companion_agent.deepseek import DeepSeekConfig
from companion_agent.directives import remember_directive
from companion_agent.memory_language import SENSITIVE, UNCERTAIN, forget_target, literal_memories
from companion_agent.persona.models import PersonaModel
from companion_memoryos.config import InterpreterConfig
from companion_memoryos.interpreter import OpenAICompatibleInterpreter
from companion_memoryos.schemas import (
    ConsentState,
    ConversationRole,
    ConversationTurnRecord,
    ExperienceEvidenceKind,
    MemoryInput,
    MemoryKind,
    MemoryRecord,
    MemoryReferenceFeedbackInput,
    MemoryStatus,
    ProcessTurnRequest,
    ProcessTurnResult,
    RealityLayer,
    RecallRequest,
    ReferenceFeedbackKind,
    ResolutionStatus,
    ReviewDecision,
    Sensitivity,
    TurnDeletionState,
)
from companion_memoryos.semantic_index import (
    SemanticDocument,
    SemanticKind,
    SQLiteSemanticIndex,
)
from companion_memoryos.service import CompanionMemoryService


class CognitionSettings(PersonaModel):
    extract_memory: bool = True
    model_extraction: bool = False
    embedding_backend: Literal["local", "api", "off"] = "local"
    # Separate embedding endpoint and environment credential; never reuse chat credentials.
    embedding: DeepSeekConfig = Field(
        default_factory=lambda: DeepSeekConfig(
            base_url="http://127.0.0.1:8080/v1",
            model="local-embedding",
            api_key_env="COMPANION_EMBEDDING_API_KEY",
        )
    )

    @model_validator(mode="before")
    @classmethod
    def migrate_review_setting(cls, value: object) -> object:
        if isinstance(value, dict):
            value = dict(value)
            value.pop("confirm_preferences_automatically", None)
        return value


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None


class Embeddings:
    def __init__(self, settings: CognitionSettings, *, offline: bool) -> None:
        self.settings = settings
        self.backend = (
            "local"
            if offline and settings.embedding_backend == "api"
            else (settings.embedding_backend)
        )
        self.space = (
            "lexical-hash-zh-v2:256"
            if self.backend == "local"
            else (
                "embedding:"
                + hashlib.sha256(
                    (settings.embedding.base_url + "/" + settings.embedding.model).encode()
                ).hexdigest()[:32]
            )
        )

    def encode(self, text: str) -> list[float]:
        if self.backend == "local":
            normalized = text.lower()
            for variants, canonical in [
                (("爱喝", "爱吃", "偏爱", "爱好"), "喜欢"),
                (("喜欢喝", "喜欢吃"), "喜欢"),
                (("美式", "拿铁", "卡布奇诺"), "咖啡"),
                (("称呼", "昵称", "名字"), "叫我"),
                (("说教", "讲道理", "给建议"), "建议"),
            ]:
                for variant in variants:
                    normalized = normalized.replace(variant, canonical)
            for filler in (
                "还记得",
                "记不记得",
                "记得",
                "现在",
                "目前",
                "什么",
                "哪些",
                "吗",
                "呢",
                "了",
            ):
                normalized = normalized.replace(filler, "")
            words = re.findall(r"[\u4e00-\u9fff]|[a-z0-9_]+", normalized)
            features = words + [a + b for a, b in pairwise(words)]
            vector = [0.0] * 256
            for feature in features:
                digest = hashlib.sha256(feature.encode()).digest()
                vector[int.from_bytes(digest[:2]) % 256] += 1 if digest[2] & 1 else -1
            norm = math.sqrt(sum(value * value for value in vector)) or 1
            return [value / norm for value in vector]
        if self.backend == "off":
            return []
        import os

        config = self.settings.embedding
        headers = {"Content-Type": "application/json"}
        key = os.environ.get(config.api_key_env)
        if key:
            headers["Authorization"] = "Bearer " + key
        request = urllib.request.Request(
            config.base_url + "/embeddings",
            data=json.dumps({"model": config.model, "input": text}).encode(),
            headers=headers,
        )
        try:
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=15) as response:
                raw = response.read(262145)
            if len(raw) > 262144:
                raise ValueError("embedding response too large")
            result = json.loads(raw)["data"][0]["embedding"]
            if not isinstance(result, list) or not 1 <= len(result) <= 4096:
                raise ValueError("invalid embedding dimension")
            vector = [float(value) for value in result]
            if not all(math.isfinite(value) for value in vector):
                raise ValueError("invalid embedding value")
            return vector
        except (OSError, ValueError, KeyError, TypeError, IndexError):
            raise ValueError("embedding_service_unavailable") from None


class ApplicationMemory(CompanionMemoryService):
    on_user_turn: Callable[[ConversationTurnRecord], None] | None = None

    def configure(
        self,
        settings: CognitionSettings,
        *,
        offline: bool,
        model: DeepSeekConfig,
        key: str | None,
    ) -> None:
        self.learning = settings
        self.embeddings = Embeddings(settings, offline=offline)
        self.embedding_status = "ready"
        self.turn_interpreter = None
        if settings.extract_memory and settings.model_extraction and not offline and key:
            config = InterpreterConfig(
                enabled=True,
                base_url=model.base_url,
                model=model.model,
                api_key_env="COMPANION_EXPLICIT_INTERPRETER_KEY",
                output_token_parameter="max_tokens",
            )
            self.turn_interpreter = OpenAICompatibleInterpreter(config, api_key=key)
        with self.store.database.connection() as db:
            db.execute("CREATE TABLE IF NOT EXISTS agent_learned_turns (id TEXT PRIMARY KEY)")
            db.execute(
                "CREATE TABLE IF NOT EXISTS agent_memory_actions "
                "(turn_id TEXT PRIMARY KEY, result_json TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS agent_embedding_cache "
                "(id TEXT NOT NULL, space TEXT NOT NULL, digest TEXT NOT NULL, "
                "PRIMARY KEY(id, space))"
            )

    def process_turn(self, request: ProcessTurnRequest) -> ProcessTurnResult:
        result = super().process_turn(request)
        turn = result.storage.turn
        if turn is None or request.consent is not ConsentState.GRANTED or result.response_stale:
            return result
        if turn.role is ConversationRole.USER and self.on_user_turn:
            self.on_user_turn(turn)
        actions: dict[str, int] = {}
        if turn.role is ConversationRole.USER:
            with self.store.database.atomic() as db:
                prior = db.execute("SELECT id FROM agent_learned_turns WHERE id=?", (turn.id,))
                if prior.fetchone() is None:
                    direct = self._direct_user_discourse_text(turn).strip()
                    target = forget_target(direct)
                    if target is not None:
                        actions["forgotten"] = self._forget_from_chat(turn, target)
                    else:
                        remember_directive(self, turn)
                    learned = (
                        literal_memories(direct)
                        if self.learning.extract_memory
                        and turn.sensitivity is Sensitivity.NORMAL
                        and target is None
                        else []
                    )
                    for fact in learned:
                        stable_key = (
                            "natural:" + hashlib.sha256(fact.subject.encode()).hexdigest()[:24]
                        )
                        decision = self.remember(
                            MemoryInput(
                                user_id=turn.user_id,
                                scope=turn.scope.model_copy(update={"conversation_id": None}),
                                kind=MemoryKind.PREFERENCE,
                                title="相处方式" if fact.reflection else "日常偏好",
                                content=fact.content,
                                stable_key=stable_key,
                                consent=turn.consent,
                                sensitivity=turn.sensitivity,
                                explicit_user_request=fact.reflection,
                                source_ref=f"turn:{turn.id}",
                                source_excerpt=fact.content,
                                evidence_turn_ids=[turn.id],
                                event_at=turn.occurred_at,
                                metadata={
                                    "extractor": "bounded-local-v2",
                                    "reflection": fact.reflection,
                                    "subject": fact.subject,
                                },
                            )
                        )
                        if decision.memory:
                            record = decision.memory
                            if record.status is MemoryStatus.CANDIDATE:
                                self._adopt(record, "literal_user_statement")
                            actions["learned"] = actions.get("learned", 0) + 1
                    if self.learning.extract_memory and target is None:
                        self._adopt_model_candidates(turn, direct)
                    db.execute("INSERT INTO agent_learned_turns VALUES (?)", (turn.id,))
                    db.execute(
                        "INSERT INTO agent_memory_actions VALUES (?, ?)",
                        (turn.id, json.dumps(actions)),
                    )
                else:
                    receipt = db.execute(
                        "SELECT result_json FROM agent_memory_actions WHERE turn_id=?", (turn.id,)
                    ).fetchone()
                    actions = json.loads(receipt[0]) if receipt else {}
        if result.response_context is None:
            # Preserve core attention / policy gates instead of creating a new recall path.
            return result
        recall = request.recall_request or RecallRequest(
            user_id=request.user_id,
            scope=request.scope,
            query=request.content[:4000],
            calendar_timezone=request.calendar_timezone,
            state_reality_layer=request.reality_layer,
            exclude_turn_ids=[turn.id],
        )
        if self.embeddings.backend != "off":
            try:
                self.index_active(request.user_id, request.scope)
                recall = recall.model_copy(
                    update={
                        "query_embedding": self.embeddings.encode(recall.query),
                        "embedding_space": self.embeddings.space,
                    }
                )
                self.embedding_status = "ready"
            except ValueError:
                # Retrieval remains available through FTS when a provider is unavailable.
                self.embedding_status = "unavailable_using_fts"
        result.response_context = self.recall(recall)
        if actions:
            result.response_context.guidance.append("application_memory:" + json.dumps(actions))
        return result

    def _adopt(self, record: MemoryRecord, reason: str) -> None:
        # Keep the original evidence and attribution; adoption is an application decision.
        with self.store.database.atomic() as db:
            metadata = {**record.metadata, "automatic_adoption": reason}
            db.execute(
                "UPDATE memories SET conversation_id=NULL, metadata_json=? "
                "WHERE id=? AND user_id=?",
                (json.dumps(metadata, ensure_ascii=False), record.id, record.user_id),
            )
            self.review(record.id, record.user_id, ReviewDecision.CONFIRM)

    def _adopt_model_candidates(self, turn: ConversationTurnRecord, direct: str) -> None:
        if UNCERTAIN.search(direct) or SENSITIVE.search(direct):
            return
        for record in self.store.list_memories(
            turn.user_id, {MemoryStatus.CANDIDATE}, scope=turn.scope
        ):
            if (
                record.evidence_turn_ids == [turn.id]
                and record.metadata.get("interpretation_model")
                and record.content in direct
                and "我" in record.content
                and record.confidence >= 0.85
                and record.subject_actor_id in {None, turn.user_id}
                and record.kind in {MemoryKind.PREFERENCE, MemoryKind.SUPPORT_STRATEGY}
                and record.sensitivity is Sensitivity.NORMAL
                and record.reality_layer is RealityLayer.REAL_WORLD
                and record.resolution_status is ResolutionStatus.RESOLVED
                and record.quote_depth == 0
            ):
                self._adopt(record, "validated_literal_model_proposal")

    def _forget_from_chat(self, turn: ConversationTurnRecord, target: str) -> int:
        records = self.store.list_memories(
            turn.user_id, {MemoryStatus.ACTIVE, MemoryStatus.CANDIDATE}, scope=turn.scope
        )
        if target == "@recent":
            previous = [
                item
                for item in self.store.list_turns(turn.user_id, turn.scope)
                if item.scope == turn.scope
                and item.role is ConversationRole.USER
                and item.server_sequence < turn.server_sequence
                and item.deletion_state is TurnDeletionState.ACTIVE
            ]
            previous.sort(key=lambda item: item.server_sequence, reverse=True)
            targets = [r for r in records if previous and previous[0].id in r.evidence_turn_ids]
        else:
            targets = [
                r for r in records if target in r.content or target == r.metadata.get("subject")
            ]
        for record in targets:
            self.forget(record.id, turn.user_id)
        return len(targets)

    def forget(self, memory_id: str, user_id: str) -> MemoryRecord:
        with self.store.database.atomic() as db:
            current = self.store.get(memory_id, user_id)
            versions = [current]
            if current.stable_key:
                versions = [
                    record
                    for record in self.store.list_memories(user_id)
                    if record.stable_key == current.stable_key
                    and record.scope == current.scope
                    and record.kind == current.kind
                    and record.reality_layer == current.reality_layer
                    and record.subject_actor_id == current.subject_actor_id
                    and record.predicate == current.predicate
                ]
            source_ids: set[str] = set()
            for record in versions:
                if record.status is MemoryStatus.FORGOTTEN:
                    continue
                super().forget(record.id, user_id)
                source_ids.update(record.evidence_turn_ids)
                # A recalled fact can have been repeated in another conversation.
                # The saved response plan records this even without recent-turn dependencies.
                source_ids.update(
                    str(row[0])
                    for row in db.execute(
                        "SELECT DISTINCT t.id FROM response_plans p "
                        "JOIN json_each(p.memory_use_plan_json, '$.decisions') d "
                        "JOIN conversation_turns t ON t.user_id=p.user_id "
                        "AND t.reply_to_turn_id=p.trigger_turn_id AND t.role='assistant' "
                        "WHERE p.user_id=? AND json_extract(d.value, '$.evidence.kind')='memory' "
                        "AND json_extract(d.value, '$.evidence.id')=? "
                        "AND json_extract(d.value, '$.mode') NOT IN ('suppress', 'clarify')",
                        (user_id, record.id),
                    )
                )
            turns = self.store.list_turns(user_id)
            for turn in sorted(turns, key=lambda item: item.server_sequence):
                if turn.role is ConversationRole.ASSISTANT and (
                    turn.reply_to_turn_id in source_ids
                    or source_ids.intersection(turn.metadata.get("context_turn_ids", []))
                ):
                    source_ids.add(turn.id)
            # Apply explicit restrictions to all derived replies as well: they can be
            # retrieved independently, outside the recent-conversation filter.
            feedback_scope = current.scope.model_copy(update={"conversation_id": None})
            for source_id in source_ids:
                try:
                    source = self.store.get_turn(source_id, user_id)
                except KeyError:
                    continue
                if (
                    source.scope.companion_id != feedback_scope.companion_id
                    or source.scope.relationship_id != feedback_scope.relationship_id
                    or source.scope.group_id != feedback_scope.group_id
                ):
                    continue
                self.record_reference_feedback(
                    MemoryReferenceFeedbackInput(
                        user_id=user_id,
                        scope=feedback_scope,
                        evidence_kind=ExperienceEvidenceKind.TURN,
                        evidence_id=source_id,
                        kind=ReferenceFeedbackKind.DO_NOT_REFERENCE,
                        note="user_requested_memory_forgetting",
                    )
                )
            return self.store.get(memory_id, user_id)

    def index_active(self, user_id: str, scope: object) -> None:
        from companion_memoryos.schemas import MemoryScope

        assert isinstance(scope, MemoryScope)
        index = SQLiteSemanticIndex(self.store.database)
        for record in self.store.list_memories(user_id, {MemoryStatus.ACTIVE}, scope=scope):
            digest = hashlib.sha256(record.content.encode()).hexdigest()
            with self.store.database.connection() as db:
                cached = db.execute(
                    "SELECT digest FROM agent_embedding_cache WHERE id=? AND space=?",
                    (record.id, self.embeddings.space),
                ).fetchone()
            if cached and cached["digest"] == digest:
                continue
            vector = self.embeddings.encode(record.content)
            index.upsert(
                SemanticDocument(
                    SemanticKind.MEMORY,
                    record.id,
                    user_id,
                    record.scope,
                    self.embeddings.space,
                    vector,
                )
            )
            with self.store.database.connection() as db:
                db.execute(
                    "INSERT OR REPLACE INTO agent_embedding_cache VALUES (?, ?, ?)",
                    (record.id, self.embeddings.space, digest),
                )
