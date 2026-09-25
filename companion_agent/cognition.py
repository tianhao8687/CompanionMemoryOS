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
from dataclasses import replace
from datetime import datetime
from itertools import pairwise
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, model_validator

from companion_agent.communication import communication_preferences
from companion_agent.deepseek import DeepSeekConfig
from companion_agent.directives import remember_directive
from companion_agent.evidence_policy import filter_recent_turns, filter_superseded_context
from companion_agent.memory_language import (
    SENSITIVE,
    LiteralMemory,
    forget_target,
    literal_memories,
    memory_note,
    shared_material,
    supported_literal,
)
from companion_agent.persona.models import PersonaModel
from companion_agent.relationship.models import RelationshipKey
from companion_memoryos.config import InterpreterConfig
from companion_memoryos.diagnostics import model_call
from companion_memoryos.interpreter import OpenAICompatibleInterpreter
from companion_memoryos.schemas import (
    AnswerCardinality,
    ConsentState,
    ConversationRole,
    ConversationTurnRecord,
    ExperienceEvidenceKind,
    MemoryInput,
    MemoryKind,
    MemoryRecord,
    MemoryReferenceFeedbackInput,
    MemoryScope,
    MemoryStatus,
    MemoryUsePlan,
    ProcessTurnRequest,
    ProcessTurnResult,
    RealityLayer,
    RecallRequest,
    ReferenceFeedbackKind,
    ResolutionStatus,
    ReviewDecision,
    Sensitivity,
    TurnDeletionState,
    TurnRecallItem,
)
from companion_memoryos.semantic_index import (
    SemanticDocument,
    SemanticKind,
    SQLiteSemanticIndex,
)
from companion_memoryos.service import CompanionMemoryService
from companion_memoryos.temporal import TemporalHint


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
        config = self.settings.embedding
        with model_call(
            "embedding",
            {"model": config.model, "input": text, "space": self.space},
            live=urlsplit(config.base_url).hostname not in {"127.0.0.1", "::1", "localhost"},
        ) as call:
            vector = self._encode_api(text)
            call["vector_dimensions"] = len(vector)
            return vector

    def _encode_api(self, text: str) -> list[float]:
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
    on_memory_changed: Callable[[], None] | None = None

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
                max_output_tokens=min(model.max_tokens, 4096),
                timeout_seconds=model.timeout_seconds,
                thinking=(
                    "disabled"
                    if model.model not in {"deepseek-chat", "deepseek-reasoner"}
                    else None
                ),
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
                    from companion_agent.memory_lifecycle import (
                        reconcile_open_loops,
                        reconcile_preference_correction,
                    )

                    reconciled = reconcile_open_loops(self, turn, direct)
                    if reconciled:
                        actions["updated_open_loops"] = reconciled
                    target = forget_target(direct)
                    if target is not None:
                        actions["forgotten"] = self._forget_from_chat(turn, target)
                    learned = (
                        literal_memories(direct)
                        if self.learning.extract_memory
                        and turn.sensitivity is Sensitivity.NORMAL
                        and target is None
                        else []
                    )
                    note = memory_note(direct)
                    # A structured preference already retains the full assertion. Avoid
                    # a second free-text copy that could keep a superseded value alive.
                    preference_note = len(learned) == 1 and note == learned[0].content
                    if (
                        target is None
                        and not preference_note
                        and remember_directive(self, turn, request.calendar_timezone)
                    ):
                        actions["learned"] = actions.get("learned", 0) + 1
                    for fact in learned:
                        fact = self._resolve_favorite(fact, turn, direct)
                        stable_key = (
                            "natural:"
                            + hashlib.sha256(
                                (
                                    fact.subject
                                    + (
                                        ":" + fact.behavior.lifetime
                                        if fact.behavior and fact.behavior.lifetime != "durable"
                                        else ""
                                    )
                                ).encode()
                            ).hexdigest()[:24]
                        )
                        decision = self.remember(
                            MemoryInput(
                                user_id=turn.user_id,
                                scope=turn.scope.model_copy(
                                    update={
                                        "conversation_id": (
                                            turn.scope.conversation_id
                                            if fact.behavior
                                            and fact.behavior.lifetime in {"turn", "conversation"}
                                            else None
                                        )
                                    }
                                ),
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
                                valid_time_end=fact.behavior.valid_until(
                                    turn.occurred_at, request.calendar_timezone
                                )
                                if fact.behavior
                                else None,
                                metadata={
                                    "extractor": "bounded-local-v2",
                                    "reflection": fact.reflection,
                                    "subject": fact.subject,
                                    "favorite": fact.favorite,
                                    "preference_category": fact.category,
                                    "preference_value": fact.value,
                                    "behavior_lifetime": fact.behavior.lifetime
                                    if fact.behavior
                                    else None,
                                },
                            )
                        )
                        if decision.memory:
                            record = decision.memory
                            if record.status is MemoryStatus.CANDIDATE:
                                self._adopt(
                                    record,
                                    "literal_user_statement",
                                    promote=not (
                                        fact.behavior
                                        and fact.behavior.lifetime in {"turn", "conversation"}
                                    ),
                                )
                            actions["learned"] = actions.get("learned", 0) + 1
                    if self.learning.extract_memory and target is None:
                        corrected = reconcile_preference_correction(self, turn, direct)
                        if corrected:
                            actions["corrected"] = corrected
                        adopted = self._adopt_model_candidates(turn, direct)
                        if adopted:
                            actions["learned"] = actions.get("learned", 0) + adopted
                        if turn.sensitivity is Sensitivity.NORMAL and shared_material(turn.content):
                            decision = self.remember(
                                MemoryInput(
                                    user_id=turn.user_id,
                                    scope=turn.scope.model_copy(update={"conversation_id": None}),
                                    kind=MemoryKind.SHARED_MOMENT,
                                    title="分享过的原文（引文人物不代表用户）",
                                    content=turn.content,
                                    consent=turn.consent,
                                    sensitivity=turn.sensitivity,
                                    evidence_turn_ids=[turn.id],
                                    source_ref=f"turn:{turn.id}",
                                    event_at=turn.occurred_at,
                                    metadata={"quoted_material_reference": True},
                                )
                            )
                            if decision.memory:
                                self._adopt(decision.memory, "attributed_shared_material")
                                actions["learned"] = actions.get("learned", 0) + 1
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
            include_turn_evidence=True,
            include_relationship_turns=bool(
                request.scope.companion_id and request.scope.relationship_id
            ),
            answer_cardinality=AnswerCardinality.OPEN,
            limit=4,
            turn_limit=6,
            max_tokens=2500,
            max_characters=12000,
        )
        if self.embeddings.backend != "off":
            try:
                self.index_active(request.user_id, request.scope)
                self.index_turns(request.user_id, request.scope, recall.as_of)
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

    def _resolve_favorite(
        self, fact: LiteralMemory, turn: ConversationTurnRecord, direct: str
    ) -> LiteralMemory:
        if (
            not fact.favorite
            or fact.category
            or not any(cue in direct for cue in ("更新", "更正", "改", "以前", "旧", "现在"))
        ):
            return fact
        # Resolve "my favourite is now ..." by the explicitly named old value,
        # never by replacing every preference or guessing a domain from a new noun.
        candidates = [
            record
            for record in self.store.list_memories(
                turn.user_id, {MemoryStatus.ACTIVE}, scope=turn.scope
            )
            if record.metadata.get("favorite")
            and record.metadata.get("preference_category")
            and isinstance(record.metadata.get("preference_value"), str)
            and record.metadata["preference_value"] != fact.value
            and record.metadata["preference_value"] in direct
            and record.subject_actor_id in {None, turn.user_id}
        ]
        if len(candidates) != 1:
            return fact
        category = str(candidates[0].metadata["preference_category"])
        return replace(fact, subject=f"favorite:{category}", category=category)

    def _recall_turns(
        self,
        request: RecallRequest,
        temporal_hint: TemporalHint,
        fts_query: str,
        event_after: datetime | None,
        event_before: datetime | None,
        turn_limit: int,
        has_cues: bool,
    ) -> list[TurnRecallItem]:
        if not turn_limit:
            return []
        items = super()._recall_turns(
            request,
            temporal_hint,
            fts_query,
            event_after,
            event_before,
            self.config.retrieval.turn_candidate_pool,
            has_cues,
        )
        from companion_agent.recall_completion import complete_candidates, dialogue_replies

        items = complete_candidates(self, request, temporal_hint, items)
        # Apply the same source/dependency restrictions as recent conversation.
        # A forgotten fact's later acknowledgement is not independent new evidence.
        key = RelationshipKey(
            user_id=request.user_id,
            companion_id=request.scope.companion_id or "",
            relationship_id=request.scope.relationship_id or "",
        )
        eligible = filter_recent_turns(
            self, key, [item.turn for item in items], MemoryUsePlan(), request.as_of
        )
        if not re.search(r"以前|曾经|最初|原来|改过|变过|变化|历史", request.query):
            eligible = filter_superseded_context(self, key, request.scope, eligible)
            # A current, explicitly versioned favourite already has a complete
            # structured value. Its correction's quoted old answer adds no detail
            # to this slot and can otherwise reintroduce the superseded value.
            covered_favorites = {
                source
                for record in self.store.list_memories(
                    request.user_id, {MemoryStatus.ACTIVE}, scope=request.scope
                )
                if record.metadata.get("favorite")
                and record.metadata.get("preference_category")
                and str(record.metadata["preference_category"]) in request.query
                and re.search(r"最喜欢|最爱", request.query)
                for source in record.evidence_turn_ids
            }
            eligible = [item for item in eligible if item.id not in covered_favorites]
        allowed = {turn.id for turn in eligible if turn.role is ConversationRole.USER}
        retained = [item for item in items if item.turn.id in allowed]
        from companion_agent.memory_lifecycle import has_dated_plan, is_planning_overview

        if is_planning_overview(request.query):
            # Prior appointments matter more than moods that happen to resemble
            # wanting an easy weekend. Original evidence and scores stay visible.
            for item in retained:
                if has_dated_plan(self._direct_user_discourse_text(item.turn)):
                    item.reasons.append("dated_plan_for_overview")
            retained.sort(key=lambda item: "dated_plan_for_overview" not in item.reasons)
        selected = retained[:turn_limit]
        replies = dialogue_replies(self, request, temporal_hint, selected)
        reply_sources = (
            filter_recent_turns(
                self, key, [item.turn for item in replies], MemoryUsePlan(), request.as_of
            )
            if replies
            else []
        )
        allowed_replies = {turn.id for turn in reply_sources}
        # Stay in the requested evidence limit. Actual assistant words retain
        # their role and normal use-plan validation; they are not user facts.
        for reply in replies:
            if reply.turn.id in allowed_replies:
                selected.insert(min(1, len(selected)), reply)
        return selected[:turn_limit]

    def _adopt(self, record: MemoryRecord, reason: str, *, promote: bool = True) -> None:
        # Keep the original evidence and attribution; adoption is an application decision.
        with self.store.database.atomic() as db:
            metadata = {**record.metadata, "automatic_adoption": reason}
            db.execute(
                "UPDATE memories SET conversation_id=?, metadata_json=? WHERE id=? AND user_id=?",
                (
                    None if promote else record.scope.conversation_id,
                    json.dumps(metadata, ensure_ascii=False),
                    record.id,
                    record.user_id,
                ),
            )
            self.review(record.id, record.user_id, ReviewDecision.CONFIRM)

    def _adopt_model_candidates(self, turn: ConversationTurnRecord, direct: str) -> int:
        if SENSITIVE.search(direct):
            return 0
        adopted = 0
        active_from_turn = [
            record
            for record in self.store.list_memories(
                turn.user_id, {MemoryStatus.ACTIVE}, scope=turn.scope
            )
            if record.evidence_turn_ids == [turn.id]
        ]
        for record in self.store.list_memories(
            turn.user_id, {MemoryStatus.CANDIDATE}, scope=turn.scope
        ):
            # The local projection already owns temporary communication requests.
            # Another classification must not turn a pause into a lasting rule.
            if any(
                setting.lifetime != "durable" and setting.original in record.content
                for setting in communication_preferences(direct)
            ):
                continue
            if (
                record.evidence_turn_ids == [turn.id]
                and record.metadata.get("interpretation_model")
                and supported_literal(record.content, memory_note(direct) or direct)
                and supported_literal(record.content, memory_note(turn.content) or turn.content)
                and record.confidence >= 0.85
                and (
                    record.subject_actor_id in {None, turn.user_id}
                    or record.kind is MemoryKind.SHARED_MOMENT
                    or any(
                        entity.id == record.subject_actor_id
                        and any(
                            name and name in record.content
                            for name in [entity.name, *entity.aliases]
                        )
                        for entity in record.entities
                    )
                )
                and record.kind
                in {
                    MemoryKind.PREFERENCE,
                    MemoryKind.SUPPORT_STRATEGY,
                    MemoryKind.SHARED_MOMENT,
                    MemoryKind.IDENTITY,
                    MemoryKind.RITUAL,
                }
                and record.sensitivity is Sensitivity.NORMAL
                and record.reality_layer is RealityLayer.REAL_WORLD
                and record.resolution_status is ResolutionStatus.RESOLVED
                and record.quote_depth == 0
                # Keep one version chain for an assertion already learned locally.
                # A second model copy with a different predicate can outlive updates.
                and not any(
                    record.content.strip("。.!！ \n") in active.content
                    or (
                        record.kind is MemoryKind.PREFERENCE
                        and active.kind is MemoryKind.PREFERENCE
                        and active.content in record.content
                    )
                    for active in active_from_turn
                )
            ):
                self._adopt(record, "validated_literal_model_proposal")
                adopted += 1
                active_from_turn.append(record)
        return adopted

    def _forget_from_chat(self, turn: ConversationTurnRecord, target: str) -> int:
        if target.startswith("@location:"):
            from companion_agent.memory_redaction import forget_location

            count = forget_location(self, turn, target.removeprefix("@location:"))
            self._hide_forgetting_request(turn)
            return count

        def matches(content: str) -> bool:
            return target in content

        records = self.store.list_memories(
            turn.user_id, {MemoryStatus.ACTIVE, MemoryStatus.CANDIDATE}, scope=turn.scope
        )
        recent_source: str | None = None
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
            recent_source = previous[0].id if previous else None
            targets = [r for r in records if previous and previous[0].id in r.evidence_turn_ids]
        else:
            targets = [
                r for r in records if matches(r.content) or target == r.metadata.get("subject")
            ]
        for record in targets:
            self.forget(record.id, turn.user_id)
        # Raw evidence still exists when extraction failed. Forget its source and
        # derived replies too; otherwise newly enabled turn retrieval revives it.
        source_ids = {source for record in targets for source in record.evidence_turn_ids}
        if recent_source is not None:
            source_ids.add(recent_source)
        turns = self.store.list_turns(turn.user_id)
        for source in sorted(turns, key=lambda item: item.server_sequence):
            if (
                source.scope.companion_id != turn.scope.companion_id
                or source.scope.relationship_id != turn.scope.relationship_id
                or source.scope.group_id != turn.scope.group_id
                or source.server_sequence >= turn.server_sequence
                or source.deletion_state is not TurnDeletionState.ACTIVE
            ):
                continue
            if (
                target != "@recent"
                and source.role is ConversationRole.USER
                and matches(source.content)
            ):
                source_ids.add(source.id)
            if source.role is ConversationRole.ASSISTANT and (
                source.reply_to_turn_id in source_ids
                or source_ids.intersection(source.metadata.get("context_turn_ids", []))
            ):
                source_ids.add(source.id)
            if source.id in source_ids:
                self.forget_turn(source.id, turn.user_id)
        if source_ids and self.on_memory_changed:
            self.on_memory_changed()
        # The forgetting request itself can repeat the private fact. It must not
        # become a fresh route for recalling the same text on a later turn.
        self._hide_forgetting_request(turn)
        return len(targets) + len(source_ids)

    def _hide_forgetting_request(self, turn: ConversationTurnRecord) -> None:
        self.record_reference_feedback(
            MemoryReferenceFeedbackInput(
                user_id=turn.user_id,
                scope=turn.scope.model_copy(update={"conversation_id": None}),
                evidence_kind=ExperienceEvidenceKind.TURN,
                evidence_id=turn.id,
                kind=ReferenceFeedbackKind.DO_NOT_REFERENCE,
                note="memory_forgetting_request",
            )
        )

    def forget(self, memory_id: str, user_id: str) -> MemoryRecord:
        if self.on_memory_changed:
            self.on_memory_changed()
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
        with self.store.database.connection() as db:
            cached = {
                row["id"]: row["digest"]
                for row in db.execute(
                    "SELECT id, digest FROM agent_embedding_cache WHERE space=?",
                    (self.embeddings.space,),
                )
            }
        for record in self.store.list_memories(user_id, {MemoryStatus.ACTIVE}, scope=scope):
            digest = hashlib.sha256(record.content.encode()).hexdigest()
            if cached.get(record.id) == digest:
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

    def index_turns(self, user_id: str, scope: MemoryScope, as_of: datetime) -> None:
        """Index original user evidence, independently of successful fact extraction.

        Backfill is bounded per chat. Retrieval rechecks scope, consent, realm and
        source restrictions; an embedding is never authority to assert a fact.
        """
        if not scope.companion_id or not scope.relationship_id:
            return
        domain = scope.model_copy(update={"conversation_id": None})
        with self.store.database.connection() as db:
            cached = {
                row["id"]: row["digest"]
                for row in db.execute(
                    "SELECT c.id, c.digest FROM agent_embedding_cache c JOIN turn_embeddings e "
                    "ON e.turn_id=c.id AND e.space=c.space WHERE c.space=?",
                    (self.embeddings.space,),
                )
            }
        turns = [
            turn
            for turn in self.store.list_turns(user_id, domain)
            if turn.role is ConversationRole.USER
            and turn.scope.group_id == scope.group_id
            and cached.get(turn.id) != hashlib.sha256(turn.content[:16000].encode()).hexdigest()
        ]
        turns = filter_recent_turns(
            self,
            RelationshipKey(
                user_id=user_id,
                companion_id=scope.companion_id,
                relationship_id=scope.relationship_id,
            ),
            turns,
            MemoryUsePlan(),
            as_of,
        )
        index = SQLiteSemanticIndex(self.store.database)
        for turn in turns[:32]:
            text = turn.content[:16000]
            digest = hashlib.sha256(text.encode()).hexdigest()
            vector = self.embeddings.encode(text)
            index.upsert(
                SemanticDocument(
                    SemanticKind.TURN, turn.id, user_id, turn.scope, self.embeddings.space, vector
                )
            )
            with self.store.database.connection() as db:
                db.execute(
                    "INSERT OR REPLACE INTO agent_embedding_cache VALUES (?, ?, ?)",
                    (turn.id, self.embeddings.space, digest),
                )
