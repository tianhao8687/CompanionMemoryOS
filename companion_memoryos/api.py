from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse

from companion_memoryos.config import CompanionConfig, default_data_dir, load_config
from companion_memoryos.constants import APPLICATION_VERSION
from companion_memoryos.database import Database
from companion_memoryos.schemas import (
    ChannelWatermark,
    CompanionContext,
    ConversationEventInput,
    ConversationEventRecord,
    ConversationRepairRequest,
    ConversationRepairResult,
    ConversationTurnInput,
    ConversationTurnRecord,
    ConversationTurnStorageResult,
    DiscourseInterpretation,
    DiscourseInterpretRequest,
    EventStatus,
    EventStorageResult,
    ExportBundle,
    FollowUpDecision,
    FollowUpRequest,
    InterpretedResponsePlan,
    InterpretedResponsePlanRequest,
    MemoryCorrectionRequest,
    MemoryCorrectionResult,
    MemoryInput,
    MemoryRecord,
    MemoryReferenceFeedbackInput,
    MemoryReferenceFeedbackRecord,
    MemoryScope,
    MemoryStatus,
    MemoryUseInput,
    MemoryUseRecord,
    OpenLoopInput,
    OpenLoopRecord,
    OpenLoopStatus,
    OpenLoopStorageResult,
    OpenLoopUpdateRequest,
    PolicyConstraintInput,
    PolicyConstraintRecord,
    PolicyGateDecision,
    PolicyGateRequest,
    ProactivityDecision,
    ProactivityRequest,
    ProcessingWatermarkInput,
    ProfileSnapshot,
    RecallRequest,
    ResponseBeatSentRequest,
    ResponsePlanInterruptRequest,
    ResponsePlanRecord,
    ResponsePlanRequest,
    ResponsePlanResolveRequest,
    ResponsePlanStatus,
    ReviewRequest,
    StateQuery,
    StateQueryResult,
    StorageResult,
    TemporalAnchorInput,
    TemporalAnchorRecord,
    TemporalAnchorStatus,
    TemporalAnchorStorageResult,
)
from companion_memoryos.security import TokenManager
from companion_memoryos.service import CompanionMemoryService
from companion_memoryos.store import MemoryStore


def create_app(
    data_dir: Path | None = None,
    config: CompanionConfig | None = None,
) -> FastAPI:
    selected_config = config or load_config()
    selected_data_dir = (data_dir or default_data_dir()).expanduser().resolve()
    database = Database(selected_data_dir, selected_config)
    database.initialize()
    database.integrity_check()
    service = CompanionMemoryService(MemoryStore(database), selected_config)
    tokens = TokenManager(selected_data_dir, selected_config)
    tokens.get_or_create()

    app = FastAPI(
        title="CompanionMemoryOS",
        version=APPLICATION_VERSION,
        description="Local-first, consent-first memory API for emotional companions.",
    )
    app.state.service = service
    app.state.config = selected_config
    app.state.tokens = tokens

    def authorize(authorization: str | None = Header(default=None)) -> None:
        if authorization is None or not authorization.lower().startswith("bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="missing bearer token",
            )
        token = authorization.split(maxsplit=1)[1].strip()
        if not token or not tokens.authenticate(token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid bearer token",
            )

    protected = [Depends(authorize)]

    @app.exception_handler(KeyError)
    async def not_found(_: Request, error: KeyError) -> JSONResponse:
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(error)})

    @app.exception_handler(ValueError)
    async def conflict(_: Request, error: ValueError) -> JSONResponse:
        return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": str(error)})

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/v1/config", dependencies=protected)
    def get_config() -> dict[str, object]:
        return {
            "config": selected_config.model_dump(mode="json"),
            "fingerprint": selected_config.fingerprint(),
        }

    @app.post("/api/v1/memories", response_model=StorageResult, dependencies=protected)
    def remember(item: MemoryInput) -> StorageResult:
        return service.remember(item)

    @app.post(
        "/api/v1/memories/{memory_id}/correct",
        response_model=MemoryCorrectionResult,
        dependencies=protected,
    )
    def correct(memory_id: str, request: MemoryCorrectionRequest) -> MemoryCorrectionResult:
        return service.correct(memory_id, request)

    @app.post("/api/v1/events", response_model=EventStorageResult, dependencies=protected)
    def archive_event(item: ConversationEventInput) -> EventStorageResult:
        return service.archive_event(item)

    @app.post(
        "/api/v1/turns",
        response_model=ConversationTurnStorageResult,
        dependencies=protected,
    )
    def append_turn(item: ConversationTurnInput) -> ConversationTurnStorageResult:
        return service.append_turn(item)

    @app.post(
        "/api/v1/turns/interpret",
        response_model=DiscourseInterpretation,
        dependencies=protected,
    )
    def interpret_turn(request: DiscourseInterpretRequest) -> DiscourseInterpretation:
        return service.interpret_turn(request)

    @app.post(
        "/api/v1/open-loops",
        response_model=OpenLoopStorageResult,
        dependencies=protected,
    )
    def create_open_loop(item: OpenLoopInput) -> OpenLoopStorageResult:
        return service.create_open_loop(item)

    @app.patch(
        "/api/v1/open-loops/{open_loop_id}",
        response_model=OpenLoopRecord,
        dependencies=protected,
    )
    def update_open_loop(open_loop_id: str, request: OpenLoopUpdateRequest) -> OpenLoopRecord:
        return service.update_open_loop(open_loop_id, request)

    @app.post(
        "/api/v1/follow-ups/evaluate",
        response_model=FollowUpDecision,
        dependencies=protected,
    )
    def evaluate_follow_up(request: FollowUpRequest) -> FollowUpDecision:
        return service.evaluate_follow_up(request)

    @app.post(
        "/api/v1/reference-feedback",
        response_model=MemoryReferenceFeedbackRecord,
        dependencies=protected,
    )
    def record_reference_feedback(
        item: MemoryReferenceFeedbackInput,
    ) -> MemoryReferenceFeedbackRecord:
        return service.record_reference_feedback(item)

    @app.post(
        "/api/v1/response-plans",
        response_model=ResponsePlanRecord,
        dependencies=protected,
    )
    def plan_response(request: ResponsePlanRequest) -> ResponsePlanRecord:
        return service.plan_response(request)

    @app.post(
        "/api/v1/response-plans/staged",
        response_model=ResponsePlanRecord,
        dependencies=protected,
    )
    def stage_response_plan(request: ResponsePlanRequest) -> ResponsePlanRecord:
        return service.stage_response_plan(request)

    @app.post(
        "/api/v1/response-plans/interpreted-staged",
        response_model=InterpretedResponsePlan,
        dependencies=protected,
    )
    def stage_interpreted_response_plan(
        request: InterpretedResponsePlanRequest,
    ) -> InterpretedResponsePlan:
        return service.stage_interpreted_response_plan(request)

    @app.post(
        "/api/v1/response-plans/{plan_id}/resolve",
        response_model=ResponsePlanRecord,
        dependencies=protected,
    )
    def resolve_staged_response_plan(
        plan_id: str, request: ResponsePlanResolveRequest
    ) -> ResponsePlanRecord:
        return service.resolve_staged_response_plan(plan_id, request)

    @app.post("/api/v1/response-plans/interrupt", dependencies=protected)
    def interrupt_response_plans(
        request: ResponsePlanInterruptRequest,
    ) -> dict[str, list[str]]:
        return {"cancelled_response_plan_ids": service.interrupt_response_plans(request)}

    @app.get(
        "/api/v1/response-plans/{plan_id}",
        response_model=ResponsePlanRecord,
        dependencies=protected,
    )
    def get_response_plan(plan_id: str, user_id: str = Query(min_length=1)) -> ResponsePlanRecord:
        return service.get_response_plan(plan_id, user_id)

    @app.post(
        "/api/v1/response-plans/{plan_id}/beats/{beat_id}/sent",
        response_model=ResponsePlanRecord,
        dependencies=protected,
    )
    def mark_response_beat_sent(
        plan_id: str,
        beat_id: str,
        request: ResponseBeatSentRequest,
    ) -> ResponsePlanRecord:
        return service.mark_response_beat_sent(plan_id, beat_id, request)

    @app.delete(
        "/api/v1/response-plans/{plan_id}",
        response_model=ResponsePlanRecord,
        dependencies=protected,
    )
    def cancel_response_plan(
        plan_id: str,
        user_id: str = Query(min_length=1),
        reason: str = Query(default="host_cancelled", min_length=1, max_length=240),
    ) -> ResponsePlanRecord:
        return service.cancel_response_plan(plan_id, user_id, reason)

    @app.post(
        "/api/v1/repairs",
        response_model=ConversationRepairResult,
        dependencies=protected,
    )
    def apply_repair(request: ConversationRepairRequest) -> ConversationRepairResult:
        return service.apply_repair(request)

    @app.post(
        "/api/v1/time-anchors",
        response_model=TemporalAnchorStorageResult,
        dependencies=protected,
    )
    def remember_temporal_anchor(item: TemporalAnchorInput) -> TemporalAnchorStorageResult:
        return service.remember_temporal_anchor(item)

    @app.post(
        "/api/v1/memories/{memory_id}/review",
        response_model=MemoryRecord,
        dependencies=protected,
    )
    def review(memory_id: str, request: ReviewRequest) -> MemoryRecord:
        return service.review(memory_id, request.user_id, request.decision)

    @app.delete("/api/v1/memories/{memory_id}", dependencies=protected)
    def delete_memory(
        memory_id: str,
        user_id: str = Query(min_length=1),
        mode: Literal["forget", "purge"] = "purge",
    ) -> MemoryRecord | dict[str, str]:
        if mode == "forget":
            return service.forget(memory_id, user_id)
        service.purge(memory_id, user_id)
        return {"status": "primary_store_purged", "memory_id": memory_id}

    @app.post("/api/v1/recall", response_model=CompanionContext, dependencies=protected)
    def recall(request: RecallRequest) -> CompanionContext:
        return service.recall(request)

    @app.post(
        "/api/v1/state/query",
        response_model=StateQueryResult,
        dependencies=protected,
    )
    def query_state(request: StateQuery) -> StateQueryResult:
        return service.query_state(request)

    @app.put(
        "/api/v1/processing-watermarks",
        response_model=ChannelWatermark,
        dependencies=protected,
    )
    def update_processing_watermark(item: ProcessingWatermarkInput) -> ChannelWatermark:
        return service.update_processing_watermark(item)

    @app.post(
        "/api/v1/memory-uses",
        response_model=MemoryUseRecord,
        dependencies=protected,
    )
    def record_memory_use(item: MemoryUseInput) -> MemoryUseRecord:
        return service.record_memory_use(item)

    @app.post(
        "/api/v1/policy-constraints",
        response_model=PolicyConstraintRecord,
        dependencies=protected,
    )
    def create_policy_constraint(item: PolicyConstraintInput) -> PolicyConstraintRecord:
        return service.create_policy_constraint(item)

    @app.post(
        "/api/v1/policy/evaluate",
        response_model=PolicyGateDecision,
        dependencies=protected,
    )
    def evaluate_policy(request: PolicyGateRequest) -> PolicyGateDecision:
        return service.evaluate_policy(request)

    @app.post(
        "/api/v1/proactivity/evaluate",
        response_model=ProactivityDecision,
        dependencies=protected,
    )
    def evaluate_proactivity(request: ProactivityRequest) -> ProactivityDecision:
        return service.proactivity(request)

    @app.get(
        "/api/v1/users/{user_id}/profile",
        response_model=ProfileSnapshot,
        dependencies=protected,
    )
    def profile(
        user_id: str,
        companion_id: str | None = Query(default=None),
        relationship_id: str | None = Query(default=None),
        conversation_id: str | None = Query(default=None),
        group_id: str | None = Query(default=None),
    ) -> ProfileSnapshot:
        return service.profile(
            user_id,
            MemoryScope(
                companion_id=companion_id,
                relationship_id=relationship_id,
                conversation_id=conversation_id,
                group_id=group_id,
            ),
        )

    @app.get(
        "/api/v1/users/{user_id}/memories",
        response_model=list[MemoryRecord],
        dependencies=protected,
    )
    def list_memories(
        user_id: str,
        memory_status: set[MemoryStatus] | None = Query(default=None, alias="status"),
        limit: int | None = Query(default=None, gt=0),
    ) -> list[MemoryRecord]:
        return service.list_memories(user_id, memory_status, limit)

    @app.get(
        "/api/v1/users/{user_id}/events",
        response_model=list[ConversationEventRecord],
        dependencies=protected,
    )
    def list_events(
        user_id: str,
        event_status: set[EventStatus] | None = Query(default=None, alias="status"),
        limit: int | None = Query(default=None, gt=0),
    ) -> list[ConversationEventRecord]:
        return service.list_events(user_id, event_status, limit)

    @app.get(
        "/api/v1/users/{user_id}/turns",
        response_model=list[ConversationTurnRecord],
        dependencies=protected,
    )
    def list_turns(
        user_id: str,
        companion_id: str | None = Query(default=None),
        relationship_id: str | None = Query(default=None),
        conversation_id: str | None = Query(default=None),
        group_id: str | None = Query(default=None),
        limit: int | None = Query(default=None, gt=0),
    ) -> list[ConversationTurnRecord]:
        scope = MemoryScope(
            companion_id=companion_id,
            relationship_id=relationship_id,
            conversation_id=conversation_id,
            group_id=group_id,
        )
        return service.list_turns(user_id, scope, limit)

    @app.get(
        "/api/v1/users/{user_id}/open-loops",
        response_model=list[OpenLoopRecord],
        dependencies=protected,
    )
    def list_open_loops(
        user_id: str,
        open_loop_status: set[OpenLoopStatus] | None = Query(default=None, alias="status"),
        companion_id: str | None = Query(default=None),
        relationship_id: str | None = Query(default=None),
        conversation_id: str | None = Query(default=None),
        group_id: str | None = Query(default=None),
        limit: int | None = Query(default=None, gt=0),
    ) -> list[OpenLoopRecord]:
        scope = MemoryScope(
            companion_id=companion_id,
            relationship_id=relationship_id,
            conversation_id=conversation_id,
            group_id=group_id,
        )
        return service.list_open_loops(
            user_id, None if scope.is_global else scope, open_loop_status, limit
        )

    @app.get(
        "/api/v1/users/{user_id}/reference-feedback",
        response_model=list[MemoryReferenceFeedbackRecord],
        dependencies=protected,
    )
    def list_reference_feedback(
        user_id: str,
        memory_id: list[str] | None = Query(default=None),
        companion_id: str | None = Query(default=None),
        relationship_id: str | None = Query(default=None),
        conversation_id: str | None = Query(default=None),
        group_id: str | None = Query(default=None),
        limit: int | None = Query(default=None, gt=0),
    ) -> list[MemoryReferenceFeedbackRecord]:
        scope = MemoryScope(
            companion_id=companion_id,
            relationship_id=relationship_id,
            conversation_id=conversation_id,
            group_id=group_id,
        )
        return service.list_reference_feedback(
            user_id, None if scope.is_global else scope, memory_id, limit
        )

    @app.get(
        "/api/v1/users/{user_id}/response-plans",
        response_model=list[ResponsePlanRecord],
        dependencies=protected,
    )
    def list_response_plans(
        user_id: str,
        plan_status: set[ResponsePlanStatus] | None = Query(default=None, alias="status"),
        companion_id: str | None = Query(default=None),
        relationship_id: str | None = Query(default=None),
        conversation_id: str | None = Query(default=None),
        group_id: str | None = Query(default=None),
        limit: int | None = Query(default=None, gt=0),
    ) -> list[ResponsePlanRecord]:
        scope = MemoryScope(
            companion_id=companion_id,
            relationship_id=relationship_id,
            conversation_id=conversation_id,
            group_id=group_id,
        )
        return service.list_response_plans(
            user_id, None if scope.is_global else scope, plan_status, limit
        )

    @app.get(
        "/api/v1/users/{user_id}/memory-uses",
        response_model=list[MemoryUseRecord],
        dependencies=protected,
    )
    def list_memory_uses(
        user_id: str,
        memory_id: str | None = Query(default=None),
        limit: int | None = Query(default=None, gt=0),
    ) -> list[MemoryUseRecord]:
        return service.list_memory_uses(user_id, memory_id, limit)

    @app.get(
        "/api/v1/users/{user_id}/policy-constraints",
        response_model=list[PolicyConstraintRecord],
        dependencies=protected,
    )
    def list_policy_constraints(
        user_id: str,
        limit: int | None = Query(default=None, gt=0),
    ) -> list[PolicyConstraintRecord]:
        return service.list_policy_constraints(user_id, limit)

    @app.delete("/api/v1/policy-constraints/{constraint_id}", dependencies=protected)
    def delete_policy_constraint(
        constraint_id: str,
        user_id: str = Query(min_length=1),
        mode: Literal["revoke", "purge"] = "revoke",
    ) -> PolicyConstraintRecord | dict[str, str]:
        if mode == "revoke":
            return service.revoke_policy_constraint(constraint_id, user_id)
        service.purge_policy_constraint(constraint_id, user_id)
        return {
            "status": "primary_store_purged",
            "policy_constraint_id": constraint_id,
        }

    @app.get(
        "/api/v1/users/{user_id}/time-anchors",
        response_model=list[TemporalAnchorRecord],
        dependencies=protected,
    )
    def list_temporal_anchors(
        user_id: str,
        anchor_status: set[TemporalAnchorStatus] | None = Query(default=None, alias="status"),
        limit: int | None = Query(default=None, gt=0),
    ) -> list[TemporalAnchorRecord]:
        return service.list_temporal_anchors(user_id, anchor_status, limit)

    @app.delete("/api/v1/events/{event_id}", dependencies=protected)
    def delete_event(
        event_id: str,
        user_id: str = Query(min_length=1),
        mode: Literal["forget", "purge"] = "purge",
    ) -> ConversationEventRecord | dict[str, str]:
        if mode == "forget":
            return service.forget_event(event_id, user_id)
        service.purge_event(event_id, user_id)
        return {"status": "primary_store_purged", "event_id": event_id}

    @app.delete("/api/v1/turns/{turn_id}", dependencies=protected)
    def delete_turn(
        turn_id: str,
        user_id: str = Query(min_length=1),
        mode: Literal["forget", "purge"] = "purge",
        revoke_source_policies: bool = False,
    ) -> ConversationTurnRecord | dict[str, str]:
        if mode == "forget":
            return service.forget_turn(
                turn_id,
                user_id,
                revoke_source_policies=revoke_source_policies,
            )
        service.purge_turn(
            turn_id,
            user_id,
            revoke_source_policies=revoke_source_policies,
        )
        return {"status": "primary_store_purged", "turn_id": turn_id}

    @app.delete("/api/v1/time-anchors/{anchor_id}", dependencies=protected)
    def delete_temporal_anchor(
        anchor_id: str,
        user_id: str = Query(min_length=1),
        mode: Literal["forget", "purge"] = "purge",
    ) -> TemporalAnchorRecord | dict[str, str]:
        if mode == "forget":
            return service.forget_temporal_anchor(anchor_id, user_id)
        service.purge_temporal_anchor(anchor_id, user_id)
        return {"status": "primary_store_purged", "anchor_id": anchor_id}

    @app.get(
        "/api/v1/users/{user_id}/export",
        response_model=ExportBundle,
        dependencies=protected,
    )
    def export(user_id: str) -> ExportBundle:
        return service.export(user_id)

    return app
