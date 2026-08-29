from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse

from companion_memoryos.config import CompanionConfig, default_data_dir, load_config
from companion_memoryos.database import Database
from companion_memoryos.schemas import (
    CompanionContext,
    ExportBundle,
    MemoryInput,
    MemoryRecord,
    MemoryStatus,
    ProfileSnapshot,
    RecallRequest,
    ReviewRequest,
    StorageResult,
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
        version="0.1.0",
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
        return {"status": "purged", "memory_id": memory_id}

    @app.post("/api/v1/recall", response_model=CompanionContext, dependencies=protected)
    def recall(request: RecallRequest) -> CompanionContext:
        return service.recall(request)

    @app.get(
        "/api/v1/users/{user_id}/profile",
        response_model=ProfileSnapshot,
        dependencies=protected,
    )
    def profile(user_id: str) -> ProfileSnapshot:
        return service.profile(user_id)

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
        "/api/v1/users/{user_id}/export",
        response_model=ExportBundle,
        dependencies=protected,
    )
    def export(user_id: str) -> ExportBundle:
        return service.export(user_id)

    return app
