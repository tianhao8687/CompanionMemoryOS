"""Local, synchronous ingestion orchestration; a model call never holds a DB transaction."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any
from weakref import WeakValueDictionary

from companion_memoryos.constants import RECALL_QUERY_MAX_CHARACTERS
from companion_memoryos.entity_resolution import domain_filter, entity_catalog
from companion_memoryos.interpreter import (
    INTERPRETER_PROMPT_SHA256,
    INTERPRETER_PROMPT_VERSION,
    InterpreterError,
    OpenAICompatibleInterpreter,
    interpreter_messages,
)
from companion_memoryos.schemas import (
    ConsentState,
    ConversationRole,
    ConversationTurnInput,
    ConversationTurnRecord,
    ConversationTurnStorageResult,
    DiscourseInterpretRequest,
    InterpreterContext,
    InterpreterEpisode,
    InterpreterTurn,
    InterpreterUsage,
    ProcessTurnRequest,
    ProcessTurnResult,
    RealityLayer,
    RecallRequest,
    Sensitivity,
    SpeechSpan,
    TurnDeletionState,
    TurnInterpretation,
    TurnInterpretationRequest,
)
from companion_memoryos.store import SCOPE_COLUMNS, datetime_to_text, scope_values, utc_now

if TYPE_CHECKING:
    from companion_memoryos.service import CompanionMemoryService


class _TurnLock:
    def __init__(self) -> None:
        self.lock = threading.Lock()


_LOCKS: WeakValueDictionary[tuple[str, str], _TurnLock] = WeakValueDictionary()
_LOCKS_GUARD = threading.Lock()


@contextmanager
def _single_flight(database: str, turn_id: str) -> Iterator[None]:
    # One process only. Durable interpretation idempotency still governs multiple processes.
    key = (database, turn_id)
    with _LOCKS_GUARD:
        holder = _LOCKS.get(key)
        if holder is None:
            holder = _TurnLock()
            _LOCKS[key] = holder
    with holder.lock:
        yield


def process_turn(
    service: CompanionMemoryService,
    request: ProcessTurnRequest,
) -> ProcessTurnResult:
    storage = _persist(service, request)
    result = ProcessTurnResult(storage=storage, interpretation_status="not_stored")
    if storage.turn is None:
        result.reasons.extend(storage.reasons)
        return result
    with _single_flight(str(service.store.database.path), storage.turn.id):
        _interpret(service, request, result)
    return _finish(service, request, result)


def _persist(
    service: CompanionMemoryService,
    request: ProcessTurnRequest,
) -> ConversationTurnStorageResult:
    # Default timestamps must remain stable when the host retries the same delivery key.
    exact_scope = " AND ".join(f"{column} IS ?" for column in SCOPE_COLUMNS)
    with service.store.database.atomic() as connection:
        previous = connection.execute(
            f"SELECT occurred_at FROM conversation_turns WHERE user_id = ? AND {exact_scope} "
            "AND idempotency_key = ?",
            (request.user_id, *scope_values(request.scope), request.idempotency_key),
        ).fetchone()
        occurred_at = request.occurred_at or (
            previous["occurred_at"] if previous is not None else utc_now()
        )
        spans = request.speech_spans
        if not spans and request.reality_layer is not RealityLayer.REAL_WORLD:
            spans = [
                SpeechSpan(
                    start_offset=0,
                    end_offset=len(request.content),
                    attributed_speaker_id=request.actor_id,
                    reality_layer=request.reality_layer,
                    machine_generated=False,
                )
            ]
        assert request.actor_id is not None
        return service.append_turn(
            ConversationTurnInput(
                user_id=request.user_id,
                scope=request.scope,
                actor_id=request.actor_id,
                role=request.role,
                content=request.content,
                occurred_at=occurred_at,
                consent=request.consent,
                sensitivity=request.sensitivity,
                reply_to_turn_id=request.reply_to_turn_id,
                speech_spans=spans,
                idempotency_key=request.idempotency_key,
                source_ref="conversation:process",
                metadata={"process_reality_layer": request.reality_layer.value},
            )
        )


def _interpret(
    service: CompanionMemoryService,
    request: ProcessTurnRequest,
    result: ProcessTurnResult,
) -> None:
    turn = result.storage.turn
    assert turn is not None
    previous = service.get_turn_interpretation(turn.id, turn.user_id)
    if previous is not None:
        result.interpretation_status = "cached"
        result.interpretation = previous
        result.discourse = previous.discourse
        result.estimated_input_tokens = previous.processing_metadata.get("estimated_input_tokens")
        if previous.processing_metadata.get("usage") is not None:
            result.model_usage = InterpreterUsage.model_validate(
                previous.processing_metadata["usage"]
            )
        result.reasons.append("existing_interpretation_reused_without_model_call")
        return
    if turn.role is ConversationRole.USER:
        result.discourse = service.interpret_turn(
            DiscourseInterpretRequest(
                user_id=turn.user_id,
                scope=turn.scope,
                turn_id=turn.id,
                apply_low_risk_actions=request.apply_low_risk_actions
                and result.storage.duplicate_of is None
                and not _is_stale(service, turn),
            )
        )
    if service.config.interpreter.skip_exact_directives and _exact_directive(service, turn):
        result.interpretation = service.apply_turn_interpretation(
            turn.id,
            TurnInterpretationRequest(
                user_id=turn.user_id,
                scope=turn.scope,
                model_output=TurnInterpretation(),
                model_fingerprint=f"deterministic:{service.config.fingerprint()}",
                idempotency_key=f"process:{turn.id}",
                apply_low_risk_actions=False,
            ),
            prior_discourse=result.discourse,
        )
        result.interpretation_status = "rules_only"
        result.reasons.append("exact_directive_handled_locally")
        return
    if service.turn_interpreter is None:
        result.interpretation_status = "not_configured"
        result.reasons.append("raw_turn_and_local_rules_available_without_model")
        return
    if request.model_consent is not ConsentState.GRANTED or (
        turn.sensitivity is not Sensitivity.NORMAL and not request.allow_sensitive_model_input
    ):
        result.interpretation_status = "not_authorized"
        result.reasons.append("model_context_requires_host_authorization")
        return
    context = _context(service, request, turn)
    result.estimated_input_tokens = _fit_context(service, context)
    if result.estimated_input_tokens > service.config.interpreter.max_input_tokens:
        result.interpretation_status = "budget_exceeded"
        result.reasons.append("current_turn_not_truncated_or_sent_over_input_budget")
        return
    if not _source_active(service, turn):
        result.interpretation_status = "source_invalidated"
        return
    try:
        result.model_calls = 1
        output = service.turn_interpreter.interpret(context)
        result.model_usage = output.usage
        proposed, reasons = _eligible_proposals(output.interpretation, context)
        result.reasons.extend(reasons)
        if not _source_active(service, turn):
            result.interpretation_status = "source_invalidated"
            return
        interpretation_request = TurnInterpretationRequest(
            user_id=turn.user_id,
            scope=turn.scope,
            model_output=proposed,
            model_fingerprint=output.model_fingerprint,
            idempotency_key=f"process:{turn.id}",
            episode_max_gap_seconds=request.episode_max_gap_seconds,
            apply_low_risk_actions=request.apply_low_risk_actions and not _is_stale(service, turn),
            processing_metadata={
                "prompt_version": INTERPRETER_PROMPT_VERSION
                if isinstance(service.turn_interpreter, OpenAICompatibleInterpreter)
                else None,
                "prompt_sha256": INTERPRETER_PROMPT_SHA256
                if isinstance(service.turn_interpreter, OpenAICompatibleInterpreter)
                else None,
                "budget_template_sha256": INTERPRETER_PROMPT_SHA256,
                "config_fingerprint": service.config.fingerprint(),
                "estimated_input_tokens": result.estimated_input_tokens,
                "usage": output.usage.model_dump() if output.usage is not None else None,
                "calendar_timezone": request.calendar_timezone,
                "proposal_filter_reasons": reasons,
            },
        )
        try:
            result.interpretation = service.apply_turn_interpretation(
                turn.id,
                interpretation_request,
                prior_discourse=result.discourse,
            )
        except ValueError:
            # Another process can finish first; use the durable winning receipt, not a new write.
            winner = service.get_turn_interpretation(turn.id, turn.user_id)
            if winner is None:
                raise
            result.interpretation = winner
            result.reasons.append("concurrent_interpretation_receipt_reused")
        result.discourse = result.interpretation.discourse
        result.interpretation_status = "completed"
    except InterpreterError as error:
        result.interpretation_status = "failed"
        # Only our adapter's fixed codes are exposed, never arbitrary provider exception text.
        result.reasons.append(
            str(error)
            if str(error)
            in {
                "interpreter_api_key_missing",
                "interpreter_timeout",
                "interpreter_http_error",
                "interpreter_unavailable",
                "interpreter_response_too_large",
                "interpreter_incomplete_output",
                "interpreter_refused_or_tool_output",
                "interpreter_invalid_output",
            }
            else "interpreter_failed"
        )
    except Exception:
        # Plugin/model failures must not undo an already committed original conversation.
        result.interpretation_status = "failed"
        result.reasons.append("interpretation_or_candidate_validation_failed")


def _exact_directive(service: CompanionMemoryService, turn: ConversationTurnRecord) -> bool:
    if turn.role is not ConversationRole.USER:
        return False
    content = service._direct_user_discourse_text(turn).strip(" \t\r\n。.!！?？")
    return bool(content) and any(
        content.casefold() == phrase
        for phrases in service.config.discourse.model_dump().values()
        for phrase in phrases
    )


def _context(
    service: CompanionMemoryService,
    request: ProcessTurnRequest,
    turn: ConversationTurnRecord,
) -> InterpreterContext:
    settings = service.config.interpreter
    exact_scope = " AND ".join(f"{column} IS ?" for column in SCOPE_COLUMNS)
    normal_only = "" if request.allow_sensitive_model_input else " AND sensitivity = 'normal'"
    realm_sql, realm_parameters = service.store._realm_filter(
        "conversation_turns",
        request.reality_layer,
    )
    with service.store.database.connection() as connection:
        rows = connection.execute(
            f"SELECT * FROM conversation_turns WHERE user_id = ? AND {exact_scope} "
            "AND server_sequence < ? AND occurred_at <= ? AND deletion_state = 'active' "
            "AND consent = 'granted' "
            f"{realm_sql}{normal_only} ORDER BY occurred_at DESC, server_sequence DESC LIMIT ?",
            (
                turn.user_id,
                *scope_values(turn.scope),
                turn.server_sequence,
                datetime_to_text(turn.occurred_at),
                *realm_parameters,
                settings.recent_turn_limit,
            ),
        ).fetchall()
    recent = [_turn_context(service.store._row_to_turn(row)) for row in reversed(rows)]
    entities, _ = entity_catalog(
        service.store,
        turn.user_id,
        turn.scope,
        request.reality_layer,
        turn.occurred_at,
        settings.entity_candidate_limit,
        text="\n".join([turn.content, *(item.content for item in recent)]),
        allow_sensitive=request.allow_sensitive_model_input,
    )
    return InterpreterContext(
        user_id=turn.user_id,
        companion_id=turn.scope.companion_id,
        current_turn=_turn_context(turn),
        calendar_timezone=request.calendar_timezone,
        reality_layer=request.reality_layer,
        recent_turns=recent,
        known_entities=entities,
        episodes=_episode_context(service, request, turn),
    )


def _turn_context(turn: ConversationTurnRecord) -> InterpreterTurn:
    return InterpreterTurn(
        id=turn.id,
        actor_id=turn.actor_id,
        role=turn.role,
        content=turn.content,
        occurred_at=turn.occurred_at,
        speech_spans=turn.speech_spans,
    )


def _episode_context(
    service: CompanionMemoryService,
    request: ProcessTurnRequest,
    turn: ConversationTurnRecord,
) -> list[InterpreterEpisode]:
    domain, values = domain_filter("e", turn.scope)
    turn_domain, turn_values = domain_filter("t", turn.scope)
    normal_only = (
        ""
        if request.allow_sensitive_model_input
        else (
            " AND NOT EXISTS (SELECT 1 FROM conversation_turns sensitive "
            "WHERE sensitive.episode_id = e.id AND sensitive.deletion_state = 'active' "
            "AND sensitive.sensitivity != 'normal')"
        )
    )
    with service.store.database.connection() as connection:
        rows = connection.execute(
            f"SELECT e.*, t.id AS continuity_turn_id, MAX(t.occurred_at) AS last_evidence "
            "FROM episodes e JOIN conversation_turns t ON t.episode_id = e.id "
            f"WHERE e.user_id = ? AND {domain} "
            "AND (e.conversation_id IS NULL OR e.conversation_id = ?) "
            f"AND t.user_id = ? AND {turn_domain} "
            "AND e.status = 'open' AND e.reality_layer = ? "
            "AND t.deletion_state = 'active' AND t.consent = 'granted' "
            f"AND t.server_sequence < ? AND t.occurred_at <= ? {normal_only} "
            "GROUP BY e.id ORDER BY last_evidence DESC, e.id LIMIT ?",
            (
                turn.user_id,
                *values,
                turn.scope.conversation_id,
                turn.user_id,
                *turn_values,
                request.reality_layer.value,
                turn.server_sequence,
                datetime_to_text(turn.occurred_at),
                service.config.interpreter.episode_candidate_limit,
            ),
        ).fetchall()
    return [
        InterpreterEpisode(
            id=row["id"],
            title=row["title"],
            topic_keys=json.loads(row["topic_keys_json"]),
            participant_actor_ids=json.loads(row["participant_actor_ids_json"]),
            reality_layer=row["reality_layer"],
            continuity_turn_id=row["continuity_turn_id"],
        )
        for row in rows
    ]


def _fit_context(service: CompanionMemoryService, context: InterpreterContext) -> int:
    settings = service.config.interpreter
    while True:
        count = service.token_counter.count(
            json.dumps(
                interpreter_messages(context, settings.instruction_role),
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        if count <= settings.max_input_tokens:
            return count
        if context.recent_turns:
            context.recent_turns.pop(0)
        elif context.episodes:
            context.episodes.pop()
        elif context.known_entities:
            context.known_entities.pop()
        else:
            return count


def _eligible_proposals(
    proposed: TurnInterpretation,
    context: InterpreterContext,
) -> tuple[TurnInterpretation, list[str]]:
    entities = [
        entity
        for entity in proposed.entities
        if context.reality_layer is RealityLayer.REAL_WORLD
        or entity.reality_layer is context.reality_layer
    ]
    local_refs = {entity.ref for entity in entities}
    allowed_subjects = {
        None,
        context.user_id,
        context.companion_id,
        context.current_turn.actor_id,
        *local_refs,
    }
    reasons: list[str] = []
    updates: dict[str, Any] = {"entities": entities}
    for category in ("memory_candidates", "state_claims"):
        candidates = []
        for item in getattr(proposed, category):
            if (
                item.subject_actor_id not in allowed_subjects
                or not set(item.entity_refs) <= local_refs
            ):
                reasons.append("unknown_subject_candidate_deferred")
                continue
            if context.current_turn.role is ConversationRole.ASSISTANT and (
                item.subject_actor_id != context.current_turn.actor_id
            ):
                reasons.append("assistant_output_not_promoted_to_user_or_shared_fact")
                continue
            if context.reality_layer is not RealityLayer.REAL_WORLD and (
                item.reality_layer is not context.reality_layer
            ):
                reasons.append("candidate_reality_mismatch_deferred")
                continue
            candidates.append(item)
        updates[category] = candidates
    hint = proposed.episode_hint
    if hint is not None and (
        hint.reality_layer is not context.reality_layer
        or (
            hint.action == "attach"
            and not any(
                episode.id == hint.episode_id
                and episode.continuity_turn_id == hint.continuity_turn_id
                for episode in context.episodes
            )
        )
        or any(
            actor not in allowed_subjects | {entity.id for entity in context.known_entities}
            for actor in hint.participant_actor_ids
        )
    ):
        updates["episode_hint"] = None
        reasons.append("unsupported_episode_hint_deferred")
    if context.current_turn.role is not ConversationRole.USER or (
        context.reality_layer is not RealityLayer.REAL_WORLD
    ):
        updates["open_loop_candidates"] = []
        updates["discourse_signals"] = []
    return proposed.model_copy(update=updates), reasons


def _source_active(service: CompanionMemoryService, turn: ConversationTurnRecord) -> bool:
    try:
        current = service.store.get_turn(turn.id, turn.user_id)
        return (
            current.deletion_state is TurnDeletionState.ACTIVE
            and current.consent is ConsentState.GRANTED
        )
    except KeyError:
        return False


def _is_stale(service: CompanionMemoryService, turn: ConversationTurnRecord) -> bool:
    scope = " AND ".join(f"{column} IS ?" for column in SCOPE_COLUMNS)
    with service.store.database.connection() as connection:
        return (
            connection.execute(
                f"SELECT 1 FROM conversation_turns WHERE user_id = ? AND {scope} "
                "AND role = 'user' AND server_sequence > ? AND deletion_state = 'active' LIMIT 1",
                (turn.user_id, *scope_values(turn.scope), turn.server_sequence),
            ).fetchone()
            is not None
        )


def _finish(
    service: CompanionMemoryService,
    request: ProcessTurnRequest,
    result: ProcessTurnResult,
) -> ProcessTurnResult:
    turn = result.storage.turn
    assert turn is not None
    if not _source_active(service, turn):
        result.interpretation_status = "source_invalidated"
        result.interpretation = None
        result.discourse = None
        result.storage.turn = None
        result.reasons.append("source_invalidated_during_processing")
        return result
    result.storage.turn = service.store.get_turn(turn.id, turn.user_id)
    result.response_stale = _is_stale(service, turn)
    if result.response_stale:
        result.reasons.append("newer_user_turn_requires_response_replanning")
        return result
    if (
        request.enable_recall
        and turn.role is ConversationRole.USER
        and not (
            result.discourse is not None
            and result.discourse.current_turn_requires_full_attention
            and not result.discourse.user_asked_memory_question
        )
    ):
        if len(turn.content) > RECALL_QUERY_MAX_CHARACTERS and request.recall_request is None:
            result.reasons.append("long_turn_recalled_with_bounded_query_prefix")
        result.response_context = service.recall(
            request.recall_request
            or RecallRequest(
                user_id=turn.user_id,
                scope=turn.scope,
                query=turn.content[:RECALL_QUERY_MAX_CHARACTERS],
                calendar_timezone=request.calendar_timezone,
                state_reality_layer=request.reality_layer,
                exclude_turn_ids=[turn.id],
            )
        )
        # Do not deliver an old context if a new turn arrived during retrieval.
        result.response_stale = _is_stale(service, turn)
        if result.response_stale or not _source_active(service, turn):
            result.response_context = None
            result.reasons.append("context_invalidated_before_return")
    return result
