from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import typer

from companion_memoryos.api import create_app
from companion_memoryos.config import CompanionConfig, default_data_dir, load_config
from companion_memoryos.database import Database
from companion_memoryos.schemas import (
    AnswerCardinality,
    AnswerSemantics,
    ChannelStatus,
    ConsentState,
    ConversationEventInput,
    ConversationRepairRequest,
    ConversationRole,
    ConversationTurnInput,
    DiscourseInterpretRequest,
    ElicitationKind,
    EpistemicKind,
    EventStatus,
    EvidenceActor,
    ExperienceEvidenceKind,
    FollowUpMode,
    FollowUpRequest,
    MemoryCorrectionRequest,
    MemoryInput,
    MemoryKind,
    MemoryScope,
    MemoryStatus,
    MemoryUseInput,
    OpenLoopInput,
    OpenLoopKind,
    OpenLoopStatus,
    OpenLoopTransition,
    OpenLoopUpdateRequest,
    PolicyConstraintInput,
    PolicyEffect,
    PolicyGateRequest,
    ProcessingWatermarkInput,
    RealityLayer,
    RecallIntent,
    RecallRequest,
    RecallUseMode,
    RepairKind,
    ResolutionStatus,
    ResponseBeatSentRequest,
    ResponseGoal,
    ResponsePlanInterruptRequest,
    ResponsePlanRequest,
    ResponsePlanResolveRequest,
    ResponsePlanStatus,
    ReviewDecision,
    Sensitivity,
    StateQuery,
    TemporalAnchorInput,
    TemporalAnchorStatus,
    TurnModality,
)
from companion_memoryos.security import TokenManager
from companion_memoryos.service import CompanionMemoryService
from companion_memoryos.store import MemoryStore

app = typer.Typer(no_args_is_help=True, help="CompanionMemoryOS local memory service")


@dataclass(frozen=True)
class Runtime:
    data_dir: Path
    config: CompanionConfig
    database: Database
    service: CompanionMemoryService


@app.callback()
def configure(
    ctx: typer.Context,
    data_dir: Path = typer.Option(default_data_dir(), help="Local data directory"),
    config_file: Path | None = typer.Option(None, "--config", help="TOML override"),
) -> None:
    config = load_config(config_file)
    database = Database(data_dir, config)
    database.initialize()
    ctx.obj = Runtime(
        data_dir.resolve(), config, database, CompanionMemoryService(MemoryStore(database), config)
    )


@app.command("init")
def initialize(ctx: typer.Context) -> None:
    runtime = _runtime(ctx)
    runtime.database.integrity_check()
    token_path = TokenManager(runtime.data_dir, runtime.config).path
    TokenManager(runtime.data_dir, runtime.config).get_or_create()
    _emit(
        {"database": str(runtime.database.path), "token_file": str(token_path), "status": "ready"}
    )


@app.command()
def serve(ctx: typer.Context) -> None:
    import uvicorn

    runtime = _runtime(ctx)
    api = create_app(runtime.data_dir, runtime.config)
    uvicorn.run(api, host=runtime.config.server.host, port=runtime.config.server.port)


@app.command()
def remember(
    ctx: typer.Context,
    user_id: str,
    kind: MemoryKind,
    title: str,
    content: str,
    consent: ConsentState = ConsentState.UNKNOWN,
    explicit_user_request: bool = typer.Option(False, "--explicit/--inferred"),
    sensitivity: Sensitivity = Sensitivity.NORMAL,
    stable_key: str | None = None,
    epistemic_kind: EpistemicKind = EpistemicKind.OBSERVATION,
    resolution_status: ResolutionStatus = ResolutionStatus.RESOLVED,
    reality_layer: RealityLayer = RealityLayer.REAL_WORLD,
    source_actor: EvidenceActor = EvidenceActor.AUTHENTICATED_USER,
    quote_depth: int = 0,
    elicitation_kind: ElicitationKind = ElicitationKind.SPONTANEOUS,
    subject_actor_id: str | None = None,
    predicate: str | None = None,
    valid_time_start: str | None = None,
    valid_time_end: str | None = None,
    evidence_turn_id: list[str] | None = typer.Option(None, "--evidence-turn-id"),
    companion_id: str | None = None,
    relationship_id: str | None = None,
    conversation_id: str | None = None,
    group_id: str | None = None,
) -> None:
    result = _runtime(ctx).service.remember(
        MemoryInput(
            user_id=user_id,
            scope=_scope(companion_id, relationship_id, conversation_id, group_id),
            kind=kind,
            title=title,
            content=content,
            consent=consent,
            explicit_user_request=explicit_user_request,
            sensitivity=sensitivity,
            stable_key=stable_key,
            epistemic_kind=epistemic_kind,
            resolution_status=resolution_status,
            reality_layer=reality_layer,
            source_actor=source_actor,
            quote_depth=quote_depth,
            elicitation_kind=elicitation_kind,
            subject_actor_id=subject_actor_id,
            predicate=predicate,
            valid_time_start=(
                _parse_aware_datetime(valid_time_start) if valid_time_start is not None else None
            ),
            valid_time_end=(
                _parse_aware_datetime(valid_time_end) if valid_time_end is not None else None
            ),
            evidence_turn_ids=evidence_turn_id or [],
        )
    )
    _emit(result.model_dump(mode="json"))


@app.command()
def review(
    ctx: typer.Context,
    memory_id: str,
    user_id: str,
    decision: ReviewDecision,
) -> None:
    result = _runtime(ctx).service.review(memory_id, user_id, decision)
    _emit(result.model_dump(mode="json"))


@app.command()
def correct(
    ctx: typer.Context,
    memory_id: str,
    user_id: str,
    content: str,
    title: str | None = None,
    consent: ConsentState = ConsentState.UNKNOWN,
    evidence_turn_id: list[str] | None = typer.Option(None, "--evidence-turn-id"),
) -> None:
    result = _runtime(ctx).service.correct(
        memory_id,
        MemoryCorrectionRequest(
            user_id=user_id,
            content=content,
            title=title,
            consent=consent,
            evidence_turn_ids=evidence_turn_id or [],
        ),
    )
    _emit(result.model_dump(mode="json"))


@app.command("archive-event")
def archive_event(
    ctx: typer.Context,
    user_id: str,
    session_id: str,
    role: ConversationRole,
    content: str,
    consent: ConsentState = ConsentState.UNKNOWN,
    sensitivity: Sensitivity = Sensitivity.NORMAL,
    companion_id: str | None = None,
    relationship_id: str | None = None,
    group_id: str | None = None,
) -> None:
    result = _runtime(ctx).service.archive_event(
        ConversationEventInput(
            user_id=user_id,
            scope=_scope(companion_id, relationship_id, session_id, group_id),
            session_id=session_id,
            role=role,
            content=content,
            consent=consent,
            sensitivity=sensitivity,
        )
    )
    _emit(result.model_dump(mode="json"))


@app.command("append-turn")
def append_turn(
    ctx: typer.Context,
    user_id: str,
    conversation_id: str,
    actor_id: str,
    role: ConversationRole,
    content: str,
    consent: ConsentState = ConsentState.UNKNOWN,
    sensitivity: Sensitivity = Sensitivity.NORMAL,
    modality: TurnModality = TurnModality.TEXT,
    language: str | None = None,
    reply_to_turn_id: str | None = None,
    supersedes_turn_id: str | None = None,
    episode_id: str | None = None,
    source_ref: str = "conversation:turn",
    idempotency_key: str | None = None,
    retrieval_key: list[str] | None = typer.Option(None, "--retrieval-key"),
    embedding: list[float] | None = typer.Option(None, "--embedding"),
    embedding_space: str | None = None,
    companion_id: str | None = None,
    relationship_id: str | None = None,
    group_id: str | None = None,
) -> None:
    result = _runtime(ctx).service.append_turn(
        ConversationTurnInput(
            user_id=user_id,
            scope=_scope(companion_id, relationship_id, conversation_id, group_id),
            actor_id=actor_id,
            role=role,
            content=content,
            consent=consent,
            sensitivity=sensitivity,
            modality=modality,
            language=language,
            reply_to_turn_id=reply_to_turn_id,
            supersedes_turn_id=supersedes_turn_id,
            episode_id=episode_id,
            source_ref=source_ref,
            idempotency_key=idempotency_key,
            retrieval_keys=retrieval_key or [],
            embedding=embedding,
            embedding_space=embedding_space,
        )
    )
    _emit(result.model_dump(mode="json"))


@app.command("create-open-loop")
def create_open_loop(
    ctx: typer.Context,
    user_id: str,
    relationship_id: str,
    kind: OpenLoopKind,
    summary: str,
    topic_key: list[str] | None = typer.Option(None, "--topic-key"),
    follow_up_mode: FollowUpMode = FollowUpMode.WHEN_RELEVANT,
    follow_up_after: str | None = None,
    expires_at: str | None = None,
    source_turn_id: str | None = None,
    consent: ConsentState = ConsentState.UNKNOWN,
    sensitivity: Sensitivity = Sensitivity.NORMAL,
    companion_id: str | None = None,
    conversation_id: str | None = None,
    group_id: str | None = None,
) -> None:
    result = _runtime(ctx).service.create_open_loop(
        OpenLoopInput(
            user_id=user_id,
            scope=_scope(companion_id, relationship_id, conversation_id, group_id),
            kind=kind,
            summary=summary,
            topic_keys=topic_key or [],
            follow_up_mode=follow_up_mode,
            follow_up_after=(
                _parse_aware_datetime(follow_up_after) if follow_up_after is not None else None
            ),
            expires_at=_parse_aware_datetime(expires_at) if expires_at is not None else None,
            source_turn_id=source_turn_id,
            consent=consent,
            sensitivity=sensitivity,
        )
    )
    _emit(result.model_dump(mode="json"))


@app.command("update-open-loop")
def update_open_loop(
    ctx: typer.Context,
    open_loop_id: str,
    user_id: str,
    transition: OpenLoopTransition,
    resolution_summary: str | None = None,
    next_follow_up_at: str | None = None,
    response_group_id: str | None = None,
    expected_revision: int | None = None,
    source_turn_id: str | None = None,
) -> None:
    result = _runtime(ctx).service.update_open_loop(
        open_loop_id,
        OpenLoopUpdateRequest(
            user_id=user_id,
            transition=transition,
            source_turn_id=source_turn_id,
            resolution_summary=resolution_summary,
            next_follow_up_at=(
                _parse_aware_datetime(next_follow_up_at) if next_follow_up_at is not None else None
            ),
            response_group_id=response_group_id,
            expected_revision=expected_revision,
        ),
    )
    _emit(result.model_dump(mode="json"))


@app.command("evaluate-follow-up")
def evaluate_follow_up(
    ctx: typer.Context,
    user_id: str,
    relationship_id: str,
    topic_key: list[str] | None = typer.Option(None, "--topic-key"),
    current_turn_requires_full_attention: bool = False,
    user_reopened_topic: bool = False,
    reopened_open_loop_id: str | None = None,
    allow_due_topic_switch: bool = False,
    companion_id: str | None = None,
    conversation_id: str | None = None,
    group_id: str | None = None,
) -> None:
    result = _runtime(ctx).service.evaluate_follow_up(
        FollowUpRequest(
            user_id=user_id,
            scope=_scope(companion_id, relationship_id, conversation_id, group_id),
            current_topic_keys=topic_key or [],
            current_turn_requires_full_attention=current_turn_requires_full_attention,
            user_reopened_topic=user_reopened_topic,
            reopened_open_loop_id=reopened_open_loop_id,
            allow_due_topic_switch=allow_due_topic_switch,
        )
    )
    _emit(result.model_dump(mode="json"))


@app.command("interpret-turn")
def interpret_turn(
    ctx: typer.Context,
    user_id: str,
    conversation_id: str,
    turn_id: str,
    topic_key: list[str] | None = typer.Option(None, "--topic-key"),
    apply_low_risk_actions: bool = True,
    companion_id: str | None = None,
    relationship_id: str | None = None,
    group_id: str | None = None,
) -> None:
    result = _runtime(ctx).service.interpret_turn(
        DiscourseInterpretRequest(
            user_id=user_id,
            scope=_scope(companion_id, relationship_id, conversation_id, group_id),
            turn_id=turn_id,
            current_topic_keys=topic_key or [],
            apply_low_risk_actions=apply_low_risk_actions,
        )
    )
    _emit(result.model_dump(mode="json"))


@app.command("plan-response")
def plan_response(
    ctx: typer.Context,
    user_id: str,
    conversation_id: str,
    trigger_turn_id: str,
    goal: ResponseGoal,
    query: str | None = None,
    intent: RecallIntent = RecallIntent.GENERAL,
    topic_key: list[str] | None = typer.Option(None, "--topic-key"),
    user_asked_memory_question: bool = False,
    user_reopened_topic: bool = False,
    reopened_open_loop_id: str | None = None,
    current_turn_requires_full_attention: bool = False,
    allow_follow_up: bool = True,
    allow_due_topic_switch: bool = False,
    allow_afterthought: bool | None = None,
    channel_supports_multiple_beats: bool = True,
    conversation_started_at: str | None = None,
    companion_id: str | None = None,
    relationship_id: str | None = None,
    group_id: str | None = None,
    staged: bool = False,
) -> None:
    scope = _scope(companion_id, relationship_id, conversation_id, group_id)
    recall_request = (
        RecallRequest(user_id=user_id, scope=scope, query=query, intent=intent)
        if query is not None
        else None
    )
    request = ResponsePlanRequest(
        user_id=user_id,
        scope=scope,
        trigger_turn_id=trigger_turn_id,
        goal=goal,
        recall_request=recall_request,
        user_asked_memory_question=user_asked_memory_question,
        user_reopened_topic=user_reopened_topic,
        reopened_open_loop_id=reopened_open_loop_id,
        current_turn_requires_full_attention=current_turn_requires_full_attention,
        current_topic_keys=topic_key or [],
        allow_follow_up=allow_follow_up,
        allow_due_topic_switch=allow_due_topic_switch,
        allow_afterthought=allow_afterthought,
        channel_supports_multiple_beats=channel_supports_multiple_beats,
        conversation_started_at=(
            _parse_aware_datetime(conversation_started_at)
            if conversation_started_at is not None
            else None
        ),
    )
    result = (
        _runtime(ctx).service.stage_response_plan(request)
        if staged
        else _runtime(ctx).service.plan_response(request)
    )
    _emit(result.model_dump(mode="json"))


@app.command("resolve-response-plan")
def resolve_response_plan(
    ctx: typer.Context,
    plan_id: str,
    user_id: str,
    expected_revision: int,
    resolution_key: str,
) -> None:
    result = _runtime(ctx).service.resolve_staged_response_plan(
        plan_id,
        ResponsePlanResolveRequest(
            user_id=user_id,
            expected_revision=expected_revision,
            resolution_key=resolution_key,
        ),
    )
    _emit(result.model_dump(mode="json"))


@app.command("mark-response-beat-sent")
def mark_response_beat_sent(
    ctx: typer.Context,
    plan_id: str,
    beat_id: str,
    user_id: str,
    rendered_text: str,
    task_policy_version: int,
    host_release_signal: bool = False,
) -> None:
    result = _runtime(ctx).service.mark_response_beat_sent(
        plan_id,
        beat_id,
        ResponseBeatSentRequest(
            user_id=user_id,
            rendered_text=rendered_text,
            task_policy_version=task_policy_version,
            host_release_signal=host_release_signal,
        ),
    )
    _emit(result.model_dump(mode="json"))


@app.command("interrupt-response-plans")
def interrupt_response_plans(
    ctx: typer.Context,
    user_id: str,
    conversation_id: str,
    companion_id: str | None = None,
    relationship_id: str | None = None,
    group_id: str | None = None,
) -> None:
    cancelled = _runtime(ctx).service.interrupt_response_plans(
        ResponsePlanInterruptRequest(
            user_id=user_id,
            scope=_scope(companion_id, relationship_id, conversation_id, group_id),
        )
    )
    _emit({"cancelled_response_plan_ids": cancelled})


@app.command("repair-conversation")
def repair_conversation(
    ctx: typer.Context,
    user_id: str,
    kind: RepairKind,
    memory_id: str | None = None,
    evidence_kind: ExperienceEvidenceKind = ExperienceEvidenceKind.MEMORY,
    evidence_id: str | None = None,
    open_loop_id: str | None = None,
    replacement_content: str | None = None,
    replacement_title: str | None = None,
    resolution_summary: str | None = None,
    source_turn_id: str | None = None,
    companion_id: str | None = None,
    relationship_id: str | None = None,
    conversation_id: str | None = None,
    group_id: str | None = None,
) -> None:
    result = _runtime(ctx).service.apply_repair(
        ConversationRepairRequest(
            user_id=user_id,
            scope=_scope(companion_id, relationship_id, conversation_id, group_id),
            kind=kind,
            source_turn_id=source_turn_id,
            memory_id=memory_id,
            evidence_kind=evidence_kind,
            evidence_id=evidence_id,
            open_loop_id=open_loop_id,
            replacement_content=replacement_content,
            replacement_title=replacement_title,
            resolution_summary=resolution_summary,
        )
    )
    _emit(result.model_dump(mode="json"))


@app.command("query-state")
def query_state(
    ctx: typer.Context,
    user_id: str,
    predicate: str,
    semantics: AnswerSemantics = AnswerSemantics.STATE_AT_VALID_TIME,
    reality_layer: RealityLayer = RealityLayer.REAL_WORLD,
    valid_at: str | None = None,
    known_at: str | None = None,
    companion_id: str | None = None,
    relationship_id: str | None = None,
    conversation_id: str | None = None,
    group_id: str | None = None,
) -> None:
    now = datetime.now(UTC)
    result = _runtime(ctx).service.query_state(
        StateQuery(
            user_id=user_id,
            scope=_scope(companion_id, relationship_id, conversation_id, group_id),
            predicate=predicate,
            semantics=semantics,
            reality_layer=reality_layer,
            valid_at=_parse_aware_datetime(valid_at) if valid_at is not None else now,
            known_at=_parse_aware_datetime(known_at) if known_at is not None else now,
        )
    )
    _emit(result.model_dump(mode="json"))


@app.command("set-processing-watermark")
def set_processing_watermark(
    ctx: typer.Context,
    user_id: str,
    channel: str,
    status: ChannelStatus,
    durable_sequence: int | None = None,
    indexed_sequence: int | None = None,
    model_fingerprint: str | None = None,
    companion_id: str | None = None,
    relationship_id: str | None = None,
    conversation_id: str | None = None,
    group_id: str | None = None,
) -> None:
    result = _runtime(ctx).service.update_processing_watermark(
        ProcessingWatermarkInput(
            user_id=user_id,
            scope=_scope(companion_id, relationship_id, conversation_id, group_id),
            channel=channel,
            status=status,
            durable_sequence=durable_sequence,
            indexed_sequence=indexed_sequence,
            model_fingerprint=model_fingerprint,
        )
    )
    _emit(result.model_dump(mode="json"))


@app.command("set-policy")
def set_policy(
    ctx: typer.Context,
    user_id: str,
    action: str,
    effect: PolicyEffect,
    reason_code: str,
    channel: str = "all",
    source_turn_id: str | None = None,
    source_direct_user_instruction: bool = False,
    valid_from: str | None = None,
    valid_until: str | None = None,
    companion_id: str | None = None,
    relationship_id: str | None = None,
    conversation_id: str | None = None,
    group_id: str | None = None,
) -> None:
    result = _runtime(ctx).service.create_policy_constraint(
        PolicyConstraintInput(
            user_id=user_id,
            scope=_scope(companion_id, relationship_id, conversation_id, group_id),
            action=action,
            effect=effect,
            reason_code=reason_code,
            channel=channel,
            source_turn_id=source_turn_id,
            source_direct_user_instruction=source_direct_user_instruction,
            valid_from=(
                _parse_aware_datetime(valid_from) if valid_from is not None else datetime.now(UTC)
            ),
            valid_until=(_parse_aware_datetime(valid_until) if valid_until is not None else None),
        )
    )
    _emit(result.model_dump(mode="json"))


@app.command("evaluate-policy")
def evaluate_policy(
    ctx: typer.Context,
    user_id: str,
    action: list[str] = typer.Option(..., "--action"),
    channel: str = "chat",
    task_policy_version: int | None = None,
    companion_id: str | None = None,
    relationship_id: str | None = None,
    conversation_id: str | None = None,
    group_id: str | None = None,
) -> None:
    result = _runtime(ctx).service.evaluate_policy(
        PolicyGateRequest(
            user_id=user_id,
            scope=_scope(companion_id, relationship_id, conversation_id, group_id),
            actions=action,
            channel=channel,
            task_policy_version=task_policy_version,
        )
    )
    _emit(result.model_dump(mode="json"))


@app.command("revoke-policy")
def revoke_policy(
    ctx: typer.Context,
    constraint_id: str,
    user_id: str,
) -> None:
    result = _runtime(ctx).service.revoke_policy_constraint(constraint_id, user_id)
    _emit(result.model_dump(mode="json"))


@app.command("purge-policy")
def purge_policy(
    ctx: typer.Context,
    constraint_id: str,
    user_id: str,
) -> None:
    _runtime(ctx).service.purge_policy_constraint(constraint_id, user_id)
    _emit(
        {
            "status": "primary_store_purged",
            "policy_constraint_id": constraint_id,
        }
    )


@app.command("record-memory-use")
def record_memory_use(
    ctx: typer.Context,
    user_id: str,
    memory_id: str,
    response_group_id: str,
    use_mode: RecallUseMode,
    purpose: str,
    companion_id: str | None = None,
    relationship_id: str | None = None,
    conversation_id: str | None = None,
    group_id: str | None = None,
) -> None:
    result = _runtime(ctx).service.record_memory_use(
        MemoryUseInput(
            user_id=user_id,
            scope=_scope(companion_id, relationship_id, conversation_id, group_id),
            memory_id=memory_id,
            response_group_id=response_group_id,
            use_mode=use_mode,
            purpose=purpose,
        )
    )
    _emit(result.model_dump(mode="json"))


@app.command("list-events")
def list_events(
    ctx: typer.Context,
    user_id: str,
    event_status: list[EventStatus] | None = typer.Option(None, "--status"),
    limit: int | None = None,
) -> None:
    statuses = set(event_status) if event_status else None
    result = _runtime(ctx).service.list_events(user_id, statuses, limit)
    _emit([event.model_dump(mode="json") for event in result])


@app.command("list-turns")
def list_turns(
    ctx: typer.Context,
    user_id: str,
    companion_id: str | None = None,
    relationship_id: str | None = None,
    conversation_id: str | None = None,
    group_id: str | None = None,
    limit: int | None = None,
) -> None:
    turns = _runtime(ctx).service.list_turns(
        user_id,
        _scope(companion_id, relationship_id, conversation_id, group_id),
        limit,
    )
    _emit([turn.model_dump(mode="json") for turn in turns])


@app.command("list-open-loops")
def list_open_loops(
    ctx: typer.Context,
    user_id: str,
    open_loop_status: list[OpenLoopStatus] | None = typer.Option(None, "--status"),
    companion_id: str | None = None,
    relationship_id: str | None = None,
    conversation_id: str | None = None,
    group_id: str | None = None,
    limit: int | None = None,
) -> None:
    scope = _scope(companion_id, relationship_id, conversation_id, group_id)
    result = _runtime(ctx).service.list_open_loops(
        user_id,
        None if scope.is_global else scope,
        set(open_loop_status) if open_loop_status else None,
        limit,
    )
    _emit([item.model_dump(mode="json") for item in result])


@app.command("list-response-plans")
def list_response_plans(
    ctx: typer.Context,
    user_id: str,
    plan_status: list[ResponsePlanStatus] | None = typer.Option(None, "--status"),
    companion_id: str | None = None,
    relationship_id: str | None = None,
    conversation_id: str | None = None,
    group_id: str | None = None,
    limit: int | None = None,
) -> None:
    scope = _scope(companion_id, relationship_id, conversation_id, group_id)
    result = _runtime(ctx).service.list_response_plans(
        user_id,
        None if scope.is_global else scope,
        set(plan_status) if plan_status else None,
        limit,
    )
    _emit([item.model_dump(mode="json") for item in result])


@app.command("forget-turn")
def forget_turn(
    ctx: typer.Context,
    turn_id: str,
    user_id: str,
    revoke_source_policies: bool = False,
) -> None:
    result = _runtime(ctx).service.forget_turn(
        turn_id,
        user_id,
        revoke_source_policies=revoke_source_policies,
    )
    _emit(result.model_dump(mode="json"))


@app.command("purge-turn")
def purge_turn(
    ctx: typer.Context,
    turn_id: str,
    user_id: str,
    revoke_source_policies: bool = False,
) -> None:
    _runtime(ctx).service.purge_turn(
        turn_id,
        user_id,
        revoke_source_policies=revoke_source_policies,
    )
    _emit({"status": "primary_store_purged", "turn_id": turn_id})


@app.command("forget-event")
def forget_event(ctx: typer.Context, event_id: str, user_id: str) -> None:
    result = _runtime(ctx).service.forget_event(event_id, user_id)
    _emit(result.model_dump(mode="json"))


@app.command("purge-event")
def purge_event(ctx: typer.Context, event_id: str, user_id: str) -> None:
    _runtime(ctx).service.purge_event(event_id, user_id)
    _emit({"status": "primary_store_purged", "event_id": event_id})


@app.command("remember-time-anchor")
def remember_time_anchor(
    ctx: typer.Context,
    user_id: str,
    name: str,
    start_at: str,
    end_at: str,
    alias: list[str] | None = typer.Option(None, "--alias"),
    consent: ConsentState = ConsentState.UNKNOWN,
    sensitivity: Sensitivity = Sensitivity.NORMAL,
    companion_id: str | None = None,
    relationship_id: str | None = None,
    conversation_id: str | None = None,
    group_id: str | None = None,
) -> None:
    result = _runtime(ctx).service.remember_temporal_anchor(
        TemporalAnchorInput(
            user_id=user_id,
            scope=_scope(companion_id, relationship_id, conversation_id, group_id),
            name=name,
            aliases=alias or [],
            start_at=_parse_aware_datetime(start_at),
            end_at=_parse_aware_datetime(end_at),
            consent=consent,
            sensitivity=sensitivity,
        )
    )
    _emit(result.model_dump(mode="json"))


@app.command("list-time-anchors")
def list_time_anchors(
    ctx: typer.Context,
    user_id: str,
    anchor_status: list[TemporalAnchorStatus] | None = typer.Option(None, "--status"),
    limit: int | None = None,
) -> None:
    statuses = set(anchor_status) if anchor_status else None
    anchors = _runtime(ctx).service.list_temporal_anchors(user_id, statuses, limit)
    _emit([anchor.model_dump(mode="json") for anchor in anchors])


@app.command("forget-time-anchor")
def forget_time_anchor(ctx: typer.Context, anchor_id: str, user_id: str) -> None:
    result = _runtime(ctx).service.forget_temporal_anchor(anchor_id, user_id)
    _emit(result.model_dump(mode="json"))


@app.command("purge-time-anchor")
def purge_time_anchor(ctx: typer.Context, anchor_id: str, user_id: str) -> None:
    _runtime(ctx).service.purge_temporal_anchor(anchor_id, user_id)
    _emit({"status": "primary_store_purged", "anchor_id": anchor_id})


@app.command()
def recall(
    ctx: typer.Context,
    user_id: str,
    query: str = typer.Argument(""),
    intent: RecallIntent = RecallIntent.GENERAL,
    limit: int | None = None,
    event_limit: int | None = None,
    turn_limit: int | None = None,
    max_characters: int | None = None,
    max_tokens: int | None = None,
    answer_semantics: AnswerSemantics = AnswerSemantics.EVENT_RECALL,
    answer_cardinality: AnswerCardinality = AnswerCardinality.AUTO,
    utterance_actor_id: str | None = None,
    state_predicate: str | None = None,
    state_reality_layer: RealityLayer = RealityLayer.REAL_WORLD,
    valid_at: str | None = None,
    known_at: str | None = None,
    companion_id: str | None = None,
    relationship_id: str | None = None,
    conversation_id: str | None = None,
    group_id: str | None = None,
) -> None:
    result = _runtime(ctx).service.recall(
        RecallRequest(
            user_id=user_id,
            scope=_scope(companion_id, relationship_id, conversation_id, group_id),
            query=query,
            intent=intent,
            limit=limit,
            event_limit=event_limit,
            turn_limit=turn_limit,
            max_characters=max_characters,
            max_tokens=max_tokens,
            answer_semantics=answer_semantics,
            answer_cardinality=answer_cardinality,
            utterance_actor_id=utterance_actor_id,
            state_predicate=state_predicate,
            state_reality_layer=state_reality_layer,
            valid_at=_parse_aware_datetime(valid_at) if valid_at is not None else None,
            known_at=_parse_aware_datetime(known_at) if known_at is not None else None,
        )
    )
    _emit(result.model_dump(mode="json"))


@app.command()
def profile(
    ctx: typer.Context,
    user_id: str,
    companion_id: str | None = None,
    relationship_id: str | None = None,
    conversation_id: str | None = None,
    group_id: str | None = None,
) -> None:
    result = _runtime(ctx).service.profile(
        user_id,
        _scope(companion_id, relationship_id, conversation_id, group_id),
    )
    _emit(result.model_dump(mode="json"))


@app.command("list")
def list_command(
    ctx: typer.Context,
    user_id: str,
    memory_status: list[MemoryStatus] | None = typer.Option(None, "--status"),
    limit: int | None = None,
) -> None:
    statuses = set(memory_status) if memory_status else None
    result = _runtime(ctx).service.list_memories(user_id, statuses, limit)
    _emit([memory.model_dump(mode="json") for memory in result])


@app.command()
def forget(ctx: typer.Context, memory_id: str, user_id: str) -> None:
    result = _runtime(ctx).service.forget(memory_id, user_id)
    _emit(result.model_dump(mode="json"))


@app.command()
def purge(ctx: typer.Context, memory_id: str, user_id: str) -> None:
    _runtime(ctx).service.purge(memory_id, user_id)
    _emit({"status": "primary_store_purged", "memory_id": memory_id})


@app.command("export")
def export_command(ctx: typer.Context, user_id: str) -> None:
    result = _runtime(ctx).service.export(user_id)
    _emit(result.model_dump(mode="json"))


@app.command("show-config")
def show_config(ctx: typer.Context) -> None:
    runtime = _runtime(ctx)
    _emit(
        {
            "config": runtime.config.model_dump(mode="json"),
            "fingerprint": runtime.config.fingerprint(),
        }
    )


def _runtime(ctx: typer.Context) -> Runtime:
    runtime = ctx.obj
    if not isinstance(runtime, Runtime):
        raise RuntimeError("CLI runtime was not initialized")
    return runtime


def _emit(value: Any) -> None:
    typer.echo(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _scope(
    companion_id: str | None = None,
    relationship_id: str | None = None,
    conversation_id: str | None = None,
    group_id: str | None = None,
) -> MemoryScope:
    return MemoryScope(
        companion_id=companion_id,
        relationship_id=relationship_id,
        conversation_id=conversation_id,
        group_id=group_id,
    )


def _parse_aware_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise typer.BadParameter("timestamp must use ISO 8601 format") from error
    if parsed.tzinfo is None:
        raise typer.BadParameter("timestamp must include a timezone")
    return parsed


def main() -> None:
    app()
