"""Local message bookmarks and reader/composer state; never a memory source."""

from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import suppress
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import Depends, FastAPI, Query
from pydantic import Field

from companion_agent.journal import JournalError
from companion_agent.persona.models import PersonaModel

if TYPE_CHECKING:
    from companion_agent.app import RomanceHost


class BookmarkUpdate(PersonaModel):
    ids: list[Annotated[str, Field(min_length=1, max_length=240)]] = Field(
        min_length=1, max_length=100
    )
    saved: bool = True


class ChatUIState(PersonaModel):
    is_current: bool = False
    text: str = Field(default="", max_length=6000)
    quote_id: str | None = Field(default=None, max_length=240)
    image_ids: list[Annotated[str, Field(pattern=r"^[a-f0-9]{32}$")]] = Field(
        default_factory=list, max_length=4
    )
    anchor_id: str | None = Field(default=None, max_length=240)
    anchor_y: float = Field(default=0, ge=-100000, le=100000, allow_inf_nan=False)
    scroll_offset: float = Field(default=0, ge=0, le=100000000, allow_inf_nan=False)
    last_sequence: int = Field(default=0, ge=0)


class ChatExperience:
    def __init__(self, host: RomanceHost) -> None:
        self.host = host
        with host.database.connection() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS chat_bookmarks ("
                "turn_id TEXT PRIMARY KEY REFERENCES conversation_turns(id) ON DELETE CASCADE, "
                "saved_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')))"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS chat_ui_state ("
                "conversation_id TEXT PRIMARY KEY REFERENCES romance_conversations(id) "
                "ON DELETE CASCADE, data_json TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS chat_ui_meta (name TEXT PRIMARY KEY, value TEXT)"
            )
            cleanup = (
                "DELETE FROM chat_bookmarks WHERE turn_id=OLD.id; "
                "UPDATE chat_ui_state SET data_json=json_set(data_json,'$.quote_id',NULL) "
                "WHERE json_extract(data_json,'$.quote_id')=OLD.id; "
                "UPDATE chat_ui_state SET data_json=json_set(data_json,'$.anchor_id',NULL,"
                "'$.scroll_offset',0,'$.anchor_y',0) "
                "WHERE json_extract(data_json,'$.anchor_id')=OLD.id; "
            )
            db.execute(
                "CREATE TRIGGER IF NOT EXISTS chat_bookmark_forget AFTER UPDATE ON "
                "conversation_turns WHEN NEW.deletion_state!='active' OR NEW.consent!='granted' "
                "OR json_extract(NEW.metadata_json,'$.content_redacted_at') IS NOT NULL "
                "BEGIN " + cleanup + " END"
            )
            db.execute(
                "CREATE TRIGGER IF NOT EXISTS chat_bookmark_purge AFTER DELETE ON "
                "conversation_turns BEGIN " + cleanup + " END"
            )

    def contains(self, identifier: str) -> bool:
        with self.host.database.connection() as db:
            return (
                db.execute("SELECT 1 FROM chat_bookmarks WHERE turn_id=?", (identifier,)).fetchone()
                is not None
            )

    def last_conversation(self) -> str | None:
        with self.host.database.connection() as db:
            row = db.execute(
                "SELECT value FROM chat_ui_meta WHERE name='last_conversation' "
                "AND value IN (SELECT id FROM romance_conversations)"
            ).fetchone()
        return str(row[0]) if row else None

    def update_bookmarks(self, item: BookmarkUpdate) -> dict[str, Any]:
        self.host.journal.require_storage()
        identifiers = list(dict.fromkeys(item.ids))
        # Validate the whole selection before mutating any item.
        for identifier in identifiers:
            self.host.journal.require_turn(identifier)
        with self.host.database.atomic() as db:
            for identifier in identifiers:
                if item.saved:
                    db.execute(
                        "INSERT OR IGNORE INTO chat_bookmarks(turn_id) VALUES (?)", (identifier,)
                    )
                else:
                    db.execute("DELETE FROM chat_bookmarks WHERE turn_id=?", (identifier,))
        return {"ids": identifiers, "saved": item.saved}

    def bookmarks(self, offset: int, limit: int) -> dict[str, Any]:
        self.host.journal.require_storage()
        key = self.host.key
        with self.host.database.connection() as db:
            rows = db.execute(
                "SELECT t.*, c.title AS conversation_title FROM chat_bookmarks b "
                "JOIN conversation_turns t ON t.id=b.turn_id "
                "JOIN romance_conversations c ON c.id=t.conversation_id "
                "WHERE t.user_id=? AND t.companion_id=? AND t.relationship_id=? "
                "AND t.group_id IS NULL AND t.deletion_state='active' AND t.consent='granted' "
                "AND json_extract(t.metadata_json,'$.content_redacted_at') IS NULL "
                "ORDER BY b.saved_at DESC,t.server_sequence DESC LIMIT ? OFFSET ?",
                (key.user_id, key.companion_id, key.relationship_id, limit + 1, offset),
            ).fetchall()
        return {
            "items": [
                {
                    "message": self.host.public_turn(self.host.memory.store._row_to_turn(row)),
                    "conversation_id": row["conversation_id"],
                    "title": row["conversation_title"],
                }
                for row in rows[:limit]
            ],
            "has_more": len(rows) > limit,
        }

    def read_state(self, conversation: str) -> ChatUIState:
        self.host.scope(conversation)
        if not self.host.settings.storage_consent:
            return ChatUIState()
        with self.host.database.connection() as db:
            row = db.execute(
                "SELECT data_json FROM chat_ui_state WHERE conversation_id=?", (conversation,)
            ).fetchone()
        state = ChatUIState.model_validate_json(row[0]) if row else ChatUIState()
        for field in ("quote_id", "anchor_id"):
            identifier = getattr(state, field)
            if identifier:
                try:
                    self.host.journal.require_turn(identifier, conversation)
                except JournalError:
                    setattr(state, field, None)
                    if field == "anchor_id":
                        state.scroll_offset = 0
        valid_images = []
        for identifier in state.image_ids:
            try:
                self.host.images.require(identifier, "chat")
                valid_images.append(identifier)
            except ValueError:
                pass
        state.image_ids = valid_images
        return state

    def save_state(self, conversation: str, state: ChatUIState) -> None:
        self.host.scope(conversation)
        self.host.journal.require_storage()
        for field in ("quote_id", "anchor_id"):
            identifier = getattr(state, field)
            if identifier:
                try:
                    turn = self.host.memory.store.get_turn(identifier, self.host.key.user_id)
                except KeyError:
                    turn = None
                if (
                    turn is None
                    or turn.deletion_state.value != "active"
                    or (turn.consent.value != "granted" or turn.metadata.get("content_redacted_at"))
                ):
                    setattr(state, field, None)
                    if field == "anchor_id":
                        state.scroll_offset = 0
                else:
                    self.host.journal.require_turn(identifier, conversation)
        for identifier in state.image_ids:
            self.host.images.require(identifier, "chat")
        with self.host.database.atomic() as db:
            db.execute(
                "INSERT INTO chat_ui_state VALUES (?,?) ON CONFLICT(conversation_id) "
                "DO UPDATE SET data_json=excluded.data_json",
                (conversation, state.model_dump_json()),
            )
            if state.is_current:
                db.execute(
                    "INSERT INTO chat_ui_meta VALUES ('last_conversation',?) "
                    "ON CONFLICT(name) DO UPDATE SET value=excluded.value",
                    (conversation,),
                )

    def protected_images(self) -> set[str]:
        with self.host.database.connection() as db:
            return {
                identifier
                for row in db.execute("SELECT data_json FROM chat_ui_state")
                for identifier in json.loads(row[0]).get("image_ids", [])
            }

    def clear_private_ui(self) -> None:
        photos = self.protected_images()
        with self.host.database.atomic() as db:
            db.execute("DELETE FROM chat_ui_state")
            db.execute("DELETE FROM chat_ui_meta")
            db.execute("DELETE FROM chat_bookmarks")
        for identifier in photos:
            # Already-sent images remain governed by their original source.
            with suppress(ValueError):
                self.host.images.discard(identifier, set())


def install_routes(app: FastAPI, host: RomanceHost, authorized: Callable[..., Any]) -> None:
    dependencies = [Depends(authorized)]

    @app.get("/api/bookmarks", dependencies=dependencies)
    def bookmarks(
        offset: Annotated[int, Query(ge=0, le=100000)] = 0,
        limit: Annotated[int, Query(ge=1, le=100)] = 40,
    ) -> dict[str, Any]:
        with host.lock:
            return host.chat_experience.bookmarks(offset, limit)

    @app.put("/api/bookmarks", dependencies=dependencies)
    def update_bookmarks(item: BookmarkUpdate) -> dict[str, Any]:
        with host.lock:
            return host.chat_experience.update_bookmarks(item)

    @app.get("/api/conversations/{conversation}/ui-state", dependencies=dependencies)
    def read_state(conversation: str) -> dict[str, Any]:
        with host.lock:
            return host.chat_experience.read_state(conversation).model_dump(mode="json")

    @app.put("/api/conversations/{conversation}/ui-state", dependencies=dependencies)
    def save_state(conversation: str, item: ChatUIState) -> dict[str, bool]:
        with host.lock:
            host.chat_experience.save_state(conversation, item)
            return {"ok": True}
