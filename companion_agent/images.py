"""Local image storage and bounded, consent-aware vision context attachment."""

from __future__ import annotations

import base64
import json
import struct
import zlib
from typing import Any, Literal
from uuid import uuid4

from companion_agent.context import ChatMessage
from companion_agent.llm import MainLLM, ModelResponse
from companion_memoryos.database import Database
from companion_memoryos.schemas import (
    ConsentState,
    ConversationRole,
    ConversationTurnRecord,
    TurnDeletionState,
)
from companion_memoryos.store import MemoryStore

MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGES = 4
ImagePurpose = Literal["background", "user_avatar", "companion_avatar", "chat", "moment"]


def validate_png(data: bytes) -> tuple[int, int]:
    """Accept bounded, noninterlaced 8-bit PNG; Flutter re-encodes picked files."""
    if not 45 <= len(data) <= MAX_IMAGE_BYTES or data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("请选择有效图片（处理后最多 8 MB）。")
    offset, width, height, channels = 8, 0, 0, 0
    compressed = bytearray()
    ended = False
    while offset + 12 <= len(data):
        size = struct.unpack_from(">I", data, offset)[0]
        kind = data[offset + 4 : offset + 8]
        end = offset + 12 + size
        if end > len(data):
            raise ValueError("图片不完整。")
        payload = data[offset + 8 : end - 4]
        if zlib.crc32(kind + payload) != struct.unpack_from(">I", data, end - 4)[0]:
            raise ValueError("图片校验失败。")
        if offset == 8:
            if kind != b"IHDR" or size != 13:
                raise ValueError("图片头无效。")
            width, height, depth, color, compression, filtering, interlace = struct.unpack(
                ">IIBBBBB", payload
            )
            channels = {0: 1, 2: 3, 4: 2, 6: 4}.get(color, 0)
            if (
                not 1 <= width <= 2048
                or not 1 <= height <= 2048
                or depth != 8
                or not channels
                or compression
                or filtering
                or interlace
            ):
                raise ValueError("图片需先缩放到 2048 像素以内。")
        elif kind == b"IDAT":
            compressed.extend(payload)
        elif kind == b"IEND":
            ended = size == 0 and end == len(data)
            break
        elif kind in {b"IHDR", b"acTL", b"fcTL", b"fdAT"}:
            raise ValueError("请使用静态图片。")
        offset = end
    if not ended:
        raise ValueError("图片不完整。")
    expected = height * (width * channels + 1)
    try:
        decoder = zlib.decompressobj()
        raw = decoder.decompress(bytes(compressed), expected + 1)
        if len(raw) != expected or not decoder.eof or decoder.unused_data:
            raise ValueError("图片像素数据无效。")
        if any(raw[i] > 4 for i in range(0, len(raw), width * channels + 1)):
            raise ValueError("图片像素数据无效。")
    except zlib.error:
        raise ValueError("图片像素数据损坏。") from None
    return width, height


def visible(turn: ConversationTurnRecord) -> bool:
    return (
        turn.role is ConversationRole.USER
        and turn.deletion_state is TurnDeletionState.ACTIVE
        and turn.consent is ConsentState.GRANTED
        and not turn.metadata.get("content_redacted_at")
        and not turn.metadata.get("content_redacted_empty")
    )


class ImageStore:
    def __init__(self, database: Database, store: MemoryStore, user_id: str) -> None:
        self.database, self.store, self.user_id = database, store, user_id
        with database.connection() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS romance_images (id TEXT PRIMARY KEY, "
                "purpose TEXT NOT NULL, content BLOB NOT NULL, width INTEGER NOT NULL, "
                "height INTEGER NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS romance_message_images ("
                "conversation_id TEXT NOT NULL, request_id TEXT NOT NULL, "
                "image_ids TEXT NOT NULL, PRIMARY KEY(conversation_id, request_id))"
            )
            # Privacy lifecycle happens in the source-of-truth transaction, including
            # partial redactions. An old image must not survive a forgotten source.
            cleanup = """
                DELETE FROM romance_images WHERE purpose='chat' AND id IN (
                    SELECT value FROM romance_message_images, json_each(image_ids)
                    WHERE conversation_id=OLD.conversation_id
                    AND request_id=OLD.idempotency_key);
                DELETE FROM romance_message_images WHERE conversation_id=OLD.conversation_id
                    AND request_id=OLD.idempotency_key;
            """
            db.execute(
                "CREATE TRIGGER IF NOT EXISTS romance_image_forget AFTER UPDATE ON "
                "conversation_turns WHEN OLD.role='user' AND (NEW.deletion_state!='active' "
                "OR NEW.consent!='granted' "
                "OR json_extract(NEW.metadata_json,'$.content_redacted_at') IS NOT NULL "
                "OR json_extract(NEW.metadata_json,'$.content_redacted_empty')=1) "
                "BEGIN " + cleanup + " END"
            )
            db.execute(
                "CREATE TRIGGER IF NOT EXISTS romance_image_delete AFTER DELETE ON "
                "conversation_turns WHEN OLD.role='user' BEGIN " + cleanup + " END"
            )
            moment_cleanup = (
                "DELETE FROM romance_images WHERE purpose='moment' AND id IN "
                "(SELECT value FROM json_each(OLD.metadata_json,'$.journal_images')); "
            )
            db.execute(
                "CREATE TRIGGER IF NOT EXISTS romance_moment_forget AFTER UPDATE ON memories "
                "WHEN NEW.status IN ('forgotten','rejected','expired') OR NEW.consent!='granted' "
                "BEGIN " + moment_cleanup + " END"
            )
            db.execute(
                "CREATE TRIGGER IF NOT EXISTS romance_moment_purge AFTER DELETE ON memories "
                "BEGIN " + moment_cleanup + " END"
            )

    def upload(self, purpose: ImagePurpose, content: bytes) -> dict[str, Any]:
        width, height = validate_png(content)
        image_id = uuid4().hex
        with self.database.connection() as db:
            used = db.execute(
                "SELECT COALESCE(SUM(length(content)),0) FROM romance_images"
            ).fetchone()[0]
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='romance_stickers'").fetchone():
                used += db.execute(
                    "SELECT COALESCE(SUM(length(content)),0) FROM romance_stickers"
                ).fetchone()[0]
            if used + len(content) > 48 * 1024 * 1024:
                raise ValueError("本地图片空间已满（48 MB）。请删除不需要的图片后重试。")
            db.execute(
                "INSERT INTO romance_images VALUES (?,?,?,?,?)",
                (image_id, purpose, content, width, height),
            )
        return {"id": image_id, "width": width, "height": height, "mime_type": "image/png"}

    def require(self, image_id: str, purpose: str) -> None:
        with self.database.connection() as db:
            if (
                db.execute(
                    "SELECT 1 FROM romance_images WHERE id=? AND purpose=?", (image_id, purpose)
                ).fetchone()
                is None
            ):
                raise ValueError("图片不存在或用途不匹配，请重新选择。")

    def bind(self, conversation: str, request: str, ids: list[str]) -> None:
        if len(ids) != len(set(ids)):
            raise ValueError("请勿重复发送同一张图片。")
        for image_id in ids:
            self.require(image_id, "chat")
        with self.database.connection() as db:
            previous = db.execute(
                "SELECT image_ids FROM romance_message_images "
                "WHERE conversation_id=? AND request_id=?",
                (conversation, request),
            ).fetchone()
            if previous is not None:
                if json.loads(previous[0]) != ids:
                    raise ValueError("重试时图片必须与原消息一致。")
                return
            for image_id in ids:
                used = db.execute(
                    "SELECT 1 FROM romance_message_images, json_each(image_ids) WHERE value=?",
                    (image_id,),
                ).fetchone()
                if used:
                    raise ValueError("图片已用于另一条消息，请重新选择。")
            old_turn = db.execute(
                "SELECT 1 FROM conversation_turns "
                "WHERE user_id=? AND conversation_id=? AND idempotency_key=?",
                (self.user_id, conversation, request),
            ).fetchone()
            if old_turn and ids:
                raise ValueError("不能给已发送的消息更换图片。")
            db.execute(
                "INSERT INTO romance_message_images VALUES (?,?,?)",
                (conversation, request, json.dumps(ids)),
            )

    def ids(self, turn: ConversationTurnRecord) -> list[str]:
        if not visible(turn) or not turn.idempotency_key:
            return []
        with self.database.connection() as db:
            row = db.execute(
                "SELECT image_ids FROM romance_message_images "
                "WHERE conversation_id=? AND request_id=?",
                (turn.scope.conversation_id, turn.idempotency_key),
            ).fetchone()
        return list(json.loads(row[0])) if row else []

    def read(self, image_id: str) -> bytes:
        with self.database.connection() as db:
            row = db.execute(
                "SELECT purpose,content FROM romance_images WHERE id=?", (image_id,)
            ).fetchone()
            if row is None:
                raise ValueError("图片不存在。")
            if row["purpose"] == "moment":
                owners = db.execute(
                    "SELECT * FROM memories WHERE user_id=? AND "
                    "EXISTS (SELECT 1 FROM json_each(metadata_json,'$.journal_images') "
                    "WHERE value=?)",
                    (self.user_id, image_id),
                ).fetchall()
                if owners and not any(
                    owner["status"] == "active"
                    and owner["consent"] == "granted"
                    and all(
                        self.store.get_turn(i, self.user_id).deletion_state
                        is TurnDeletionState.ACTIVE
                        and self.store.get_turn(i, self.user_id).consent is ConsentState.GRANTED
                        for i in json.loads(owner["evidence_turn_ids_json"])
                    )
                    for owner in owners
                ):
                    raise ValueError("此回忆图片已不可用。")
            if row["purpose"] == "chat":
                bindings = db.execute(
                    "SELECT conversation_id,request_id FROM romance_message_images "
                    "WHERE EXISTS (SELECT 1 FROM json_each(image_ids) WHERE value=?)",
                    (image_id,),
                ).fetchall()
                if bindings:
                    permitted = False
                    for binding in bindings:
                        source = db.execute(
                            "SELECT id FROM conversation_turns "
                            "WHERE user_id=? AND conversation_id=? AND idempotency_key=?",
                            (self.user_id, *binding),
                        ).fetchone()
                        if source and visible(self.store.get_turn(source[0], self.user_id)):
                            permitted = True
                    if not permitted:
                        raise ValueError("此图片所属消息已不可用。")
            return bytes(row["content"])

    def discard(self, image_id: str, protected: set[str]) -> None:
        with self.database.connection() as db:
            used = db.execute(
                "SELECT 1 FROM romance_message_images, json_each(image_ids) WHERE value=?",
                (image_id,),
            ).fetchone()
            used = (
                used
                or db.execute(
                    "SELECT 1 FROM memories,json_each(metadata_json,'$.journal_images') "
                    "WHERE value=? AND status='active'",
                    (image_id,),
                ).fetchone()
            )
            if used or image_id in protected:
                raise ValueError("图片仍在使用中。")
            db.execute("DELETE FROM romance_images WHERE id=?", (image_id,))

    def prune_drafts(self, protected: set[str]) -> None:
        """A restarted client has no pending picker or composer; discard abandoned imports."""
        with self.database.connection() as db:
            used = {
                row[0]
                for row in db.execute(
                    "SELECT value FROM romance_message_images, json_each(image_ids)"
                )
            } | protected
            used.update(
                row[0]
                for row in db.execute(
                    "SELECT value FROM memories,json_each(metadata_json,'$.journal_images') "
                    "WHERE status='active' AND consent='granted'",
                )
            )
            for row in db.execute("SELECT id FROM romance_images").fetchall():
                if row[0] not in used:
                    db.execute("DELETE FROM romance_images WHERE id=?", (row[0],))


class ImageAwareModel:
    def __init__(self, model: MainLLM, images: ImageStore, enabled: bool) -> None:
        self.model, self.images, self.enabled = model, images, enabled

    def generate(self, messages: list[ChatMessage]) -> ModelResponse:
        remaining = MAX_IMAGES
        result: list[ChatMessage] = []
        for message in reversed(messages):
            copy = message.model_copy(deep=True)
            if message.role == "user" and message.source_turn_id:
                turn = self.images.store.get_turn(message.source_turn_id, self.images.user_id)
                ids = self.images.ids(turn)
                if ids and self.enabled:
                    selected = ids[:remaining]
                    copy.image_urls = [
                        "data:image/png;base64,"
                        + base64.b64encode(self.images.read(i)).decode("ascii")
                        for i in selected
                    ]
                    remaining -= len(selected)
                    if len(selected) != len(ids):
                        copy.content += "\n[部分历史图片本轮未附带，不能据此描述图片内容。]"
                elif ids:
                    copy.content += "\n[本轮未启用识图，图片内容不可见。]"
            copy.source_turn_id = None
            result.append(copy)
        return self.model.generate(list(reversed(result)))
