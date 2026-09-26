"""Loopback-only web host for the romantic companion. Run with companion-romance."""

from __future__ import annotations

import argparse
import json
import logging
import os
import secrets
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from threading import RLock
from typing import TYPE_CHECKING, Annotated, Any
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from companion_agent import chat_search
from companion_agent.automation.hub import ToolHub
from companion_agent.automation.loop import AgentLoop, RunContext
from companion_agent.automation.models import AutomationConfig, ScheduleInput
from companion_agent.channels import ChannelConfig, Channels, IncomingMessage
from companion_agent.chat_experience import ChatExperience
from companion_agent.chat_experience import install_routes as install_chat_experience_routes
from companion_agent.cognition import ApplicationMemory
from companion_agent.context import ChatMessage
from companion_agent.continuity import Continuity
from companion_agent.credentials import CredentialStore, CredentialStoreError
from companion_agent.deepseek import DeepSeekConfig, DeepSeekLLM
from companion_agent.directives import directive_recall
from companion_agent.images import MAX_IMAGE_BYTES, ImageAwareModel, ImagePurpose, ImageStore
from companion_agent.journal import Journal, JournalError
from companion_agent.journal import install_routes as install_journal_routes
from companion_agent.llm import MainLLM, MainLLMError
from companion_agent.offline import OfflineModel
from companion_agent.outreach import Outreach
from companion_agent.persona.models import PersonaModel
from companion_agent.relationship import RelationshipKey
from companion_agent.romance import (
    RomanceSettings,
    SettingsUpdate,
    romantic_persona,
    romantic_rules,
)
from companion_agent.runtime import CompanionAgent
from companion_agent.semantics import RelationshipIdentityType
from companion_agent.stickers import MAX_STICKER_BYTES, StickerModel, StickerStore
from companion_memoryos.config import load_config
from companion_memoryos.database import Database
from companion_memoryos.schemas import (
    ConsentState,
    ConversationRole,
    ConversationTurnInput,
    ConversationTurnRecord,
    MemoryCorrectionRequest,
    MemoryKind,
    MemoryScope,
    MemoryStatus,
    ProcessTurnRequest,
    ReviewDecision,
    TurnDeletionState,
)
from companion_memoryos.store import MemoryStore

logger = logging.getLogger(__name__)
if TYPE_CHECKING:
    from companion_agent.testing.control import TestControl
LOCAL_USER = "romance-user"
LOCAL_COMPANION = "romance-companion"
LOCAL_RELATIONSHIP = "romance-relationship"
COOKIE = "companion_romance_session"
DEFAULT_PORT = 8765
MAX_BODY_BYTES = 32_768
MODEL_ERRORS = {
    "main_llm_api_key_missing": "请先在设置中填写 DeepSeek API Key，或设置 DEEPSEEK_API_KEY。",
    "main_llm_cancelled": "本轮已停止，尚未完成的回复没有写入历史。",
    "main_llm_auth_failed": "API Key 无效或已过期，请检查后重试。",
    "main_llm_insufficient_balance": "DeepSeek 账户余额不足，请在服务商控制台检查。",
    "main_llm_access_denied": "当前 API Key 没有访问此模型的权限。",
    "main_llm_rate_limited": "DeepSeek 请求过于频繁，请稍后点击重试。",
    "main_llm_timeout": "模型响应超时，你的话已保留，可以稍后重试。",
    "main_llm_unavailable": "暂时无法连接模型服务，请检查网络和 API 地址。",
    "main_llm_http_error": "模型服务拒绝了请求，请检查模型名称、API 地址和服务状态。",
    "main_llm_incomplete_output": "模型回复未完整生成，可以增加输出上限或关闭思考模式后重试。",
    "main_llm_non_text_output": "模型没有返回可显示的文字，请重试。",
    "main_llm_invalid_output": "模型返回格式不正确，请检查接口是否兼容 DeepSeek。",
    "main_llm_response_too_large": "模型返回内容过大，请降低输出上限后重试。",
}


def problem(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, detail={"code": code, "message": message})


class ChatInput(PersonaModel):
    conversation_id: str = Field(min_length=1, max_length=128)
    request_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    content: str = Field(default="", max_length=6000)
    quote_id: str | None = Field(default=None, min_length=1, max_length=240)
    image_ids: list[Annotated[str, Field(pattern=r"^[a-f0-9]{32}$")]] = Field(
        default_factory=list, max_length=4
    )


class MemoryEdit(PersonaModel):
    content: str = Field(min_length=1, max_length=2000)
    request_id: str = Field(default_factory=lambda: str(uuid4()), max_length=128)
    conversation_id: str | None = Field(default=None, max_length=128)


class EventUpdate(PersonaModel):
    status: str
    due_at: datetime | None = None


def public_turn(turn: ConversationTurnRecord) -> dict[str, Any]:
    return {
        "id": turn.id,
        "role": turn.role.value,
        "content": turn.content,
        "created_at": turn.occurred_at.isoformat(),
        "sequence": turn.server_sequence,
        "request_id": turn.idempotency_key
        if turn.role.value == "user" and turn.source_ref != "memory:manual_correction"
        else None,
        "reply_to": turn.reply_to_turn_id,
    }


class RomanceHost:
    def __init__(
        self,
        data_dir: Path,
        llm: MainLLM | None = None,
        *,
        testing: TestControl | None = None,
        credentials: CredentialStore | None = None,
    ) -> None:
        self.testing = testing
        config = load_config()
        config = config.model_copy(
            update={
                "discourse": config.discourse.model_copy(
                    update={
                        "memory_question_phrases": [
                            *config.discourse.memory_question_phrases,
                            "还记得我",
                            "我喜欢什么",
                            "我爱喝什么",
                            "我叫什么",
                            "怎么称呼我",
                            "我的名字",
                            "我的昵称",
                        ],
                    }
                )
            }
        )
        database = Database(data_dir, config)
        database.initialize()
        self.memory = ApplicationMemory(MemoryStore(database), config)
        if testing:
            self.memory.on_memory_changed = testing.invalidate
        self.database = database
        self.images = ImageStore(database, self.memory.store, LOCAL_USER)
        self.memory.store.repair_empty_redactions(LOCAL_USER)
        self.lock = RLock()
        self.session = secrets.token_urlsafe(32)
        self.api_key: str | None = None
        self.credential_store = credentials or CredentialStore(data_dir, enabled=testing is None)
        self.key_persisted = False
        self.credential_store_error = False
        self.injected_llm = llm
        self.key = RelationshipKey(
            user_id=LOCAL_USER, companion_id=LOCAL_COMPANION, relationship_id=LOCAL_RELATIONSHIP
        )
        with database.connection() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS romance_settings "
                "(id INTEGER PRIMARY KEY CHECK (id=1), data_json TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS romance_conversations "
                "(id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL, "
                "updated_at TEXT NOT NULL)"
            )
            saved = connection.execute(
                "SELECT data_json FROM romance_settings WHERE id=1"
            ).fetchone()
            connection.execute(
                "CREATE TABLE IF NOT EXISTS agent_checkpoints (action_id TEXT PRIMARY KEY, "
                "source_turn TEXT NOT NULL, state TEXT NOT NULL, status TEXT NOT NULL)"
            )
            connection.execute(
                "UPDATE agent_checkpoints SET status='retryable' WHERE status='resuming'"
            )
        self.settings = (
            RomanceSettings.model_validate_json(saved["data_json"])
            if saved
            else RomanceSettings(
                deepseek=DeepSeekConfig(
                    model=os.environ.get("DEEPSEEK_MODEL", "deepseek-flash"),
                    base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
                )
            )
        )
        try:
            self.api_key = self.credential_store.load(self.settings.deepseek.base_url)
            self.key_persisted = self.api_key is not None
        except CredentialStoreError:
            self.credential_store_error = True
        self.chat_experience = ChatExperience(self)
        self.images.prune_drafts(
            {
                image_id
                for image_id in (
                    self.settings.background_image,
                    self.settings.user_avatar,
                    self.settings.companion_avatar,
                )
                if image_id
            }
            | self.chat_experience.protected_images()
        )
        self.tools = ToolHub(database)
        self.tools.available = lambda: self.settings.storage_consent
        self.stickers = StickerStore(database)
        self.agent = self.make_agent(self.settings, self.api_key)
        self.continuity = Continuity(self)
        self.journal = Journal(self)
        self.outreach = Outreach(self)
        self.memory.on_user_turn = self.continuity.observe
        self.channels = Channels(self)
        self.tools.scheduler.on_tick = self.continuity.tick
        if not self.conversations():
            self.new_conversation()
        if testing:
            testing.allowed.update(item["id"] for item in self.conversations())

    @staticmethod
    def resolved_key(settings: RomanceSettings, api_key: str | None) -> str | None:
        if api_key:
            return api_key
        # A saved custom endpoint cannot receive a different provider's environment key
        # after restart. Environment credentials require an explicitly matching endpoint.
        environment_endpoint = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        if settings.deepseek.base_url == environment_endpoint.rstrip("/"):
            return os.environ.get(settings.deepseek.api_key_env)
        return None

    def make_agent(self, settings: RomanceSettings, api_key: str | None) -> CompanionAgent:
        if self.testing:
            if settings.model_mode == "api" and not self.testing.marker["allow_live"]:
                raise problem(403, "test_live_not_authorized", "此测试实例未授权真实模型调用。")
            if (
                settings.cognition.embedding_backend == "api"
                and not self.testing.allows_local_embedding(settings.cognition.embedding.base_url)
            ):
                raise problem(
                    403, "test_embedding_not_authorized", "此测试实例未授权该向量服务地址。"
                )
            resolved = self.resolved_key(settings, api_key)
            if resolved:
                self.testing.secrets.append(resolved)
        self.memory.configure(
            settings.cognition,
            offline=settings.model_mode == "offline",
            model=settings.deepseek,
            key=self.resolved_key(settings, api_key),
        )
        self.loop = AgentLoop(
            self.injected_llm
            or (
                OfflineModel()
                if settings.model_mode == "offline"
                else DeepSeekLLM(
                    settings.deepseek,
                    api_key=self.resolved_key(settings, api_key),
                    use_environment=False,
                )
            ),
            self.tools,
        )
        self.loop.on_pending = self.persist_suspension
        return CompanionAgent(
            self.memory,
            romantic_persona(settings),
            StickerModel(
                ImageAwareModel(self.loop, self.images, settings.vision_ready),
                self.stickers,
                settings.stickers_enabled,
            ),
            application_rules=romantic_rules(settings),
            max_persona_tokens=1600,
            context_variant=self.testing.marker.get("variant", "full") if self.testing else "full",
            initial_relationship_identity=(
                RelationshipIdentityType.ROMANTIC_PARTNER
                if settings.romance_consent
                else RelationshipIdentityType.COMPANION
            ),
        )

    @contextmanager
    def exclusive(self) -> Iterator[None]:
        if not self.lock.acquire(blocking=False):
            raise problem(409, "busy", "正在回复上一条消息，请等回复完成后再操作。")
        try:
            yield
        finally:
            self.lock.release()

    def credentials_ready(self) -> bool:
        return bool(
            self.settings.model_mode == "offline"
            or self.injected_llm
            or self.resolved_key(self.settings, self.api_key)
        )

    def public_settings(self) -> dict[str, Any]:
        return {
            "settings": self.settings.model_dump(mode="json"),
            "model_ready": self.credentials_ready(),
            "vision_ready": self.settings.vision_ready,
            "chat_features": True,
            "journal_features": True,
            "chat_experience": True,
            "last_conversation": self.chat_experience.last_conversation(),
            "journal_background": self.outreach.background_enabled(),
            "key_configured": bool(
                self.injected_llm or self.resolved_key(self.settings, self.api_key)
            ),
            "embedding_status": self.memory.embedding_status,
            "embedding_backend": self.memory.embeddings.backend,
            "credential_persistence_supported": self.credential_store.available,
            "credential_store_error": self.credential_store_error,
            "key_persisted": self.key_persisted,
            "key_source": ("credential_store" if self.key_persisted else "session")
            if self.api_key
            else ("environment" if self.resolved_key(self.settings, self.api_key) else "missing"),
        }

    def conversations(self) -> list[dict[str, Any]]:
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM romance_conversations ORDER BY updated_at DESC, rowid DESC"
            ).fetchall()
        counts: dict[str, int] = {}
        for turn in self.outreach.unread():
            cid = turn.scope.conversation_id or ""
            counts[cid] = counts.get(cid, 0) + 1
        return [dict(row, unread=counts.get(row["id"], 0)) for row in rows]

    def new_conversation(self) -> dict[str, str]:
        now = datetime.now(UTC).isoformat()
        item = {"id": str(uuid4()), "title": "新的对话", "created_at": now, "updated_at": now}
        with self.database.connection() as connection:
            connection.execute(
                "INSERT INTO romance_conversations VALUES (?, ?, ?, ?)", tuple(item.values())
            )
        if self.testing:
            self.testing.allowed.add(item["id"])
        return item

    def scope(self, conversation_id: str) -> MemoryScope:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT id FROM romance_conversations WHERE id=?", (conversation_id,)
            ).fetchone()
        if row is None:
            raise problem(404, "conversation_missing", "这段对话不存在。")
        return MemoryScope(
            companion_id=LOCAL_COMPANION,
            relationship_id=LOCAL_RELATIONSHIP,
            conversation_id=conversation_id,
        )

    def save_settings(self, update: SettingsUpdate) -> dict[str, Any]:
        with self.exclusive():
            for field, purpose in (
                ("background_image", "background"),
                ("user_avatar", "user_avatar"),
                ("companion_avatar", "companion_avatar"),
            ):
                image_id = getattr(update.settings, field)
                if image_id:
                    self.images.require(image_id, purpose)
            before = self.settings
            proposed_key = None if update.clear_api_key else self.api_key
            if update.api_key is not None:
                proposed_key = update.api_key.get_secret_value()
            # An old credential must never silently follow a new provider endpoint.
            endpoint_changed = before.deepseek.base_url != update.settings.deepseek.base_url
            if endpoint_changed and update.api_key is None:
                proposed_key = None
            if (
                endpoint_changed
                and update.settings.deepseek.base_url != "https://api.deepseek.com"
                and update.api_key is None
            ):
                raise problem(
                    400, "endpoint_key_required", "更换 API 地址时请重新输入该服务的 Key。"
                )
            remember = (
                update.remember_api_key
                if update.remember_api_key is not None
                else self.key_persisted and not endpoint_changed
            ) and not update.clear_api_key
            if remember:
                if not self.credential_store.available:
                    raise problem(400, "credential_store_unavailable", "此环境不支持安全保存 Key。")
                proposed_key = self.resolved_key(update.settings, proposed_key)
                if not proposed_key:
                    raise problem(400, "key_required", "请先填写需要记住的 Key。")
            try:
                if remember and proposed_key:
                    self.credential_store.save(update.settings.deepseek.base_url, proposed_key)
                elif self.credential_store.available and (
                    update.clear_api_key or update.remember_api_key is False
                ):
                    self.credential_store.delete(before.deepseek.base_url)
            except CredentialStoreError:
                raise problem(
                    503, "credential_store_failed", "系统凭据管理器操作失败，设置尚未保存。"
                ) from None
            candidate = self.make_agent(update.settings, proposed_key)
            with self.database.atomic() as connection:
                connection.execute(
                    "INSERT INTO romance_settings VALUES (1, ?) "
                    "ON CONFLICT(id) DO UPDATE SET data_json=excluded.data_json",
                    (update.settings.model_dump_json(),),
                )
                if update.settings.storage_consent and (
                    not before.storage_consent
                    or before.romance_consent != update.settings.romance_consent
                ):
                    candidate.relationships.initialize_identity(
                        self.key,
                        RelationshipIdentityType.ROMANTIC_PARTNER
                        if update.settings.romance_consent
                        else RelationshipIdentityType.COMPANION,
                        description="用户在陪伴设置中选择关系身份："
                        + datetime.now(UTC).isoformat(),
                    )
            self.settings = update.settings.model_copy(deep=True)
            if not self.settings.storage_consent:
                self.chat_experience.clear_private_ui()
            self.api_key = proposed_key
            self.key_persisted = bool(remember and proposed_key)
            self.credential_store_error = False
            self.agent = candidate
            protected = {
                image_id
                for image_id in (
                    self.settings.background_image,
                    self.settings.user_avatar,
                    self.settings.companion_avatar,
                )
                if image_id
            }
            for previous_image in (
                before.background_image,
                before.user_avatar,
                before.companion_avatar,
            ):
                if previous_image and previous_image not in protected:
                    self.images.discard(previous_image, protected)
            return self.public_settings()

    def chat(self, item: ChatInput) -> dict[str, Any]:
        if self.testing:
            with self.testing.turn(item) as trace:
                result = self._chat(item)
                result["trace_id"] = trace["trace_id"]
                self.testing.event("result", result)
                return result
        return self._chat(item)

    def _chat(self, item: ChatInput) -> dict[str, Any]:
        with self.exclusive():
            scope = self.scope(item.conversation_id)
            if not item.content.strip() and not item.image_ids:
                raise problem(422, "empty_message", "请输入消息。")
            if not self.settings.storage_consent or not self.settings.model_consent:
                raise problem(403, "consent_required", "请先在设置中确认本地保存与模型调用授权。")
            if not self.credentials_ready():
                raise MainLLMError("main_llm_api_key_missing")
            if item.quote_id:
                self.journal.require_turn(item.quote_id, item.conversation_id, for_model=True)
            with self.database.connection() as db:
                previous = db.execute(
                    "SELECT reply_to_turn_id FROM conversation_turns WHERE user_id=? "
                    "AND conversation_id=? AND idempotency_key=? AND role='user'",
                    (LOCAL_USER, item.conversation_id, item.request_id),
                ).fetchone()
                if previous is not None and previous[0] != item.quote_id:
                    raise problem(409, "quote_changed", "重试时引用的消息必须与原消息一致。")
            if item.image_ids and not self.settings.vision_ready:
                raise problem(
                    422,
                    "vision_unavailable",
                    "请在连接设置中启用支持图片的在线模型；离线模式不能识图。",
                )
            self.images.bind(item.conversation_id, item.request_id, item.image_ids)
            item = item.model_copy(update={"content": item.content.strip() or "[图片]"})
            with self.database.connection() as db:
                checkpoint = db.execute(
                    "SELECT c.state FROM agent_checkpoints c JOIN conversation_turns t "
                    "ON t.id=c.source_turn WHERE t.user_id=? AND t.conversation_id=? "
                    "AND t.idempotency_key=? AND c.status IN ('pending','retryable') "
                    "ORDER BY c.rowid DESC LIMIT 1",
                    (LOCAL_USER, item.conversation_id, item.request_id),
                ).fetchone()
            with self.loop.run(
                item.conversation_id,
                item.request_id,
                json.loads(checkpoint["state"]) if checkpoint else None,
            ) as run:
                result = self.agent.chat(
                    ProcessTurnRequest(
                        user_id=LOCAL_USER,
                        scope=scope,
                        content=item.content,
                        reply_to_turn_id=item.quote_id,
                        idempotency_key=item.request_id,
                        consent=ConsentState.GRANTED,
                        model_consent=ConsentState.GRANTED,
                        calendar_timezone=self.settings.calendar_timezone,
                        recall_request=directive_recall(LOCAL_USER, scope, item.content),
                    )
                )
            source = self.memory.store.get_turn(result.turn.reply_to_turn_id or "", LOCAL_USER)
            with self.database.atomic() as connection:
                if not result.reused:
                    self.save_checkpoint(run, source.id)
                connection.execute(
                    "UPDATE romance_conversations SET title=CASE WHEN title='新的对话' "
                    "THEN ? ELSE title END, updated_at=? WHERE id=?",
                    (
                        item.content.strip()[:24],
                        datetime.now(UTC).isoformat(),
                        item.conversation_id,
                    ),
                )
            return {
                "user": self.public_turn(source),
                "assistant": self.public_turn(result.turn),
                "reused": result.reused,
                "execution": {
                    "steps": run.steps,
                    "tool_calls": run.tool_calls,
                    "status": run.status,
                },
            }

    def public_turn(self, turn: ConversationTurnRecord) -> dict[str, Any]:
        return {
            **public_turn(turn),
            "image_ids": self.images.ids(turn),
            "sticker": self.stickers.describe(turn.metadata.get("sticker_id")),
            "quote": self.journal.quote(turn),
            "notice": bool(turn.metadata.get("journal_reminder")),
            "bookmarked": self.chat_experience.contains(turn.id),
        }

    def save_checkpoint(self, run: RunContext, source: str) -> None:
        if run.pending_action:
            with self.database.connection() as db:
                db.execute(
                    "INSERT INTO agent_checkpoints VALUES (?, ?, ?, 'pending') "
                    "ON CONFLICT(action_id) DO UPDATE SET state=excluded.state "
                    "WHERE agent_checkpoints.status='pending'",
                    (
                        run.pending_action,
                        source,
                        json.dumps(
                            {
                                "steps": run.steps,
                                "tool_calls": run.tool_calls,
                                "tokens": run.tokens,
                                "elapsed": run.elapsed,
                            }
                        ),
                    ),
                )

    def persist_suspension(self, run: RunContext) -> None:
        for source in self.memory.list_turns(LOCAL_USER, self.scope(run.conversation)):
            if source.role is ConversationRole.USER and source.idempotency_key == run.request_id:
                self.save_checkpoint(run, source.id)
                return
        raise ValueError("suspended action has no source turn")

    def checkpoint_source(
        self, action_id: str
    ) -> tuple[dict[str, Any], ConversationTurnRecord] | None:
        with self.database.connection() as db:
            row = db.execute(
                "SELECT * FROM agent_checkpoints WHERE action_id=?", (action_id,)
            ).fetchone()
        if row is None:
            return None
        source = self.memory.store.get_turn(row["source_turn"], LOCAL_USER)
        if (
            source.deletion_state is not TurnDeletionState.ACTIVE
            or source.consent is not ConsentState.GRANTED
        ):
            raise ValueError("source invalidated")
        if any(
            turn.role is ConversationRole.USER
            and turn.server_sequence > source.server_sequence
            and turn.deletion_state is TurnDeletionState.ACTIVE
            for turn in self.memory.list_turns(LOCAL_USER, source.scope)
        ):
            raise problem(409, "stale_action", "对话已有新的指示，请拒绝旧操作后重新发起。")
        return dict(row), source

    def decide_action(self, action_id: str, approved: bool) -> dict[str, Any]:
        with self.exclusive():
            if approved:
                self.checkpoint_source(action_id)
            result = self.tools.approve(action_id, approved)
            if approved and result["status"] == "succeeded":
                try:
                    result["continuation"] = self.resume(action_id)
                except (MainLLMError, ValueError):
                    result["continuation_error"] = (
                        "操作已执行；回复暂未完成，可点击继续回复，不会重做该操作。"
                    )
            else:
                with self.database.connection() as db:
                    db.execute(
                        "UPDATE agent_checkpoints SET status='stopped' WHERE action_id=?",
                        (action_id,),
                    )
            return result

    def resume(self, action_id: str) -> dict[str, Any] | None:
        with self.exclusive():
            found = self.checkpoint_source(action_id)
            if found is None:
                return None
            row, source = found
            if source.idempotency_key is None:
                raise ValueError("source has no delivery key")
            if row["status"] not in {"pending", "retryable", "resumed"}:
                raise ValueError("continuation not resumable")
            if not self.settings.storage_consent or not self.settings.model_consent:
                raise ValueError("consent revoked")
            with self.database.connection() as db:
                action = db.execute(
                    "SELECT status FROM agent_actions WHERE id=?", (action_id,)
                ).fetchone()
                if action is None or action["status"] != "succeeded":
                    raise ValueError("only successful actions can resume")
                db.execute(
                    "UPDATE agent_checkpoints SET status='resuming' WHERE action_id=?", (action_id,)
                )
            try:
                with self.loop.run(
                    source.scope.conversation_id or "",
                    source.idempotency_key,
                    json.loads(row["state"]),
                ) as run:
                    result = self.agent.chat(
                        ProcessTurnRequest(
                            user_id=LOCAL_USER,
                            scope=source.scope,
                            content=source.content,
                            idempotency_key=source.idempotency_key,
                            consent=ConsentState.GRANTED,
                            model_consent=ConsentState.GRANTED,
                            calendar_timezone=self.settings.calendar_timezone,
                            recall_request=directive_recall(
                                LOCAL_USER, source.scope, source.content
                            ),
                        ),
                        continuation_key=action_id,
                    )
                with self.database.atomic() as db:
                    self.save_checkpoint(run, source.id)
                    db.execute(
                        "UPDATE agent_checkpoints SET status='resumed' WHERE action_id=?",
                        (action_id,),
                    )
                return {
                    "assistant": self.public_turn(result.turn),
                    "reused": result.reused,
                    "execution": {
                        "status": run.status,
                        "steps": run.steps,
                        "tool_calls": run.tool_calls,
                    },
                }
            except Exception:
                with self.database.connection() as db:
                    db.execute(
                        "UPDATE agent_checkpoints SET status='retryable', state=? "
                        "WHERE action_id=?",
                        (
                            json.dumps(
                                {
                                    "steps": run.steps,
                                    "tool_calls": run.tool_calls,
                                    "tokens": run.tokens,
                                    "elapsed": run.elapsed,
                                }
                            ),
                            action_id,
                        ),
                    )
                raise

    def memories(self, conversation_id: str) -> dict[str, Any]:
        scope = self.scope(conversation_id)
        relationship = self.agent.relationships.evaluate_stage(self.key)
        memories = self.memory.store.list_memories(
            LOCAL_USER, {MemoryStatus.ACTIVE}, scope=scope, limit=100
        )
        states = (
            self.agent.current_states.snapshot(self.key, conversation_id)
            if self.agent.current_states
            else []
        )
        experiences = self.agent.experiences.list_experiences(self.key)
        return {
            "relationship": relationship.model_dump(mode="json"),
            "memories": [record.model_dump(mode="json") for record in memories],
            # Internal uncertain proposals are not a queue of tasks for the user.
            "candidates": [],
            "events": self.continuity.events(conversation_id),
            "states": [record.model_dump(mode="json") for record in states],
            "experiences": [record.model_dump(mode="json") for record in experiences[:30]],
        }


def create_app(
    data_dir: Path | str = ".agent-data/romance",
    *,
    llm: MainLLM | None = None,
    testing: TestControl | None = None,
    client_token: str | None = None,
    credentials: CredentialStore | None = None,
    background_services: bool = True,
) -> FastAPI:
    if testing and Path(data_dir).resolve() != testing.directory / "data":
        raise ValueError("testing requires the owned run's isolated data directory")
    host = RomanceHost(Path(data_dir), llm, testing=testing, credentials=credentials)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if testing is None and background_services:
            host.tools.scheduler.start()
            host.channels.start()
        try:
            yield
        finally:
            host.tools.scheduler.stop()
            host.channels.stop()

    app = FastAPI(
        title="心隅 · AI 恋爱陪伴",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.host = host
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]"])
    static = Path(str(files("companion_agent").joinpath("web")))

    @app.middleware("http")
    async def local_security(request: Request, call_next: Any) -> Response:
        # Native apps receive this ephemeral secret through their private launch
        # channel. Other apps on the same device must not obtain a session at /.
        if client_token is not None and not secrets.compare_digest(
            request.headers.get("x-xinyu-token", ""), client_token
        ):
            return JSONResponse({"detail": {"message": "本机应用凭证无效，请重新启动。"}}, 401)
        if (
            (testing or not background_services)
            and request.method in {"POST", "PUT", "PATCH", "DELETE"}
            and (
                request.url.path.startswith("/api/channels")
                or (
                    request.url.path.startswith("/api/automation/")
                    and not request.url.path.startswith("/api/automation/cancel/")
                )
                or request.url.path == "/api/connection"
            )
        ):
            return JSONResponse({"detail": {"message": "此运行环境未启用外部工具和渠道。"}}, 403)
        origin = request.headers.get("origin")
        expected = str(request.base_url).rstrip("/")
        if origin and origin != expected:
            return JSONResponse({"detail": {"message": "不允许跨站请求。"}}, status_code=403)
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            if (
                client_token is not None
                and (host.database.data_dir / "restore-pending.sqlite").exists()
            ):
                return JSONResponse(
                    {"detail": {"message": "备份已准备好，请重启应用完成恢复。"}}, 409
                )
            if request.headers.get("x-companion-client") != "local-web":
                return JSONResponse(
                    {"detail": {"message": "缺少本地客户端标识。"}}, status_code=403
                )
            # Limit the actual body, including requests without Content-Length.
            limit = MAX_BODY_BYTES
            if request.url.path == "/api/settings":
                limit = 131_072
            if request.url.path == "/api/images":
                limit = MAX_IMAGE_BYTES
            if request.url.path == "/api/stickers":
                limit = MAX_STICKER_BYTES
            if client_token is not None and request.url.path == "/api/local/restore":
                from companion_agent.local_data import MAX_BACKUP_BYTES

                limit = MAX_BACKUP_BYTES
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > limit:
                    return JSONResponse({"detail": {"message": "请求内容过长。"}}, status_code=413)
            request._body = bytes(body)
        response: Response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        return response

    def authorized(request: Request) -> None:
        cookie = f"{COOKIE}_{request.url.port or 80}"
        if not secrets.compare_digest(request.cookies.get(cookie, ""), host.session):
            raise problem(401, "session_expired", "本地会话已失效，请刷新页面。")

    install_journal_routes(app, host, authorized)
    install_chat_experience_routes(app, host, authorized)

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request: Request, error: RequestValidationError) -> JSONResponse:
        # Pydantic errors can contain the submitted Key. Never echo inputs or exception text.
        fields = [".".join(str(part) for part in item["loc"]) for item in error.errors()]
        return JSONResponse(
            {
                "detail": {
                    "code": "invalid_input",
                    "message": "设置或消息格式不正确，请检查填写内容。",
                    "fields": fields,
                }
            },
            status_code=422,
        )

    @app.exception_handler(MainLLMError)
    async def model_error(request: Request, error: MainLLMError) -> JSONResponse:
        code = str(error)
        return JSONResponse(
            {
                "detail": {
                    "code": code,
                    "message": MODEL_ERRORS.get(code, "模型暂时不可用，请稍后重试。"),
                }
            },
            status_code=502,
        )

    @app.exception_handler(ValueError)
    async def state_error(request: Request, error: ValueError) -> JSONResponse:
        logger.warning("romance_request_state_conflict")
        return JSONResponse(
            {"detail": {"code": "state_conflict", "message": "本轮状态发生变化，请刷新后重试。"}},
            status_code=409,
        )

    @app.get("/")
    def index(request: Request) -> FileResponse:
        response = FileResponse(static / "index.html")
        # Cookies ignore ports; separate local instances must not overwrite each other.
        cookie = f"{COOKIE}_{request.url.port or 80}"
        response.set_cookie(cookie, host.session, httponly=True, samesite="strict")
        return response

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "app": "companion-romance"}

    @app.get("/api/bootstrap", dependencies=[Depends(authorized)])
    def bootstrap() -> dict[str, Any]:
        with host.lock:
            return {**host.public_settings(), "conversations": host.conversations()}

    @app.put("/api/settings", dependencies=[Depends(authorized)])
    def settings(update: SettingsUpdate) -> dict[str, Any]:
        return host.save_settings(update)

    @app.get("/api/search", dependencies=[Depends(authorized)])
    def search_chats(
        query: str = Query(min_length=1, max_length=100),
        conversation_id: str | None = None,
        before: int | None = Query(default=None, ge=1),
        limit: int = Query(default=30, ge=1, le=50),
    ) -> dict[str, Any]:
        with host.lock:
            return chat_search.search(host, query, conversation_id, before, limit)

    @app.get("/api/updates", dependencies=[Depends(authorized)])
    def updates() -> dict[str, Any]:
        with host.lock:
            host.journal.tick_reminders()
            return {
                "conversations": host.conversations(),
                "outreach": host.outreach.state(),
                "proactive_enabled": host.outreach.enabled(),
                "background_enabled": host.outreach.background_enabled(),
                "notification_conversations": list(
                    {t.scope.conversation_id for t in host.outreach.unread()}
                ),
            }

    @app.post("/api/conversations/{conversation_id}/read", dependencies=[Depends(authorized)])
    def mark_read(conversation_id: str, through: int = Query(ge=0)) -> dict[str, bool]:
        with host.lock:
            host.outreach.unread()
            host.outreach.read(conversation_id, through)
        return {"ok": True}

    @app.get(
        "/api/conversations/{conversation_id}/context/{identifier}",
        dependencies=[Depends(authorized)],
    )
    def search_context(conversation_id: str, identifier: str) -> dict[str, Any]:
        with host.lock:
            return chat_search.context(host, conversation_id, identifier)

    @app.get("/api/stickers", dependencies=[Depends(authorized)])
    def stickers() -> dict[str, Any]:
        with host.lock:
            return {"stickers": host.stickers.catalog()}

    @app.post("/api/stickers", dependencies=[Depends(authorized)])
    async def upload_sticker(request: Request, label: str = Query(max_length=32)) -> dict[str, str]:
        content = await request.body()
        with host.exclusive():
            try:
                return host.stickers.upload(content, label)
            except ValueError as error:
                raise problem(422, "invalid_sticker", str(error)) from None

    @app.get("/api/stickers/{identifier}/content", dependencies=[Depends(authorized)])
    def sticker_content(identifier: str) -> Response:
        with host.lock:
            try:
                content, mime = host.stickers.read(identifier)
                return Response(content, media_type=mime)
            except KeyError:
                raise problem(404, "sticker_missing", "表情包已删除。") from None

    @app.delete("/api/stickers/{identifier}", dependencies=[Depends(authorized)])
    def delete_sticker(identifier: str) -> dict[str, bool]:
        with host.exclusive():
            host.stickers.delete(identifier)
        return {"ok": True}

    @app.post("/api/images", dependencies=[Depends(authorized)])
    async def upload_image(request: Request, purpose: ImagePurpose) -> dict[str, Any]:
        content = await request.body()
        with host.exclusive():
            if purpose == "chat" and not host.settings.storage_consent:
                raise problem(403, "consent_required", "请先允许本地保存聊天。")
            try:
                return host.images.upload(purpose, content)
            except ValueError as error:
                raise problem(422, "invalid_image", str(error)) from None

    @app.get("/api/images/{image_id}", dependencies=[Depends(authorized)])
    def get_image(image_id: str) -> Response:
        with host.lock:
            try:
                return Response(host.images.read(image_id), media_type="image/png")
            except ValueError:
                raise problem(404, "image_missing", "图片不可用。") from None

    @app.delete("/api/images/{image_id}", dependencies=[Depends(authorized)])
    def discard_image(image_id: str) -> dict[str, bool]:
        with host.exclusive():
            protected = {
                value
                for value in (
                    host.settings.background_image,
                    host.settings.user_avatar,
                    host.settings.companion_avatar,
                )
                if value
            }
            host.images.discard(image_id, protected)
            return {"deleted": True}

    @app.post("/api/connection", dependencies=[Depends(authorized)])
    def check_connection() -> dict[str, str]:
        with host.exclusive():
            if not host.settings.model_consent:
                raise problem(403, "consent_required", "请先同意调用 DeepSeek 并保存设置。")
            model = host.agent.main_llm
            assert model is not None
            reply = model.generate([ChatMessage(role="user", content="请只回复：连接成功。")])
            return {
                "status": "ok",
                "model": reply.model,
                "message": "离线流程已验证，未调用真实模型。"
                if host.settings.model_mode == "offline"
                else "连接成功，可以开始聊天了。",
            }

    @app.post("/api/conversations", dependencies=[Depends(authorized)])
    def new_conversation() -> dict[str, str]:
        with host.exclusive():
            return host.new_conversation()

    @app.get("/api/conversations/{conversation_id}/messages", dependencies=[Depends(authorized)])
    def messages(
        conversation_id: str,
        before: Annotated[int | None, Query(ge=1)] = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 80,
    ) -> dict[str, Any]:
        with host.lock:
            turns = [
                turn
                for turn in host.memory.list_turns(LOCAL_USER, host.scope(conversation_id))
                if turn.deletion_state is TurnDeletionState.ACTIVE
                and turn.consent is ConsentState.GRANTED
                and (before is None or turn.server_sequence < before)
            ]
            page = turns[:limit]
            return {
                "messages": [host.public_turn(turn) for turn in reversed(page)],
                "has_more": len(turns) > limit,
            }

    @app.post("/api/chat", dependencies=[Depends(authorized)])
    def chat(item: ChatInput) -> dict[str, Any]:
        return host.chat(item)

    @app.post("/api/chat/stream", dependencies=[Depends(authorized)])
    async def chat_stream(item: ChatInput) -> Response:
        import asyncio
        from queue import SimpleQueue
        from threading import Thread

        from fastapi.responses import StreamingResponse

        from companion_agent.streaming import listener

        queue: SimpleQueue[dict[str, Any]] = SimpleQueue()

        def worker() -> None:
            token = listener.set(queue.put)
            try:
                queue.put({"type": "result", "result": host.chat(item)})
            except MainLLMError as error:
                queue.put(
                    {"type": "error", "message": MODEL_ERRORS.get(str(error), "模型暂未完成回复。")}
                )
            except JournalError as error:
                queue.put({"type": "error", "message": str(error)})
            except HTTPException as error:
                detail = error.detail
                queue.put(
                    {
                        "type": "error",
                        "message": detail.get("message", "请求未完成。")
                        if isinstance(detail, dict)
                        else "请求未完成。",
                    }
                )
            except Exception:
                queue.put({"type": "error", "message": "本轮状态发生变化，请刷新后重试。"})
            finally:
                listener.reset(token)
                queue.put({"type": "done"})

        async def events() -> AsyncIterator[str]:
            Thread(target=worker, name="companion-response", daemon=True).start()
            try:
                while True:
                    event = await asyncio.to_thread(queue.get)
                    yield json.dumps(event, ensure_ascii=False) + "\n"
                    if event["type"] == "done":
                        break
            finally:
                host.loop.cancel(item.request_id)

        return StreamingResponse(events(), media_type="application/x-ndjson")

    @app.get("/api/memories/{conversation_id}", dependencies=[Depends(authorized)])
    def memories(conversation_id: str) -> dict[str, Any]:
        with host.lock:
            return host.memories(conversation_id)

    @app.post("/api/memories/{memory_id}/{decision}", dependencies=[Depends(authorized)])
    def review_memory(memory_id: str, decision: str) -> dict[str, Any]:
        with host.exclusive():
            if decision == "forget":
                record = host.memory.forget(memory_id, LOCAL_USER)
            elif decision in {"confirm", "reject"}:
                with host.database.atomic() as db:
                    candidate = host.memory.store.get(memory_id, LOCAL_USER)
                    if decision == "confirm" and candidate.kind in {
                        MemoryKind.PREFERENCE,
                        MemoryKind.BOUNDARY,
                        MemoryKind.SUPPORT_STRATEGY,
                        MemoryKind.IDENTITY,
                    }:
                        db.execute(
                            "UPDATE memories SET conversation_id=NULL WHERE id=? AND user_id=?",
                            (memory_id, LOCAL_USER),
                        )
                    record = host.memory.review(memory_id, LOCAL_USER, ReviewDecision(decision))
            else:
                raise problem(422, "invalid_decision", "请选择确认、拒绝或遗忘。")
            return record.model_dump(mode="json")

    @app.put("/api/memories/{memory_id}", dependencies=[Depends(authorized)])
    def correct_memory(memory_id: str, item: MemoryEdit) -> dict[str, Any]:
        with host.exclusive():
            if testing:
                testing.invalidate()
            if not host.settings.storage_consent:
                raise problem(403, "consent_required", "请先允许本地保存。")
            record = host.memory.store.get(memory_id, LOCAL_USER)
            if record.metadata.get("journal_moment"):
                host.journal.require_memory(memory_id)
            conversation_id = item.conversation_id or host.conversations()[0]["id"]
            source_scope = host.scope(conversation_id)
            with host.database.atomic():
                source = host.memory.append_turn(
                    ConversationTurnInput(
                        user_id=LOCAL_USER,
                        scope=source_scope,
                        role=ConversationRole.USER,
                        actor_id=LOCAL_USER,
                        content=item.content,
                        consent=ConsentState.GRANTED,
                        idempotency_key="memory_edit:" + item.request_id,
                        source_ref="memory:manual_correction",
                        metadata={"reality_layer": record.reality_layer.value}
                        if record.metadata.get("journal_moment")
                        else {},
                    )
                ).turn
                assert source is not None
                if record.stable_key is None:
                    # Give legacy free-form memories a stable revision identity on user edit.
                    with host.database.connection() as db:
                        db.execute(
                            "UPDATE memories SET stable_key=? WHERE id=? AND user_id=?",
                            ("manual:" + record.id, record.id, LOCAL_USER),
                        )
                result = host.memory.correct(
                    memory_id,
                    MemoryCorrectionRequest(
                        user_id=LOCAL_USER,
                        content=item.content,
                        consent=ConsentState.GRANTED,
                        evidence_turn_ids=list(
                            dict.fromkeys(
                                [
                                    source.id,
                                    *(
                                        record.evidence_turn_ids
                                        if record.metadata.get("journal_moment")
                                        else []
                                    ),
                                ]
                            )
                        ),
                        source_excerpt=item.content,
                    ),
                )
            return result.model_dump(mode="json")

    @app.put("/api/events/{event_id}", dependencies=[Depends(authorized)])
    def update_event(event_id: str, item: EventUpdate) -> dict[str, bool]:
        with host.exclusive():
            with host.database.connection() as db:
                manual = db.execute(
                    "SELECT 1 FROM journal_event_details WHERE id=?", (event_id,)
                ).fetchone()
            if item.status in {"cancelled", "resolved"} and manual:
                host.journal.close_event(event_id, item.status)
            else:
                host.continuity.change(event_id, item.status, due=item.due_at)
        return {"saved": True}

    @app.get("/api/channels", dependencies=[Depends(authorized)])
    def channels() -> dict[str, Any]:
        return host.channels.public()

    @app.put("/api/channels", dependencies=[Depends(authorized)])
    def configure_channel(config: ChannelConfig) -> dict[str, Any]:
        with host.exclusive():
            host.channels.configure(config)
        return host.channels.public()

    @app.post("/api/channels/login/{step}", dependencies=[Depends(authorized)])
    def channel_login(step: str) -> dict[str, Any]:
        if step not in {"start", "poll"}:
            raise ValueError("invalid login step")
        with host.exclusive():
            return host.channels.login(poll=step == "poll")

    @app.post("/api/channels/demo/message", dependencies=[Depends(authorized)])
    def demo_message(item: IncomingMessage) -> dict[str, Any]:
        with host.exclusive():
            if host.channels.config.transport != "demo":
                raise ValueError("demo channel required")
            identifier = host.channels.receive(item)
            host.channels.process()
            return {"id": identifier, **host.channels.public()}

    @app.get("/api/export", dependencies=[Depends(authorized)])
    def export() -> Response:
        with host.lock:
            payload = {
                "exported_at": datetime.now(UTC).isoformat(),
                "settings": host.settings.model_dump(mode="json"),
                "conversations": host.conversations(),
                "memory": host.memory.export(LOCAL_USER).model_dump(mode="json"),
            }
            return Response(
                json.dumps(payload, ensure_ascii=False, indent=2),
                media_type="application/json",
                headers={"Content-Disposition": 'attachment; filename="companion-memories.json"'},
            )

    if client_token is not None:

        @app.get("/api/local/backup", dependencies=[Depends(authorized)])
        def local_backup() -> Response:
            from companion_agent.local_data import backup_bytes

            with host.exclusive():
                return Response(backup_bytes(host.database), media_type="application/octet-stream")

        @app.post("/api/local/restore", dependencies=[Depends(authorized)])
        async def local_restore(request: Request) -> dict[str, bool]:
            import asyncio

            from companion_agent.local_data import stage_restore

            content = await request.body()

            def prepare() -> None:
                with host.exclusive():
                    try:
                        stage_restore(host.database.data_dir, content)
                    except ValueError as error:
                        raise problem(422, "invalid_backup", str(error)) from None

            await asyncio.to_thread(prepare)
            return {"restart_required": True}

    @app.get("/api/automation", dependencies=[Depends(authorized)])
    def automation() -> dict[str, Any]:
        return host.tools.public_state()

    @app.put("/api/automation/config", dependencies=[Depends(authorized)])
    def automation_config(config: AutomationConfig) -> dict[str, bool]:
        with host.exclusive():
            host.tools.configure(config)
        return {"saved": True}

    @app.post("/api/automation/servers/{server_id}/connect", dependencies=[Depends(authorized)])
    def connect_mcp(server_id: str) -> dict[str, Any]:
        from companion_agent.automation.mcp_client import MCPFailure

        try:
            return {"tools": host.tools.discover(server_id)}
        except MCPFailure:
            raise problem(
                502, "mcp_connection_failed", "无法连接 MCP，请检查命令、地址和环境变量。"
            ) from None

    @app.post("/api/automation/actions/{action_id}/{decision}", dependencies=[Depends(authorized)])
    def decide_action(action_id: str, decision: str) -> dict[str, Any]:
        if decision == "resume":
            return {"continuation": host.resume(action_id)}
        if decision not in {"approve", "deny"}:
            raise problem(422, "invalid_decision", "请选择确认或拒绝。")
        return host.decide_action(action_id, decision == "approve")

    @app.post("/api/automation/schedules", dependencies=[Depends(authorized)])
    def create_schedule(item: ScheduleInput) -> dict[str, Any]:
        host.scope(item.conversation_id)
        if not host.settings.storage_consent:
            raise problem(403, "consent_required", "请先允许本地保存，再创建任务。")
        if item.tool_name:
            if not item.tool_name.startswith("mcp_"):
                raise problem(422, "invalid_tool", "定时操作需选择已连接的 MCP 工具。")
            host.tools.inspect(item.tool_name, item.arguments)
        return host.tools.scheduler.create(item, str(uuid4()))

    @app.post("/api/automation/schedules/{job_id}/{status}", dependencies=[Depends(authorized)])
    def change_schedule(job_id: str, status: str) -> dict[str, bool]:
        host.tools.scheduler.change(job_id, status)
        return {"saved": True}

    @app.post("/api/automation/notifications/read", dependencies=[Depends(authorized)])
    def read_notifications() -> dict[str, bool]:
        with host.database.connection() as db:
            db.execute("UPDATE agent_notifications SET seen=1")
        return {"saved": True}

    @app.post("/api/automation/cancel/{request_id}", dependencies=[Depends(authorized)])
    def cancel_run(request_id: str) -> dict[str, bool]:
        return {"cancelled": host.loop.cancel(request_id)}

    @app.get("/api/automation/phone-template", dependencies=[Depends(authorized)])
    def phone_template() -> dict[str, Any]:
        import sys

        return {
            "id": "android",
            "label": "安卓与个人微信",
            "transport": "stdio",
            "command": sys.executable,
            "args": [
                "-m",
                "companion_agent.integrations.phone",
                "--serial",
                "填写设备序列号",
                "--packages",
                "com.tencent.mm",
                "--contacts",
                "填写允许操作的联系人名称",
            ],
            "enabled": False,
            "tools": {},
        }

    if testing:
        from companion_agent.testing.control import install_routes

        install_routes(app, host, testing, authorized)
    app.mount("/static", StaticFiles(directory=static), name="static")
    return app


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser(description="心隅 · 基于 MemoryOS 的 DeepSeek 恋爱陪伴")
    parser.add_argument("--data-dir", type=Path, default=Path(".agent-data/romance"))
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    print(f"心隅已启动，请打开 http://127.0.0.1:{args.port}")
    uvicorn.run(create_app(args.data_dir), host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
