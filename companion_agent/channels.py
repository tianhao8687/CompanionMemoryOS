"""Owner-bound text ingress and durable delivery, with a Weixin ClawBot adapter.

Protocol reference: AstrBot's public weixin_oc adapter at 95e98b8 (2026-09-22).
No credential is returned by the public API or included in an export.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import urllib.parse
import urllib.request
from threading import Event, Lock, Thread
from typing import TYPE_CHECKING, Any, Literal

from pydantic import Field, field_validator

from companion_agent.cognition import NoRedirect
from companion_agent.persona.models import PersonaModel
from companion_memoryos.schemas import ConversationRole, TurnDeletionState

if TYPE_CHECKING:
    from companion_agent.app import RomanceHost


class ChannelConfig(PersonaModel):
    enabled: bool = False
    transport: Literal["demo", "weixin"] = "demo"
    owner_id: str = Field(default="demo-owner", max_length=240)
    conversation_id: str = Field(default="", max_length=128)
    base_url: str = "https://ilinkai.weixin.qq.com"
    token_env: str = Field(default="COMPANION_WEIXIN_TOKEN", pattern=r"^[A-Z_][A-Z0-9_]*$")

    @field_validator("base_url")
    @classmethod
    def endpoint(cls, value: str) -> str:
        parts = urllib.parse.urlsplit(value)
        local = parts.hostname in {"127.0.0.1", "localhost", "::1"}
        official = parts.hostname == "ilinkai.weixin.qq.com" or (parts.hostname or "").endswith(
            ".ilinkai.weixin.qq.com"
        )
        if (
            parts.username
            or parts.password
            or parts.query
            or parts.fragment
            or parts.path not in {"", "/"}
        ):
            raise ValueError("invalid channel endpoint")
        if not (
            (local and parts.scheme in {"http", "https"})
            or (official and parts.scheme == "https" and parts.port in {None, 443})
        ):
            raise ValueError("use the official Weixin endpoint or a loopback test server")
        return value.rstrip("/")


class IncomingMessage(PersonaModel):
    delivery_id: str = Field(min_length=1, max_length=240)
    sender_id: str = Field(min_length=1, max_length=240)
    text: str = Field(min_length=1, max_length=6000)
    context_token: str = Field(default="", max_length=4096)


class WeixinClient:
    def __init__(self, base_url: str, token: str | None = None) -> None:
        self.base_url = ChannelConfig.endpoint(base_url)
        self.token = token

    def request(
        self,
        endpoint: str,
        payload: dict[str, Any] | None = None,
        *,
        query: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        url = self.base_url + "/ilink/bot/" + endpoint
        if query:
            url += "?" + urllib.parse.urlencode(query)
        headers = {
            "Content-Type": "application/json",
            "AuthorizationType": "ilink_bot_token",
            "iLink-App-ClientVersion": "1",
            "X-WECHAT-UIN": base64.b64encode(str(secrets.randbits(32)).encode()).decode(),
        }
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        data = json.dumps(payload).encode() if payload is not None else None
        try:
            with urllib.request.build_opener(NoRedirect()).open(
                urllib.request.Request(url, data=data, headers=headers), timeout=15
            ) as response:
                raw = response.read(1048577)
            if len(raw) > 1048576:
                raise ValueError("response too large")
            result = json.loads(raw)
            if not isinstance(result, dict) or any(
                result.get(k, 0) not in (0, None) for k in ("ret", "errcode")
            ):
                raise ValueError("channel rejected request")
            return result
        except (OSError, ValueError, TypeError):
            raise ValueError("微信连接未完成，请检查登录状态和网络。") from None

    def updates(self, cursor: str) -> dict[str, Any]:
        return self.request(
            "getupdates",
            {"get_updates_buf": cursor, "base_info": {"channel_version": "companion-agent"}},
        )

    def send(self, sender: str, context: str, delivery: str, text: str) -> None:
        if not context:
            raise ValueError("missing context token")
        self.request(
            "sendmessage",
            {
                "base_info": {"channel_version": "companion-agent"},
                "msg": {
                    "from_user_id": "",
                    "to_user_id": sender,
                    "client_id": delivery,
                    "message_type": 2,
                    "message_state": 2,
                    "context_token": context,
                    "item_list": [{"type": 1, "text_item": {"text": text}}],
                },
            },
        )


class Channels:
    def __init__(self, host: RomanceHost) -> None:
        self.host = host
        self.session_token: str | None = None
        self.qrcode: str | None = None
        self.error = ""
        self._stop = Event()
        self._lock = Lock()
        self._thread: Thread | None = None
        with host.database.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS agent_channel_config
                    (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL, cursor TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS agent_inbox
                    (id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, sender TEXT NOT NULL,
                     content TEXT NOT NULL, context_token TEXT NOT NULL, status TEXT NOT NULL,
                     source_turn TEXT, transport TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS agent_outbox
                    (id TEXT PRIMARY KEY, inbox_id TEXT NOT NULL, content TEXT NOT NULL,
                     status TEXT NOT NULL);
            """)
            db.execute("UPDATE agent_outbox SET status='uncertain' WHERE status='sending'")
            saved = db.execute("SELECT data FROM agent_channel_config WHERE id=1").fetchone()
        self.config = ChannelConfig.model_validate_json(saved["data"]) if saved else ChannelConfig()

    def public(self) -> dict[str, Any]:
        with self.host.database.connection() as db:
            rows = db.execute(
                "SELECT id, status FROM agent_outbox ORDER BY rowid DESC LIMIT 40"
            ).fetchall()
        return {
            "config": self.config.model_dump(),
            "logged_in": bool(self.token()),
            "error": self.error,
            "deliveries": [dict(row) for row in rows],
        }

    def token(self) -> str | None:
        return self.session_token or os.environ.get(self.config.token_env)

    def configure(self, config: ChannelConfig) -> None:
        if config.enabled:
            self.host.scope(config.conversation_id)
            if not config.owner_id or not self.host.settings.storage_consent:
                raise ValueError("bind an owner and allow storage first")
        changed = (
            self.config.base_url,
            self.config.owner_id,
            self.config.transport,
            self.config.conversation_id,
        ) != (config.base_url, config.owner_id, config.transport, config.conversation_id)
        if changed:
            self.session_token = None
            self.qrcode = None
        with self.host.database.connection() as db:
            db.execute(
                "INSERT INTO agent_channel_config VALUES (1, ?, '') "
                "ON CONFLICT(id) DO UPDATE SET data=excluded.data, "
                "cursor=CASE WHEN ? THEN '' ELSE cursor END",
                (config.model_dump_json(), changed),
            )
        self.config = config

    def login(self, poll: bool = False) -> dict[str, Any]:
        if self.config.transport != "weixin":
            raise ValueError("select Weixin first")
        client = WeixinClient(self.config.base_url)
        if not poll:
            data = client.request("get_bot_qrcode", query={"bot_type": "3"})
            self.qrcode = str(data["qrcode"])
            return {"status": "wait", "login_url": str(data["qrcode_img_content"])}
        if not self.qrcode:
            raise ValueError("start login first")
        data = client.request("get_qrcode_status", query={"qrcode": self.qrcode})
        status = str(data.get("status", "wait"))
        if status == "confirmed":
            owner = str(data.get("ilink_user_id", ""))
            token = str(data.get("bot_token", ""))
            endpoint = ChannelConfig.endpoint(str(data.get("baseurl") or self.config.base_url))
            if not owner or not token:
                raise ValueError("login response missing owner or token")
            config = self.config.model_copy(update={"owner_id": owner, "base_url": endpoint})
            self.configure(config)
            self.session_token = token
            self.qrcode = None
        return {"status": status, "owner_id": self.config.owner_id}

    def receive(self, incoming: IncomingMessage) -> str:
        config = self.config
        if (
            not config.enabled
            or incoming.sender_id != config.owner_id
            or not self.host.settings.storage_consent
        ):
            raise ValueError("channel sender not authorized")
        identifier = hashlib.sha256(
            (config.transport + ":" + config.owner_id + ":" + incoming.delivery_id).encode()
        ).hexdigest()
        with self.host.database.atomic() as db:
            row = db.execute("SELECT content FROM agent_inbox WHERE id=?", (identifier,)).fetchone()
            if row and row["content"] != incoming.text:
                raise ValueError("delivery id reused with different content")
            db.execute(
                "INSERT OR IGNORE INTO agent_inbox VALUES (?, ?, ?, ?, ?, 'received', NULL, ?)",
                (
                    identifier,
                    config.conversation_id,
                    incoming.sender_id,
                    incoming.text,
                    incoming.context_token,
                    config.transport,
                ),
            )
        return identifier

    def process(self) -> None:
        from companion_agent.app import ChatInput

        if not self.config.enabled or not self.host.settings.storage_consent:
            return
        with self.host.database.connection() as db:
            rows = db.execute(
                "SELECT * FROM agent_inbox WHERE status='received' "
                "AND transport=? AND sender=? AND conversation_id=? ORDER BY rowid LIMIT 5",
                (self.config.transport, self.config.owner_id, self.config.conversation_id),
            ).fetchall()
        for row in rows:
            result = self.host.chat(
                ChatInput(
                    conversation_id=row["conversation_id"],
                    request_id="channel_" + row["id"],
                    content=row["content"],
                )
            )
            with self.host.database.connection() as db:
                db.execute(
                    "UPDATE agent_inbox SET source_turn=?, status='processed' WHERE id=?",
                    (result["user"]["id"], row["id"]),
                )
        self.flush()

    def flush(self) -> None:
        if not self.config.enabled or not self.host.settings.storage_consent:
            return
        with self.host.database.connection() as db:
            inbox = db.execute(
                "SELECT * FROM agent_inbox WHERE status='processed' "
                "AND transport=? AND sender=? AND conversation_id=?",
                (self.config.transport, self.config.owner_id, self.config.conversation_id),
            ).fetchall()
        for row in inbox:
            scope = self.host.scope(row["conversation_id"])
            for turn in self.host.memory.list_turns(self.host.key.user_id, scope):
                if (
                    turn.role is not ConversationRole.ASSISTANT
                    or turn.reply_to_turn_id != row["source_turn"]
                    or turn.deletion_state is not TurnDeletionState.ACTIVE
                    or turn.metadata.get("proactive")
                ):
                    continue
                with self.host.database.atomic() as db:
                    if db.execute("SELECT id FROM agent_outbox WHERE id=?", (turn.id,)).fetchone():
                        continue
                    # Persist before network I/O. Unknown delivery is never automatically resent.
                    db.execute(
                        "INSERT INTO agent_outbox VALUES (?, ?, ?, 'sending')",
                        (turn.id, row["id"], turn.content),
                    )
                status = "sent"
                if self.config.transport == "weixin":
                    try:
                        WeixinClient(self.config.base_url, self.token()).send(
                            row["sender"], row["context_token"], turn.id, turn.content
                        )
                    except ValueError:
                        status = "uncertain"
                with self.host.database.connection() as db:
                    db.execute("UPDATE agent_outbox SET status=? WHERE id=?", (status, turn.id))
                if status == "uncertain":
                    self.host.tools.store.notification(
                        row["conversation_id"],
                        "微信送达待核对",
                        "回复已保存在聊天中，外部送达不确定，未自动重发。",
                    )

    def tick(self) -> None:
        if not self.config.enabled or not self._lock.acquire(blocking=False):
            return
        host_locked = False
        try:
            snapshot = self.config.model_copy(deep=True)
            data: dict[str, Any] = {}
            if self.config.transport == "weixin":
                if not self.token() or not self.host.settings.storage_consent:
                    return
                with self.host.database.connection() as db:
                    row = db.execute(
                        "SELECT cursor FROM agent_channel_config WHERE id=1"
                    ).fetchone()
                data = WeixinClient(self.config.base_url, self.token()).updates(
                    row["cursor"] if row else ""
                )
            if not self.host.lock.acquire(blocking=False):
                return
            host_locked = True
            if self.config != snapshot:
                return
            if self.config.transport == "weixin":
                for msg in data.get("msgs", []):
                    if (
                        msg.get("from_user_id") != self.config.owner_id
                        or msg.get("message_type") != 1
                    ):
                        continue
                    content = "\n".join(
                        str(item.get("text_item", {}).get("text", ""))
                        for item in msg.get("item_list", [])
                        if item.get("type") == 1
                    ).strip()
                    mid = msg.get("message_id") or msg.get("msg_id")
                    if content and mid:
                        self.receive(
                            IncomingMessage(
                                delivery_id=str(mid),
                                sender_id=self.config.owner_id,
                                text=content,
                                context_token=str(msg.get("context_token", "")),
                            )
                        )
                with self.host.database.connection() as db:
                    db.execute(
                        "UPDATE agent_channel_config SET cursor=? WHERE id=1",
                        (str(data.get("get_updates_buf", "")),),
                    )
            self.process()
            self.error = ""
        except Exception:
            self.error = "渠道暂未完成处理，入站已保存的消息将在后续重试。"
        finally:
            if host_locked:
                self.host.lock.release()
            self._lock.release()

    def start(self) -> None:
        self._stop.clear()
        self._thread = Thread(target=self._run, name="companion-channels", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            self.tick()
            self._stop.wait(5)

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
