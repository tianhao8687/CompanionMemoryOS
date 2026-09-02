"""Host-generated proposals applied through core rules, without an LLM client or worker."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from companion_memoryos.constants import DEFAULT_ENCODING
from companion_memoryos.entity_resolution import resolve_entities
from companion_memoryos.episode_store import EpisodeStore
from companion_memoryos.schemas import (
    AutomaticActionStatus,
    ConsentState,
    ConversationRole,
    DiscourseInterpretation,
    DiscourseInterpretationStatus,
    DiscourseInterpretRequest,
    DiscourseSignal,
    EpisodeAttachRequest,
    EpisodeInput,
    EpisodeStatus,
    EpistemicKind,
    EvidenceActor,
    FollowUpMode,
    MemoryInput,
    OpenLoopInput,
    ResolutionStatus,
    TurnDeletionState,
    TurnInterpretationRecord,
    TurnInterpretationRequest,
)
from companion_memoryos.store import MemoryStore, datetime_to_text, utc_now

if TYPE_CHECKING:
    from companion_memoryos.service import CompanionMemoryService


def get_interpretation(
    store: MemoryStore, turn_id: str, user_id: str
) -> TurnInterpretationRecord | None:
    with store.database.connection() as connection:
        row = connection.execute(
            "SELECT record_json FROM turn_interpretations WHERE turn_id = ? AND user_id = ?",
            (turn_id, user_id),
        ).fetchone()
    return (
        TurnInterpretationRecord.model_validate_json(row["record_json"])
        if row is not None
        else None
    )


def list_interpretations(store: MemoryStore, user_id: str) -> list[TurnInterpretationRecord]:
    with store.database.connection() as connection:
        rows = connection.execute(
            "SELECT record_json FROM turn_interpretations WHERE user_id = ? "
            "ORDER BY created_at, id",
            (user_id,),
        ).fetchall()
    return [TurnInterpretationRecord.model_validate_json(row["record_json"]) for row in rows]


def apply_interpretation(
    service: CompanionMemoryService,
    turn_id: str,
    request: TurnInterpretationRequest,
    *,
    prior_discourse: DiscourseInterpretation | None = None,
) -> TurnInterpretationRecord:
    store = service.store
    digest = interpretation_request_hash(request)
    with store.database.atomic() as connection:
        turn = store.get_turn(turn_id, request.user_id)
        if turn.scope != request.scope or turn.deletion_state is not TurnDeletionState.ACTIVE:
            raise ValueError("interpretation requires an active turn in the exact scope")
        if turn.consent is not ConsentState.GRANTED:
            raise ValueError("interpretation requires the original turn's capture consent")
        previous = connection.execute(
            "SELECT request_hash, record_json FROM turn_interpretations "
            "WHERE turn_id = ? AND user_id = ?",
            (turn_id, request.user_id),
        ).fetchone()
        if previous is not None:
            if previous["request_hash"] != digest:
                raise ValueError(
                    "turn already interpreted with a different request; use explicit corrections"
                )
            return TurnInterpretationRecord.model_validate_json(previous["record_json"])

        original_proposal = request.model_output
        proposed, entity_resolutions, entity_reasons = resolve_entities(
            store, turn, original_proposal, service.config.interpreter.entity_candidate_limit
        )
        if any(span.end_offset > len(turn.content) for span in proposed.speech_spans):
            raise ValueError("interpreted speech span exceeds original content")
        memory_inputs: list[MemoryInput] = []
        for candidate in [*proposed.memory_candidates, *proposed.state_claims]:
            if any(
                index >= len(proposed.speech_spans) for index in candidate.evidence_span_indices
            ):
                raise ValueError("memory candidate refers to an unknown speech span")
            spans = [proposed.speech_spans[index] for index in candidate.evidence_span_indices]
            if any(span.reality_layer is not candidate.reality_layer for span in spans):
                raise ValueError("candidate reality layer does not match its evidence span")
            if turn.role is ConversationRole.ASSISTANT and candidate.subject_actor_id not in {
                None,
                turn.actor_id,
            }:
                raise ValueError("assistant turns cannot propose another actor's state")
            # The envelope and raw evidence come from the ledger, never from model output.
            kind = candidate.epistemic_kind
            if kind in {EpistemicKind.DIRECT_SELF_REPORT, EpistemicKind.RELATIONSHIP_CONTRACT}:
                kind = EpistemicKind.OBSERVATION
            memory_inputs.append(
                MemoryInput(
                    user_id=turn.user_id,
                    scope=turn.scope,
                    kind=candidate.kind,
                    title=candidate.title,
                    content=candidate.content,
                    subject_actor_id=candidate.subject_actor_id,
                    predicate=candidate.predicate,
                    entities=[
                        resolution.entity
                        for resolution in entity_resolutions
                        if resolution.entity is not None
                        and (
                            resolution.ref in candidate.entity_refs
                            or resolution.entity.id == candidate.subject_actor_id
                        )
                    ],
                    epistemic_kind=kind,
                    reality_layer=candidate.reality_layer,
                    source_actor=EvidenceActor.MACHINE,
                    consent=turn.consent,
                    sensitivity=turn.sensitivity,
                    explicit_user_request=False,
                    quote_depth=max((span.quote_depth for span in spans), default=0),
                    confidence=candidate.confidence,
                    resolution_status=(
                        ResolutionStatus.CONTESTED
                        if kind is EpistemicKind.INTERPRETATION_HYPOTHESIS
                        else ResolutionStatus.RESOLVED
                    ),
                    event_at=turn.occurred_at,
                    valid_time_start=candidate.valid_time_start,
                    valid_time_end=candidate.valid_time_end,
                    evidence_turn_ids=[turn.id],
                    source_ref=f"turn:{turn.id}",
                    source_excerpt="\n".join(
                        turn.content[span.start_offset : span.end_offset] for span in spans
                    )
                    or None,
                    metadata={
                        "interpretation_model": request.model_fingerprint,
                        "proposed_epistemic_kind": candidate.epistemic_kind.value,
                        "evidence_span_indices": candidate.evidence_span_indices,
                        "interpretation_key": request.idempotency_key,
                    },
                )
            )

        loop_inputs = [
            OpenLoopInput(
                user_id=turn.user_id,
                scope=turn.scope,
                kind=candidate.kind,
                summary=candidate.summary,
                topic_keys=candidate.topic_keys or proposed.topics,
                follow_up_mode=FollowUpMode.USER_LED,
                source_turn_id=turn.id,
                consent=turn.consent,
                sensitivity=turn.sensitivity,
                opened_at=turn.occurred_at,
                metadata={
                    "interpretation_model": request.model_fingerprint,
                    "candidate_only": True,
                },
            )
            for candidate in proposed.open_loop_candidates
        ]
        if loop_inputs and turn.role is not ConversationRole.USER:
            raise ValueError("automatic open-loop proposals require a user turn")

        episodes = EpisodeStore(store)
        episode_id = None
        hint = proposed.episode_hint
        if hint is not None:
            if turn.episode_id is not None:
                raise ValueError("interpreters cannot reassign existing episode membership")
            if hint.action == "new":
                assert hint.title is not None
                # Cross-conversation continuity is limited to the exact consent domain.
                episode = episodes.create(
                    EpisodeInput(
                        user_id=turn.user_id,
                        scope=turn.scope.model_copy(update={"conversation_id": None}),
                        title=hint.title,
                        topic_keys=proposed.topics,
                        participant_actor_ids=hint.participant_actor_ids,
                        reality_layer=hint.reality_layer,
                        started_at=turn.occurred_at,
                    )
                )
            else:
                assert hint.episode_id is not None and hint.continuity_turn_id is not None
                episode = episodes.get(hint.episode_id, turn.user_id)
                prior = store.get_turn(hint.continuity_turn_id, turn.user_id)
                if (
                    not episodes.scope_allows(episode.scope, turn.scope)
                    or not episodes.scope_allows(episode.scope, prior.scope)
                    or prior.episode_id != episode.id
                    or prior.deletion_state is not TurnDeletionState.ACTIVE
                    or prior.occurred_at > turn.occurred_at
                    or episode.reality_layer is not hint.reality_layer
                    or episode.status is not EpisodeStatus.OPEN
                ):
                    raise ValueError(
                        "episode continuity evidence does not match scope, time or reality"
                    )
                if not set(episode.topic_keys) & set(proposed.topics):
                    raise ValueError("episode attach requires a shared topic")
                if (
                    request.episode_max_gap_seconds is not None
                    and (turn.occurred_at - prior.occurred_at).total_seconds()
                    > request.episode_max_gap_seconds
                ):
                    raise ValueError("episode continuity exceeds the host-declared time window")
                if episode.participant_actor_ids and not set(episode.participant_actor_ids) & set(
                    hint.participant_actor_ids
                ):
                    raise ValueError("episode attach requires a shared participant")
            episode_id = episodes.attach(
                episode.id,
                EpisodeAttachRequest(
                    user_id=turn.user_id,
                    scope=turn.scope,
                    turn_id=turn.id,
                    expected_revision=episode.revision,
                ),
            ).id

        memory_results = [service.remember(item) for item in memory_inputs]
        loop_results = [service.create_open_loop(item) for item in loop_inputs]
        record = TurnInterpretationRecord(
            id=str(uuid4()),
            user_id=turn.user_id,
            scope=turn.scope,
            turn_id=turn.id,
            model_fingerprint=request.model_fingerprint,
            episode_max_gap_seconds=request.episode_max_gap_seconds,
            idempotency_key=request.idempotency_key,
            model_output=original_proposal,
            entity_resolutions=entity_resolutions,
            processing_metadata=request.processing_metadata,
            memory_ids=[result.memory.id for result in memory_results if result.memory is not None],
            open_loop_ids=[
                result.open_loop.id for result in loop_results if result.open_loop is not None
            ],
            episode_id=episode_id,
            created_at=utc_now(),
            reasons=[
                "model_proposals_passed_through_core_rules",
                "no_automatic_current_truth_promotion",
                "open_loops_are_user_led_not_reminders",
                *entity_reasons,
                *(reason for result in memory_results for reason in result.reasons),
                *(reason for result in loop_results for reason in result.reasons),
            ],
        )
        connection.execute(
            "INSERT INTO turn_interpretations "
            "(id, turn_id, user_id, idempotency_key, request_hash, record_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                record.id,
                turn.id,
                turn.user_id,
                request.idempotency_key,
                digest,
                record.model_dump_json(),
                datetime_to_text(record.created_at),
            ),
        )
        # Topics are retrieval keys, not new evidence or mutations of the original utterance.
        entity_keys = [
            spelling
            for resolution in entity_resolutions
            if resolution.entity is not None
            for spelling in [resolution.entity.name, *resolution.entity.aliases]
        ]
        keys = list(dict.fromkeys([*turn.retrieval_keys, *proposed.topics, *entity_keys]))
        connection.execute(
            "UPDATE conversation_turns SET retrieval_keys_json = ? WHERE id = ?",
            (json.dumps(keys, ensure_ascii=False), turn.id),
        )
        if turn.role is ConversationRole.USER:
            # The unified path already acted on explicit local instructions before the model.
            # Reuse that result so a correction is not applied to a second, older reference.
            record.discourse = (
                prior_discourse
                if (
                    prior_discourse is not None
                    and prior_discourse.status is not DiscourseInterpretationStatus.UNKNOWN
                    and not (
                        prior_discourse.automatic_action_status
                        is AutomaticActionStatus.NEEDS_TARGET
                        and DiscourseSignal.OUTCOME_REPORTED in prior_discourse.signals
                        and proposed.topics
                    )
                )
                else service.interpret_turn(
                    DiscourseInterpretRequest(
                        user_id=turn.user_id,
                        scope=turn.scope,
                        turn_id=turn.id,
                        current_topic_keys=proposed.topics,
                        apply_low_risk_actions=request.apply_low_risk_actions,
                    )
                )
            )
            if prior_discourse is not None and record.discourse is not prior_discourse:
                record.discourse.cancelled_response_plan_ids = list(
                    dict.fromkeys(
                        [
                            *prior_discourse.cancelled_response_plan_ids,
                            *record.discourse.cancelled_response_plan_ids,
                        ]
                    )
                )
            connection.execute(
                "UPDATE turn_interpretations SET record_json = ? WHERE id = ?",
                (record.model_dump_json(), record.id),
            )
        return record


def interpretation_request_hash(request: TurnInterpretationRequest) -> str:
    """Keep empty additive 0.7.5 fields out of the 0.7.4 idempotency representation."""
    exclude: dict[str, Any] = {}
    if not request.processing_metadata:
        exclude["processing_metadata"] = True
    output: dict[str, Any] = {}
    if not request.model_output.entities:
        output["entities"] = True
    for category in ("memory_candidates", "state_claims"):
        empty_fields = {
            index: {"entity_refs"}
            for index, candidate in enumerate(getattr(request.model_output, category))
            if not candidate.entity_refs
        }
        if empty_fields:
            output[category] = empty_fields
    if output:
        exclude["model_output"] = output
    return hashlib.sha256(
        request.model_dump_json(exclude=exclude).encode(DEFAULT_ENCODING)
    ).hexdigest()
