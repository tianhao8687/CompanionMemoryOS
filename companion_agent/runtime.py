"""MemoryOS -> persona -> Main LLM -> durable assistant turn and use ledger."""

from __future__ import annotations

import hashlib
import json
import logging
from contextlib import suppress
from threading import RLock
from typing import Any

from pydantic import Field

from companion_agent.character_memory import CharacterMemoryStore
from companion_agent.context import ComposedContext, compose_context
from companion_agent.current_state import CurrentStateConfig, CurrentStateService
from companion_agent.current_state.compiler import CurrentStateBudgetError, compile_current_state
from companion_agent.current_state.evaluator import analyze_current_turn
from companion_agent.current_state.models import CurrentStateAnalysis, StatePreparation
from companion_agent.current_state.service import choose_response_goal
from companion_agent.evidence_policy import filter_recent_turns
from companion_agent.experience import ExperienceConfig
from companion_agent.experience.compiler import compile_experience_context
from companion_agent.experience.evaluator import is_recall_question
from companion_agent.llm import MainLLM
from companion_agent.persona import PersonaDefinition, RelationshipStage, compile_persona_context
from companion_agent.persona.models import PersonaModel
from companion_agent.relationship import RelationshipConfig, RelationshipKey, RelationshipService
from companion_agent.relationship.evaluator import LocalRelationshipEvaluator, RelationshipEvaluator
from companion_agent.relationship.models import (
    RelationshipDynamics,
    RelationshipUpdateCandidate,
    RelationshipUpdateKind,
    now_utc,
)
from companion_agent.semantics import RelationshipDistance, RelationshipIdentityType
from companion_memoryos.schemas import (
    ConsentState,
    ConversationRole,
    ConversationTurnInput,
    ConversationTurnRecord,
    ExperienceEvidenceKind,
    MemoryReferenceMode,
    ProcessTurnRequest,
    RealityLayer,
    ResponseBeatSentRequest,
    ResponseGoal,
    ResponsePlanRecord,
    ResponsePlanRequest,
    ResponsePlanStatus,
    Sensitivity,
    TurnDeletionState,
)
from companion_memoryos.service import CompanionMemoryService
from companion_memoryos.turn_layers import turn_reality_layer

logger = logging.getLogger(__name__)


class PreparedResponse(PersonaModel):
    context: ComposedContext
    plan: ResponsePlanRecord
    user_turn: ConversationTurnRecord
    relationship_key: RelationshipKey
    relationship_revision: int
    relationship_candidates: list[RelationshipUpdateCandidate]
    context_turn_ids: list[str] = Field(default_factory=list)


class AgentResponse(PersonaModel):
    turn: ConversationTurnRecord
    reused: bool = False


class CompanionAgent:
    def __init__(
        self,
        memory: CompanionMemoryService,
        persona: PersonaDefinition,
        main_llm: MainLLM | None = None,
        *,
        max_persona_tokens: int = 1200,
        max_context_tokens: int = 16000,
        recent_turn_limit: int = 20,
        application_rules: str = "",
        relationship_config: RelationshipConfig | None = None,
        relationship_evaluator: RelationshipEvaluator | None = None,
        experience_config: ExperienceConfig | None = None,
        initial_relationship_identity: RelationshipIdentityType | None = None,
        current_state_config: CurrentStateConfig | None = None,
    ) -> None:
        if min(max_persona_tokens, max_context_tokens, recent_turn_limit) < 1:
            raise ValueError("agent budgets and history limit must be positive")
        self.memory = memory
        self.persona = persona.model_copy(deep=True)
        self.main_llm = main_llm
        self.max_persona_tokens = max_persona_tokens
        self.max_context_tokens = max_context_tokens
        self.recent_turn_limit = recent_turn_limit
        self.application_rules = application_rules
        self.characters = CharacterMemoryStore(memory.store.database)
        self.relationships = RelationshipService(memory, relationship_config)
        self.relationship_evaluator = relationship_evaluator or LocalRelationshipEvaluator()
        self.experiences = self.relationships.experiences
        if experience_config is not None:
            self.experiences.config = experience_config
        self.initial_relationship_identity = initial_relationship_identity
        self.current_state_config = current_state_config or CurrentStateConfig()
        self.current_states: CurrentStateService | None = None
        if self.current_state_config.enabled:
            try:
                self.current_states = CurrentStateService(
                    memory, self.relationships, self.current_state_config
                )
            except Exception:
                logger.warning("current_state_initialization_unavailable")
        self._lock = RLock()

    def prepare(
        self,
        request: ProcessTurnRequest,
        relationship_stage: RelationshipStage | None = None,
        *,
        response_goal: ResponseGoal | None = None,
    ) -> PreparedResponse:
        if (
            request.role is not ConversationRole.USER
            or request.actor_id != request.user_id
            or not request.scope.companion_id
            or request.scope.companion_id == request.user_id
            or request.scope.group_id is not None
        ):
            raise ValueError("agent requires distinct user and companion actors")
        if request.consent is not ConsentState.GRANTED:
            raise ValueError("agent conversation storage requires consent")
        if self.initial_relationship_identity is not None:
            initial_key = RelationshipKey(
                user_id=request.user_id,
                companion_id=request.scope.companion_id,
                relationship_id=request.scope.relationship_id or "",
            )
            if not self.relationships.get_relationship(initial_key).identity.confirmed_by_user:
                self.relationships.initialize_identity(
                    initial_key, self.initial_relationship_identity
                )
        self.characters.install(self.persona, request.scope.companion_id)
        result = self.memory.process_turn(request)
        turn = result.storage.turn
        if turn is None or result.response_stale:
            raise ValueError("user turn unavailable or superseded")
        relationship_key = RelationshipKey(
            user_id=request.user_id,
            companion_id=request.scope.companion_id,
            relationship_id=request.scope.relationship_id or "",
        )
        state_preparation = StatePreparation(analysis=CurrentStateAnalysis())
        if self.current_state_config.enabled:
            try:
                if self.current_states is None:
                    raise ValueError("current_state_service_unavailable")
                state_preparation = self.current_states.process(request, result)
            except Exception:
                logger.warning("current_state_preparation_unavailable")
                state_preparation = StatePreparation(
                    analysis=analyze_current_turn(
                        self.memory._direct_user_discourse_text(turn), result
                    )
                    if self.relationships.evidence_valid(
                        relationship_key, f"turn:{turn.id}", now_utc()
                    )
                    else CurrentStateAnalysis(),
                    degraded=True,
                )
        discourse = result.discourse
        goal = response_goal or (discourse.suggested_goal if discourse else None)
        if goal is None and result.response_context is not None:
            with suppress(ValueError):
                goal = ResponseGoal(result.response_context.intent.value)
        goal = goal or ResponseGoal.DIRECT_ANSWER
        base_goal = goal
        if self.current_state_config.enabled:
            goal = choose_response_goal(base_goal, state_preparation, host_goal=response_goal)

        def make_plan(chosen_goal: ResponseGoal) -> ResponsePlanRecord:
            return self.memory.plan_response(
                ResponsePlanRequest(
                    user_id=request.user_id,
                    scope=request.scope,
                    trigger_turn_id=turn.id,
                    goal=chosen_goal,
                    user_asked_memory_question=bool(
                        discourse and discourse.user_asked_memory_question
                    ),
                    current_turn_requires_full_attention=(
                        state_preparation.analysis.explicit_goal is ResponseGoal.LISTEN
                        or (
                            not state_preparation.analysis.concrete_task
                            and any(
                                r.slot == "communication:need" and r.value == "listen"
                                for r in state_preparation.records
                            )
                        )
                    ),
                    channel_supports_multiple_beats=False,
                    allow_afterthought=False,
                    allow_follow_up=False,
                ),
                prepared_context=result.response_context,
            )

        plan = make_plan(goal)
        if (
            self.current_states is not None
            and not state_preparation.degraded
            and request.reality_layer is RealityLayer.REAL_WORLD
        ):
            try:
                state_preparation = self.current_states.refresh(
                    relationship_key,
                    request.scope.conversation_id or "",
                    state_preparation,
                    memory_use_plan=plan.memory_use_plan,
                    allow_sensitive=request.allow_sensitive_model_input,
                )
            except Exception:
                logger.warning("current_state_policy_refresh_unavailable")
                state_preparation = StatePreparation(
                    analysis=state_preparation.analysis, degraded=True
                )
            filtered_goal = choose_response_goal(
                base_goal, state_preparation, host_goal=response_goal
            )
            if filtered_goal is not goal:
                self.memory.cancel_response_plan(
                    plan.id, request.user_id, "current_state_policy_changed_goal"
                )
                goal = filtered_goal
                plan = make_plan(goal)
        recent = [
            item
            for item in self.memory.list_turns(request.user_id, request.scope)
            if item.scope == request.scope
            and item.server_sequence < turn.server_sequence
            and item.occurred_at <= turn.occurred_at
            and item.deletion_state is TurnDeletionState.ACTIVE
            and item.consent is ConsentState.GRANTED
            and (request.allow_sensitive_model_input or item.sensitivity is Sensitivity.NORMAL)
            and turn_reality_layer(
                item.content,
                json.dumps(item.metadata),
                json.dumps([span.model_dump(mode="json") for span in item.speech_spans]),
            )
            == request.reality_layer.value
        ]
        recent = filter_recent_turns(
            self.memory,
            relationship_key,
            recent,
            plan.memory_use_plan,
            now_utc(),
            allow_sensitive=request.allow_sensitive_model_input,
        )
        recent = list(reversed(recent[: self.recent_turn_limit]))
        characters = self.characters.recall(
            self.persona.persona_id,
            self.persona.version,
            request.scope.companion_id,
            request.content,
        )
        try:
            relationship_key = RelationshipKey(
                user_id=request.user_id,
                companion_id=request.scope.companion_id,
                relationship_id=request.scope.relationship_id or "",
            )
            relationship = self.relationships.get_relationship(
                relationship_key, as_of=turn.occurred_at
            )
            if type(self.relationship_evaluator) is LocalRelationshipEvaluator:
                candidates = self.relationship_evaluator.evaluate(
                    result,
                    relationship,
                    self.relationships,
                    include_current_interaction=not self.current_state_config.enabled
                    or state_preparation.degraded,
                )
            else:
                candidates = self.relationship_evaluator.evaluate(
                    result, relationship, self.relationships
                )
            if self.current_state_config.enabled and not state_preparation.degraded:
                candidates = [
                    candidate
                    for candidate in candidates
                    if not (
                        (
                            candidate.kind is RelationshipUpdateKind.DYNAMICS
                            and (
                                candidate.proposed_change.get("active_topics") == ["本轮倾诉"]
                                or "recent_conflict_level" in candidate.proposed_change
                                or candidate.proposed_change.get("interaction_tone")
                                in {"tense", "repairing"}
                            )
                        )
                        or (
                            candidate.kind is RelationshipUpdateKind.THREAD
                            and candidate.proposed_change.get("id") == "relationship-conflict"
                        )
                    )
                ]
            self.relationships.stage_candidates(relationship_key, candidates)
            preview = self.relationships.preview(
                relationship_key, candidates, as_of=turn.occurred_at
            )
            if self.current_state_config.enabled and preview.recent_dynamics.active_topics == [
                "本轮倾诉"
            ]:
                preview.recent_dynamics = RelationshipDynamics(
                    updated_at=preview.recent_dynamics.updated_at
                )
            effective_stage = preview.stage
            compiled_relationship = self.relationships.get_relationship_context(
                relationship_key,
                goal,
                request.content,
                model=preview,
                memory_use_plan=plan.memory_use_plan,
                as_of=turn.occurred_at,
                allow_sensitive=request.allow_sensitive_model_input,
            )
            distance_order = [
                RelationshipDistance.OPEN,
                RelationshipDistance.CAUTIOUS,
                RelationshipDistance.RESERVED,
            ]
            distance = compiled_relationship.relationship_distance
            if relationship_stage is not None:
                override = {
                    RelationshipStage.NEW: RelationshipDistance.RESERVED,
                    RelationshipStage.FAMILIAR: RelationshipDistance.CAUTIOUS,
                    RelationshipStage.ESTABLISHED: RelationshipDistance.OPEN,
                }[relationship_stage]
                distance = max([distance, override], key=distance_order.index)
            compiled_relationship.relationship_distance = distance
            relationship_payload = json.loads(compiled_relationship.text)
            relationship_payload["relationship_distance"] = distance.value
            compiled_relationship.text = json.dumps(
                relationship_payload, ensure_ascii=False, separators=(",", ":")
            )
            compiled_relationship.estimated_tokens = self.memory.token_counter.count(
                compiled_relationship.text
            )
            if (
                compiled_relationship.estimated_tokens
                > self.relationships.config.max_relationship_tokens
            ):
                raise ValueError("relationship distance context exceeds budget")
            compiled = compile_persona_context(
                self.persona,
                goal,
                effective_stage,
                max_persona_tokens=self.max_persona_tokens,
                token_counter=self.memory.token_counter,
                relationship_identity=compiled_relationship.identity.type,
                relationship_distance=distance,
            )
            recalled_experiences = (
                self.experiences.recall(
                    relationship_key,
                    request.content,
                    memory_use_plan=plan.memory_use_plan,
                    allow_sensitive=request.allow_sensitive_model_input,
                    explicit_recall=bool(discourse and discourse.user_asked_memory_question)
                    or is_recall_question(request.content),
                    calendar_timezone=request.calendar_timezone,
                    as_of=turn.occurred_at,
                )
                if request.enable_recall
                else []
            )
            compiled_experiences = compile_experience_context(
                relationship_key,
                recalled_experiences,
                self.memory.token_counter,
                max_tokens=self.experiences.config.max_context_tokens,
            )
            compiled_state = None
            if self.current_state_config.enabled:
                try:
                    compiled_state = compile_current_state(
                        relationship_key,
                        state_preparation,
                        goal,
                        self.memory.token_counter,
                        max_tokens=self.current_state_config.max_context_tokens,
                    )
                except CurrentStateBudgetError:
                    raise
                except Exception:
                    logger.warning("current_state_context_unavailable")
            while True:
                context = compose_context(
                    persona=compiled,
                    user_id=request.user_id,
                    scope=request.scope,
                    current_user_turn=request.content,
                    memory_context=result.response_context,
                    memory_use_plan=plan.memory_use_plan,
                    recent_conversation=recent,
                    character_memories=characters,
                    application_rules=self.application_rules,
                    relationship_context=compiled_relationship,
                    experience_context=compiled_experiences,
                    current_state_context=compiled_state,
                )
                serialized = json.dumps(
                    [m.model_dump() for m in context.messages], ensure_ascii=False
                )
                if self.memory.token_counter.count(serialized) <= self.max_context_tokens:
                    break
                if recent:
                    recent.pop(0)
                elif characters:
                    characters.pop()
                elif compiled_state is not None and not compiled_state.has_explicit_requests:
                    compiled_state = None
                else:
                    raise ValueError(
                        "main context exceeds budget; evidence and rules not truncated"
                    )
        except Exception:
            self.memory.cancel_response_plan(plan.id, request.user_id, "composition_failed")
            raise
        return PreparedResponse(
            context=context,
            plan=plan,
            user_turn=turn,
            relationship_key=relationship_key,
            relationship_revision=relationship.revision,
            relationship_candidates=candidates,
            context_turn_ids=[item.id for item in recent],
        )

    def chat(
        self,
        request: ProcessTurnRequest,
        relationship_stage: RelationshipStage | None = None,
        *,
        response_goal: ResponseGoal | None = None,
        continuation_key: str | None = None,
    ) -> AgentResponse:
        if self.main_llm is None:
            raise ValueError("configure a Main LLM before chatting")
        if request.consent is not ConsentState.GRANTED or request.role is not ConversationRole.USER:
            raise ValueError("agent requires a user turn with storage consent")
        if request.model_consent is not ConsentState.GRANTED or (
            request.sensitivity is not Sensitivity.NORMAL
            and not request.allow_sensitive_model_input
        ):
            raise ValueError("Main LLM input requires model consent")
        delivery_key = request.idempotency_key
        if continuation_key:
            delivery_key += ":continuation:" + continuation_key
        response_key = "agent:" + hashlib.sha256(delivery_key.encode()).hexdigest()
        with self._lock:
            turns = self.memory.list_turns(request.user_id, request.scope)
            for turn in turns:
                if (
                    turn.scope == request.scope
                    and turn.idempotency_key == response_key
                    and turn.role is ConversationRole.ASSISTANT
                ):
                    source = self.memory.store.get_turn(
                        turn.reply_to_turn_id or "", request.user_id
                    )
                    if source.content != request.content or source.actor_id != request.actor_id:
                        raise ValueError("idempotency key reused with different input")
                    if turn.metadata.get("persona_id") != self.persona.persona_id:
                        raise ValueError("idempotency key belongs to another persona")
                    if any(
                        item.deletion_state is not TurnDeletionState.ACTIVE
                        or item.consent is not ConsentState.GRANTED
                        for item in (turn, source)
                    ):
                        raise ValueError("cached conversation no longer available")
                    return AgentResponse(turn=turn, reused=True)
            prepared = self.prepare(request, relationship_stage, response_goal=response_goal)
            try:
                output = self.main_llm.generate(prepared.context.messages)
                compiled = prepared.context.persona
                metadata: dict[str, Any] = {
                    "persona_id": compiled.persona_id,
                    "persona_version": compiled.persona_version,
                    "model": output.model,
                    "response_goal": compiled.response_goal.value,
                    "relationship_stage": compiled.relationship_stage.value,
                    "familiarity_stage": compiled.relationship_stage.value,
                    "relationship_identity": compiled.relationship_identity.value,
                    "relationship_distance": compiled.relationship_distance.value,
                    "compiled_persona_tokens": compiled.estimated_tokens,
                    "agent_version": "0.4.1",
                    "current_state_status": "disabled"
                    if not self.current_state_config.enabled
                    else (
                        "degraded"
                        if prepared.context.current_state is None
                        or prepared.context.current_state.degraded
                        else "ready"
                    ),
                    "current_state_tokens": prepared.context.current_state.estimated_tokens
                    if prepared.context.current_state
                    else 0,
                    "current_state_ids": prepared.context.current_state.state_ids
                    if prepared.context.current_state
                    else [],
                    "context_turn_ids": list(
                        dict.fromkeys(
                            [
                                *prepared.context_turn_ids,
                                *(
                                    prepared.context.current_state.source_turn_ids
                                    if prepared.context.current_state
                                    else []
                                ),
                                *(
                                    ref.split(":", 1)[1]
                                    for ref in (
                                        prepared.context.relationship.evidence_ids
                                        if prepared.context.relationship
                                        else []
                                    )
                                    if ref.startswith(("turn:", "user_correction:"))
                                ),
                            ]
                        )
                    ),
                    "compiled_experience_tokens": prepared.context.experiences.estimated_tokens
                    if prepared.context.experiences
                    else 0,
                    "relationship_revision": prepared.relationship_revision,
                    "relationship_stage_source": "history",
                    "requested_distance_override": relationship_stage.value
                    if relationship_stage
                    else None,
                    "compiled_relationship_tokens": prepared.context.relationship.estimated_tokens
                    if prepared.context.relationship
                    else 0,
                    "process_reality_layer": request.reality_layer.value,
                    "usage": output.usage.model_dump() if output.usage else None,
                }
                # Sending acknowledgment and persistence commit together. A newer user turn,
                # deletion or policy update during generation invalidates the old response.
                with self.memory.store.database.atomic():
                    current = self.memory.store.get_turn(prepared.user_turn.id, request.user_id)
                    if (
                        current.deletion_state is not TurnDeletionState.ACTIVE
                        or current.consent is not ConsentState.GRANTED
                    ):
                        raise ValueError("source turn invalidated during generation")
                    context_sources = [
                        self.memory.store.get_turn(identifier, request.user_id)
                        for identifier in metadata["context_turn_ids"]
                    ]
                    if len(
                        filter_recent_turns(
                            self.memory,
                            prepared.relationship_key,
                            context_sources,
                            prepared.plan.memory_use_plan,
                            now_utc(),
                            allow_sensitive=request.allow_sensitive_model_input,
                        )
                    ) != len(context_sources):
                        raise ValueError("context source invalidated during generation")
                    if any(
                        candidate.scope == request.scope
                        and candidate.role is ConversationRole.USER
                        and candidate.deletion_state is TurnDeletionState.ACTIVE
                        and candidate.server_sequence > current.server_sequence
                        for candidate in self.memory.list_turns(request.user_id, request.scope)
                    ):
                        raise ValueError("newer user turn invalidated this response")
                    for beat in prepared.plan.beats:
                        self.memory.mark_response_beat_sent(
                            prepared.plan.id,
                            beat.id,
                            ResponseBeatSentRequest(
                                user_id=request.user_id,
                                rendered_text=output.text,
                                task_policy_version=prepared.plan.policy_version,
                                silently_used_memory_ids=[
                                    d.evidence.id
                                    for d in prepared.plan.memory_use_plan.decisions
                                    if d.mode is MemoryReferenceMode.SILENT_INFLUENCE
                                    and d.evidence.kind is ExperienceEvidenceKind.MEMORY
                                ],
                            ),
                        )
                    stored = self.memory.append_turn(
                        ConversationTurnInput(
                            user_id=request.user_id,
                            scope=request.scope,
                            actor_id=request.scope.companion_id or "",
                            role=ConversationRole.ASSISTANT,
                            content=output.text,
                            consent=request.consent,
                            sensitivity=request.sensitivity,
                            reply_to_turn_id=prepared.user_turn.id,
                            idempotency_key=response_key,
                            source_ref="companion_agent:main_llm",
                            metadata=metadata,
                        )
                    )
                    if stored.turn is None:
                        raise ValueError("assistant response storage failed")
                    experience_decisions = self.experiences.observe(prepared.user_turn, stored.turn)
                    experience_candidates = self.experiences.relationship_candidates(
                        prepared.relationship_key
                    )
                    relationship_after = self.relationships.commit_candidates(
                        prepared.relationship_key,
                        [*prepared.relationship_candidates, *experience_candidates],
                        expected_revision=prepared.relationship_revision,
                    )
                    metadata["relationship_revision_after"] = relationship_after.revision
                    metadata["experience_decisions"] = [
                        decision.model_dump(mode="json") for decision in experience_decisions
                    ]
                    with self.memory.store.database.connection() as connection:
                        connection.execute(
                            "UPDATE conversation_turns SET metadata_json = ? "
                            "WHERE id = ? AND user_id = ?",
                            (
                                json.dumps(metadata, ensure_ascii=False),
                                stored.turn.id,
                                request.user_id,
                            ),
                        )
                    stored.turn.metadata = dict(metadata)
                logger.info("companion_agent.response %s", json.dumps(metadata, ensure_ascii=False))
                return AgentResponse(turn=stored.turn)
            except Exception:
                plan = self.memory.get_response_plan(prepared.plan.id, request.user_id)
                if plan.status is ResponsePlanStatus.ACTIVE:
                    self.memory.cancel_response_plan(plan.id, request.user_id, "generation_failed")
                raise
