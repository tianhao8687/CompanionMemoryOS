"""Minimal chat-host ingestion. Optional HTTP model configuration is loaded from TOML."""

from __future__ import annotations

import argparse
from pathlib import Path

from companion_memoryos.config import load_config
from companion_memoryos.database import Database
from companion_memoryos.schemas import ConsentState, MemoryScope, ProcessTurnRequest
from companion_memoryos.service import CompanionMemoryService
from companion_memoryos.store import MemoryStore


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("content")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--message-id", required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--user", default="user")
    parser.add_argument("--companion", default="ai")
    parser.add_argument("--relationship", default="relationship")
    parser.add_argument("--conversation", default="chat")
    parser.add_argument("--calendar-timezone", default="UTC")
    parser.add_argument("--allow-model", action="store_true")
    args = parser.parse_args()
    config = load_config(args.config)
    database = Database(args.data_dir, config)
    database.initialize()
    service = CompanionMemoryService(MemoryStore(database), config)
    result = service.process_turn(
        ProcessTurnRequest(
            user_id=args.user,
            scope=MemoryScope(
                companion_id=args.companion,
                relationship_id=args.relationship,
                conversation_id=args.conversation,
            ),
            content=args.content,
            idempotency_key=args.message_id,
            consent=ConsentState.GRANTED,
            model_consent=ConsentState.GRANTED if args.allow_model else ConsentState.DENIED,
            calendar_timezone=args.calendar_timezone,
        )
    )
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
