from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import typer

from companion_memoryos.api import create_app
from companion_memoryos.config import CompanionConfig, default_data_dir, load_config
from companion_memoryos.database import Database
from companion_memoryos.schemas import (
    ConsentState,
    ConversationEventInput,
    ConversationRole,
    EventStatus,
    MemoryInput,
    MemoryKind,
    MemoryStatus,
    RecallIntent,
    RecallRequest,
    ReviewDecision,
    Sensitivity,
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
) -> None:
    result = _runtime(ctx).service.remember(
        MemoryInput(
            user_id=user_id,
            kind=kind,
            title=title,
            content=content,
            consent=consent,
            explicit_user_request=explicit_user_request,
            sensitivity=sensitivity,
            stable_key=stable_key,
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


@app.command("archive-event")
def archive_event(
    ctx: typer.Context,
    user_id: str,
    session_id: str,
    role: ConversationRole,
    content: str,
    consent: ConsentState = ConsentState.UNKNOWN,
    sensitivity: Sensitivity = Sensitivity.NORMAL,
) -> None:
    result = _runtime(ctx).service.archive_event(
        ConversationEventInput(
            user_id=user_id,
            session_id=session_id,
            role=role,
            content=content,
            consent=consent,
            sensitivity=sensitivity,
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


@app.command("forget-event")
def forget_event(ctx: typer.Context, event_id: str, user_id: str) -> None:
    result = _runtime(ctx).service.forget_event(event_id, user_id)
    _emit(result.model_dump(mode="json"))


@app.command("purge-event")
def purge_event(ctx: typer.Context, event_id: str, user_id: str) -> None:
    _runtime(ctx).service.purge_event(event_id, user_id)
    _emit({"status": "purged", "event_id": event_id})


@app.command()
def recall(
    ctx: typer.Context,
    user_id: str,
    query: str = typer.Argument(""),
    intent: RecallIntent = RecallIntent.GENERAL,
    limit: int | None = None,
    event_limit: int | None = None,
    max_characters: int | None = None,
    max_tokens: int | None = None,
) -> None:
    result = _runtime(ctx).service.recall(
        RecallRequest(
            user_id=user_id,
            query=query,
            intent=intent,
            limit=limit,
            event_limit=event_limit,
            max_characters=max_characters,
            max_tokens=max_tokens,
        )
    )
    _emit(result.model_dump(mode="json"))


@app.command()
def profile(ctx: typer.Context, user_id: str) -> None:
    result = _runtime(ctx).service.profile(user_id)
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
    _emit({"status": "purged", "memory_id": memory_id})


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


def main() -> None:
    app()
