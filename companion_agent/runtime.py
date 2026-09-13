"""MemoryOS -> persona -> Main LLM -> durable assistant turn and use ledger."""

from __future__ import annotations

import hashlib
import json
import logging
from contextlib import suppress
from threading import RLock

from companion_agent.character_memory import CharacterMemoryStore
from companion_agent.context import ComposedContext, compose_context
from companion_agent.llm import MainLLM
from companion_agent.persona import PersonaDefinition, RelationshipStage, compile_persona_context
from companion_agent.persona.models import PersonaModel
from companion_memoryos.schemas import (
    ConsentState,
    ConversationRole,
    ConversationTurnInput,
    ConversationTurnRecord,
    ExperienceEvidenceKind,
    MemoryReferenceMode,
    ProcessTurnRequest,
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
        self._lock = RLock()

    def prepare(
        self,
        request: ProcessTurnRequest,
        relationship_stage: RelationshipStage,
        *,
        response_goal: ResponseGoal | None = None,
    ) -> PreparedResponse:
        if (
            request.role is not ConversationRole.USER
            or request.actor_id != request.user_id
            or not request.scope.companion_id
            or request.scope.companion_id == request.user_id
        ):
            raise ValueError("agent requires distinct user and companion actors")
        if request.consent is not ConsentState.GRANTED:
            raise ValueError("agent conversation storage requires consent")
        self.characters.install(self.persona, request.scope.companion_id)
        result = self.memory.process_turn(request)
        turn = result.storage.turn
        if turn is None or result.response_stale:
            raise ValueError("user turn unavailable or superseded")
        discourse = result.discourse
        goal = response_goal or (discourse.suggested_goal if discourse else None)
        if goal is None and result.response_context is not None:
            with suppress(ValueError):
                goal = ResponseGoal(result.response_context.intent.value)
        goal = goal or ResponseGoal.DIRECT_ANSWER
        compiled = compile_persona_context(
            self.persona,
            goal,
            relationship_stage,
            max_persona_tokens=self.max_persona_tokens,
            token_counter=self.memory.token_counter,
        )
        plan = self.memory.plan_response(
            ResponsePlanRequest(
                user_id=request.user_id,
                scope=request.scope,
                trigger_turn_id=turn.id,
                goal=goal,
                user_asked_memory_question=discourse.user_asked_memory_question
                if discourse
                else False,
                current_turn_requires_full_attention=discourse.current_turn_requires_full_attention
                if discourse
                else False,
                channel_supports_multiple_beats=False,
                allow_afterthought=False,
                # v0.1 renders a single response; proactive follow-ups remain a host capability.
                allow_follow_up=False,
            ),
            prepared_context=result.response_context,
        )
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
        recent = list(reversed(recent[: self.recent_turn_limit]))
        characters = (
            []
            if (discourse and discourse.current_turn_requires_full_attention)
            else (
                self.characters.recall(
                    self.persona.persona_id,
                    self.persona.version,
                    request.scope.companion_id,
                    request.content,
                )
            )
        )
        try:
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
                else:
                    raise ValueError(
                        "main context exceeds budget; evidence and rules not truncated"
                    )
        except Exception:
            self.memory.cancel_response_plan(plan.id, request.user_id, "composition_failed")
            raise
        return PreparedResponse(context=context, plan=plan, user_turn=turn)

    def chat(
        self,
        request: ProcessTurnRequest,
        relationship_stage: RelationshipStage,
        *,
        response_goal: ResponseGoal | None = None,
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
        response_key = "agent:" + hashlib.sha256(request.idempotency_key.encode()).hexdigest()
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
                metadata = {
                    "persona_id": compiled.persona_id,
                    "persona_version": compiled.persona_version,
                    "model": output.model,
                    "response_goal": compiled.response_goal.value,
                    "relationship_stage": compiled.relationship_stage.value,
                    "compiled_persona_tokens": compiled.estimated_tokens,
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
                logger.info("companion_agent.response %s", json.dumps(metadata, ensure_ascii=False))
                return AgentResponse(turn=stored.turn)
            except Exception:
                plan = self.memory.get_response_plan(prepared.plan.id, request.user_id)
                if plan.status is ResponsePlanStatus.ACTIVE:
                    self.memory.cancel_response_plan(plan.id, request.user_id, "generation_failed")
                raise
