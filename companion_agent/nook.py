"""A source-bound, automatically curated pixel room in the existing SQLite store."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from threading import Event, Lock, Thread
from typing import TYPE_CHECKING, Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI
from pydantic import Field

from companion_agent.context import ChatMessage
from companion_agent.evidence_policy import restricted_evidence
from companion_agent.llm import MainLLMError, wire_input_tokens
from companion_agent.nook_art import (
    PIXEL_SIDE,
    NookArtist,
    NookBrief,
    NookDesign,
    NookSelection,
    PixelArt,
    _parse_payload,
    painting_messages,
    parse_nook_painting,
    parse_nook_plan,
)
from companion_agent.nook_drawing import render_drawing
from companion_agent.nook_layer_retouch import apply_layer_retouch, layer_retouch_messages
from companion_agent.nook_prompts import NOOK_DESIGN_PROMPT
from companion_agent.persona.models import PersonaModel
from companion_agent.romance import SettingsUpdate
from companion_agent.streaming import cancelled, listener
from companion_memoryos.diagnostics import background_context, sink
from companion_memoryos.schemas import (
    ConversationRole,
    ExperienceEvidenceKind,
    ExperienceEvidenceRef,
    ProcessTurnRequest,
    Sensitivity,
)
from companion_memoryos.turn_layers import turn_reality_layer

if TYPE_CHECKING:
    from companion_agent.app import RomanceHost

SOURCE_LIMIT = 12
SOURCE_CHARS = 900
MAX_INPUT_TOKENS = 7500
AUTO_INTERVAL_MINUTES = 30
ZONES = ("window", "shelf", "desk", "wall", "floor")
STATUSES = {
    "idle": "让聊过的小事，慢慢住进来。",
    "drawing": "TA 正在为一段回忆画小物件…",
    "created": "小窝里多了一件新物品。",
    "updated": "一件物品有了新的故事。",
    "stored": "新作品收进了收纳盒，珍藏的物品仍在原处。",
    "unchanged": "这次先把故事留在聊天里。",
    "failed": "这次创作未完成；可以稍后手动重试。",
    "output_limit": "模型还没画完就达到输出上限；可在模型设置中提高输出 Token 上限后重试。",
    "interrupted": "上次创作被中断，尚未重试。",
    "stale": "来源或设置已变化，这次创作已取消。",
    "offline": "像素创作需要已配置的在线聊天模型。",
    "disabled": "开启后，TA 会在聊天后自主创作和布置。",
    "consent": "请先在陪伴设置中允许保存和模型处理。",
    "limit": "今天的创作次数已用完，明天再继续。",
    "empty": "先聊几句，给小窝留一点创作灵感。",
    "cooldown": "刚刚布置过，新的故事会在稍后聊天时整理。",
}


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


class NookSettings(PersonaModel):
    enabled: bool
    daily_limit: int = Field(default=3, ge=1, le=12)


class NookRequest(PersonaModel):
    conversation_id: str = Field(min_length=1, max_length=128)


class NookVisibility(PersonaModel):
    displayed: bool | None = None
    pinned: bool | None = None


class MemoryNook:
    def __init__(self, host: RomanceHost) -> None:
        self.host = host
        self.busy = Lock()
        self.stopped = Event()
        self.worker: Thread | None = None
        self.epoch = 0
        with host.database.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS nook_objects (
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL, companion_id TEXT NOT NULL,
                    relationship_id TEXT NOT NULL, displayed INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE IF NOT EXISTS nook_versions (
                    revision INTEGER PRIMARY KEY AUTOINCREMENT,
                    object_id TEXT NOT NULL REFERENCES nook_objects(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL, data_json TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS nook_version_owner ON nook_versions(object_id);
                CREATE TABLE IF NOT EXISTS nook_sources (
                    object_id TEXT NOT NULL REFERENCES nook_objects(id) ON DELETE CASCADE,
                    ref TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    PRIMARY KEY(object_id,ref));
                CREATE INDEX IF NOT EXISTS nook_source_ref ON nook_sources(ref);
                CREATE TABLE IF NOT EXISTS nook_runs (
                    id TEXT PRIMARY KEY, created_at TEXT NOT NULL, local_day TEXT NOT NULL,
                    fingerprint TEXT NOT NULL, status TEXT NOT NULL);
            """)
            db.execute("UPDATE nook_runs SET status='interrupted' WHERE status='drawing'")
            run_columns = {row["name"] for row in db.execute("PRAGMA table_info(nook_runs)")}
            if "error_code" not in run_columns:
                db.execute("ALTER TABLE nook_runs ADD COLUMN error_code TEXT")
            columns = {row["name"] for row in db.execute("PRAGMA table_info(nook_objects)")}
            if "pinned" not in columns:
                db.execute("ALTER TABLE nook_objects ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0")
            # Derivatives, including every historical sprite, share source deletion.
            for table, kind, condition in (
                (
                    "conversation_turns",
                    "turn",
                    "NEW.deletion_state!='active' OR "
                    "NEW.consent!='granted' OR NEW.content!=OLD.content OR "
                    "NEW.metadata_json!=OLD.metadata_json OR "
                    "NEW.speech_spans_json!=OLD.speech_spans_json",
                ),
                (
                    "memories",
                    "memory",
                    "NEW.status!='active' OR NEW.consent!='granted' OR "
                    "NEW.content!=OLD.content OR "
                    "NEW.evidence_turn_ids_json!=OLD.evidence_turn_ids_json",
                ),
            ):
                cleanup = (
                    "DELETE FROM nook_objects WHERE id IN (SELECT object_id FROM nook_sources "
                    f"WHERE ref='{kind}:' || OLD.id);"
                )
                db.execute(
                    f"CREATE TRIGGER IF NOT EXISTS nook_{kind}_update AFTER UPDATE ON {table} "
                    f"WHEN {condition} BEGIN {cleanup} END"
                )
                db.execute(
                    f"CREATE TRIGGER IF NOT EXISTS nook_{kind}_delete AFTER DELETE ON {table} "
                    f"BEGIN {cleanup} END"
                )

    def invalidate(self) -> None:
        self.epoch += 1
        if not self.host.settings.storage_consent:
            with self.host.database.connection() as db:
                db.execute("DELETE FROM nook_objects")

    def close(self) -> None:
        self.stopped.set()
        self.epoch += 1

    def source(self, ref: str) -> dict[str, Any]:
        kind, identifier = ref.split(":", 1)
        host = self.host
        if kind == "turn":
            turn = host.journal.require_turn(identifier, for_model=True)
            if turn.role is not ConversationRole.USER or turn.actor_id != host.key.user_id:
                raise ValueError("not a user source")
            with host.database.connection() as db:
                obsolete = db.execute(
                    "SELECT 1 FROM memories,json_each(evidence_turn_ids_json) "
                    "WHERE user_id=? AND status IN ('superseded','contested','forgotten',"
                    "'rejected','expired') AND value=? LIMIT 1",
                    (host.key.user_id, identifier),
                ).fetchone()
            if obsolete or turn.metadata.get("content_redacted_empty"):
                raise ValueError("source is obsolete")
            layer = turn_reality_layer(
                turn.content,
                json.dumps(turn.metadata),
                json.dumps([span.model_dump(mode="json") for span in turn.speech_spans]),
            )
            content, at, scope = turn.content, turn.occurred_at, turn.scope
            fingerprint = digest(
                [
                    content,
                    layer,
                    scope.model_dump(),
                    [s.model_dump(mode="json") for s in turn.speech_spans],
                ]
            )
        elif kind == "memory":
            memory = host.journal.require_memory(identifier)
            if memory.sensitivity is not Sensitivity.NORMAL or not memory.evidence_turn_ids:
                raise ValueError("source is not eligible")
            for identifier in memory.evidence_turn_ids:
                host.journal.require_turn(identifier, for_model=True)
            blocked = restricted_evidence(
                host.memory,
                host.key,
                [ExperienceEvidenceRef(kind=ExperienceEvidenceKind.MEMORY, id=memory.id)],
                datetime.now(UTC),
            )
            if ref in blocked:
                raise ValueError("source is restricted")
            layer = memory.reality_layer.value
            content, at, scope = memory.content, memory.event_at, memory.scope
            fingerprint = digest([content, layer, scope.model_dump(), memory.evidence_turn_ids])
        else:
            raise ValueError("unknown source kind")
        if layer not in {"real_world", "roleplay"} or at > datetime.now(UTC):
            raise ValueError("source is not an established event")
        return {
            "ref": ref,
            "content": content[:SOURCE_CHARS],
            "at": at.isoformat(),
            "reality_layer": layer,
            "conversation_id": scope.conversation_id,
            "fingerprint": fingerprint,
        }

    def sources(self, conversation: str) -> list[dict[str, Any]]:
        host = self.host
        host.scope(conversation)
        with host.database.connection() as db:
            rows = db.execute(
                "SELECT id FROM conversation_turns WHERE user_id=? AND companion_id=? "
                "AND relationship_id=? AND conversation_id=? AND group_id IS NULL "
                "AND role='user' ORDER BY server_sequence DESC LIMIT ?",
                (*host.key.values, conversation, SOURCE_LIMIT),
            ).fetchall()
            memories = db.execute(
                "SELECT id FROM memories WHERE user_id=? AND companion_id=? AND relationship_id=? "
                "AND group_id IS NULL AND (conversation_id IS NULL OR conversation_id=?) "
                "AND status='active' ORDER BY created_at DESC LIMIT ?",
                (*host.key.values, conversation, SOURCE_LIMIT),
            ).fetchall()
        result = []
        for kind, items in (("turn", rows), ("memory", memories)):
            for row in items:
                try:
                    result.append(self.source(f"{kind}:{row['id']}"))
                except (KeyError, ValueError):
                    continue
        return result

    def prune(self) -> None:
        with self.host.database.atomic() as db:
            for row in db.execute("SELECT * FROM nook_sources").fetchall():
                try:
                    valid = self.source(row["ref"])["fingerprint"] == row["fingerprint"]
                except (KeyError, ValueError):
                    valid = False
                if not valid:
                    db.execute("DELETE FROM nook_objects WHERE id=?", (row["object_id"],))

    def room(self, at: datetime | None = None, *, include_source: bool = False) -> dict[str, Any]:
        self.host.journal.require_storage()
        if at is not None:
            if at.tzinfo is None:
                raise ValueError("timezone required")
            at = at.astimezone(UTC)
        self.prune()
        objects = []
        with self.host.database.connection() as db:
            rows = db.execute(
                "SELECT * FROM nook_objects WHERE user_id=? AND companion_id=? "
                "AND relationship_id=? ORDER BY rowid",
                self.host.key.values,
            ).fetchall()
            for row in rows:
                version = db.execute(
                    "SELECT * FROM nook_versions WHERE object_id=? AND created_at<=? "
                    "ORDER BY revision DESC LIMIT 1",
                    (row["id"], (at or datetime.now(UTC)).isoformat()),
                ).fetchone()
                if version:
                    data = json.loads(version["data_json"])
                    if not include_source:
                        data.pop("drawing", None)
                        data.pop("brief", None)
                    objects.append(
                        {
                            **data,
                            "id": row["id"],
                            "displayed": bool(row["displayed"]),
                            "pinned": bool(row["pinned"]),
                            "created_at": version["created_at"],
                            "evidence": [self.source(ref) for ref in data["sources"]],
                        }
                    )
            times = [
                r[0]
                for r in db.execute(
                    "SELECT DISTINCT created_at FROM nook_versions ORDER BY created_at"
                ).fetchall()
            ]
            last = db.execute(
                "SELECT status,error_code FROM nook_runs ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
        status = self.readiness() or (last[0] if last else "idle")
        return {
            "items": objects,
            "timeline": times,
            "status": status,
            "error_code": last["error_code"] if last and status == last["status"] else None,
            "message": STATUSES.get(status, STATUSES["idle"]),
            "enabled": self.host.settings.nook_enabled,
            "daily_limit": self.host.settings.nook_daily_limit,
            "busy": self.busy.locked(),
            "pixel_side": PIXEL_SIDE,
            "remaining_today": self.remaining(),
        }

    def chat_context(self, request: ProcessTurnRequest) -> tuple[dict[str, Any], list[str]]:
        """Describe requested artwork, never feed artistic inventions back as daily facts."""
        if not self.host.settings.storage_consent or not self.host.settings.model_consent:
            return {}, []
        if not any(word in request.content for word in ("小窝", "回忆房间", "你画的", "你创作的")):
            return {}, []
        scope = request.scope
        if (
            request.user_id,
            scope.companion_id,
            scope.relationship_id,
        ) != self.host.key.values or scope.group_id is not None:
            return {}, []
        self.host.scope(scope.conversation_id or "")
        items = self.room()["items"]
        # Objects are available for an explicit artwork question. Mere resemblance
        # to a daily topic does not turn generated meaning into user testimony.
        items = sorted(
            items,
            key=lambda item: (
                item["title"] not in request.content,
                not item["displayed"],
                not item["pinned"],
            ),
        )
        records: list[dict[str, Any]] = []
        source_ids: set[str] = set()
        for item in items:
            if not item["displayed"] and not item["pinned"]:
                continue
            record = {
                key: item[key]
                for key in (
                    "id",
                    "title",
                    "meaning",
                    "reality_layer",
                    "zone",
                    "displayed",
                    "pinned",
                )
            }
            record["sources"] = [
                {key: source[key] for key in ("ref", "content", "at", "reality_layer")}
                for source in item["evidence"]
            ]
            record["authority"] = "artistic_interpretation_not_testimony"
            candidate = {"items": [*records, record]}
            if (
                self.host.memory.token_counter.count(json.dumps(candidate, ensure_ascii=False))
                > 1800
            ):
                continue
            records.append(record)
            with self.host.database.connection() as db:
                dependencies = db.execute(
                    "SELECT ref FROM nook_sources WHERE object_id=?", (item["id"],)
                ).fetchall()
            for dependency in dependencies:
                kind, identifier = dependency["ref"].split(":", 1)
                if kind == "turn":
                    source_ids.add(identifier)
                else:
                    source_ids.update(
                        self.host.journal.require_memory(identifier).evidence_turn_ids
                    )
        return ({"items": records} if records else {}), sorted(source_ids)

    def remaining(self) -> int:
        settings = self.host.settings
        day = datetime.now(ZoneInfo(settings.calendar_timezone)).date().isoformat()
        with self.host.database.connection() as db:
            used = db.execute(
                "SELECT COUNT(*) FROM nook_runs WHERE local_day=?", (day,)
            ).fetchone()[0]
        return max(0, settings.nook_daily_limit - int(used))

    def readiness(self) -> str | None:
        settings = self.host.settings
        if not settings.storage_consent or not settings.model_consent:
            return "consent"
        if not settings.nook_enabled:
            return "disabled"
        if settings.model_mode != "api" and self.host.injected_llm is None:
            return "offline"
        if not self.host.credentials_ready():
            return "offline"
        return None

    def start(self, conversation: str, *, manual: bool = False) -> str:
        if self.stopped.is_set():
            return "interrupted"
        if issue := self.readiness():
            return issue
        if not self.remaining():
            return "limit"
        if not self.sources(conversation):
            return "empty"
        if not self.busy.acquire(blocking=False):
            return "drawing"
        context = background_context()
        # Creative output never leaks into the visible chat stream or tool loop.
        context.run(listener.set, None)
        context.run(cancelled.set, None)
        if self.host.testing and context.run(sink.get) is None:
            context.run(sink.set, self.host.testing.fork_background())
        self.worker = Thread(
            target=context.run, args=(self._work, conversation, manual), daemon=True
        )
        self.worker.start()
        return "drawing"

    def _work(self, conversation: str, manual: bool) -> None:
        run_id: str | None = None
        status = "failed"
        stage = "preparation"
        error_code: str | None = None
        try:
            with self.host.lock:
                if self.readiness() or self.stopped.is_set():
                    return
                self.prune()
                sources = self.sources(conversation)
                if not sources:
                    return
                fingerprint = digest([(s["ref"], s["fingerprint"]) for s in sources])
                settings = self.host.settings
                epoch = self.epoch
                now = datetime.now(UTC)
                day = now.astimezone(ZoneInfo(settings.calendar_timezone)).date().isoformat()
                with self.host.database.atomic() as db:
                    if (
                        db.execute(
                            "SELECT COUNT(*) FROM nook_runs WHERE local_day=?", (day,)
                        ).fetchone()[0]
                        >= settings.nook_daily_limit
                    ):
                        return
                    previous = db.execute(
                        "SELECT * FROM nook_runs ORDER BY rowid DESC LIMIT 1"
                    ).fetchone()
                    if previous and (
                        (previous["fingerprint"] == fingerprint and not manual)
                        or (
                            not manual
                            and now - datetime.fromisoformat(previous["created_at"])
                            < timedelta(minutes=AUTO_INTERVAL_MINUTES)
                        )
                    ):
                        return
                    # Explicit retry is allowed; failed calls still consume the persistent cap.
                    run_id = uuid4().hex
                    db.execute(
                        "INSERT INTO nook_runs (id,created_at,local_day,fingerprint,status) "
                        "VALUES (?,?,?,?,?)",
                        (run_id, now.isoformat(), day, fingerprint, "drawing"),
                    )
                existing = self.room(include_source=True)["items"]
                payload = {
                    "sources": sources,
                    "objects": [
                        {
                            k: o[k]
                            for k in (
                                "id",
                                "title",
                                "meaning",
                                "zone",
                                "slot",
                                "sources",
                                "displayed",
                                "pinned",
                            )
                        }
                        for o in existing
                    ],
                }
                messages = [
                    ChatMessage(role="system", content=NOOK_DESIGN_PROMPT),
                    ChatMessage(role="user", content=json.dumps(payload, ensure_ascii=False)),
                ]
                # The transport's escaped JSON is not what the model reads. Match
                # the chat adapter's Unicode text accounting, including its envelope.
                # Trim whole optional sources, never half a statement or any artwork.
                while (
                    wire_input_tokens([m.wire() for m in messages], self.host.memory.token_counter)
                    > MAX_INPUT_TOKENS
                    and len(sources) > 1
                ):
                    sources.pop()
                    messages[-1] = ChatMessage(
                        role="user", content=json.dumps(payload, ensure_ascii=False)
                    )
                stage = "selection_input"
                if (
                    wire_input_tokens([m.wire() for m in messages], self.host.memory.token_counter)
                    > MAX_INPUT_TOKENS
                ):
                    raise ValueError("nook input budget exceeded")
                # All admitted context becomes deletion lineage, including old art.
                dependencies = {s["ref"]: s["fingerprint"] for s in sources}
                with self.host.database.connection() as db:
                    for row in db.execute("SELECT ref,fingerprint FROM nook_sources").fetchall():
                        dependencies[row["ref"]] = row["fingerprint"]
                model = self.host.injected_llm or NookArtist(
                    settings.deepseek,
                    api_key=self.host.resolved_key(settings, self.host.api_key),
                    use_environment=False,
                )
            # No app/SQLite writer lock across the model call.
            stage = "selection_model"
            result = model.generate(messages)
            stage = "selection_validation"
            plan = parse_nook_plan(result.text)
            with self.host.lock:
                if self._stale(epoch, dependencies):
                    status = "stale"
                    return
                if plan.object is None:
                    status = "unchanged"
                    return
                old = self._validate_selection(plan.object, sources, existing)
                original = old.get("drawing") if old else None
                if original and old:
                    messages = layer_retouch_messages(
                        plan.object.brief, original, PixelArt.model_validate(old["art"])
                    )
                else:
                    messages = painting_messages(plan.object, old["art"] if old else None)
                stage = "painting_input"
                if (
                    wire_input_tokens([m.wire() for m in messages], self.host.memory.token_counter)
                    > MAX_INPUT_TOKENS
                ):
                    raise ValueError("nook painting input budget exceeded")
            # The same configured model paints once. No automatic repair loop.
            stage = "painting_model"
            response = model.generate(messages).text
            stage = "painting_validation"
            drawing: dict[str, Any] | None
            if original and old:
                updated = apply_layer_retouch(
                    response, original, PixelArt.model_validate(old["art"])
                )
                art, drawing = updated.art, updated.drawing
            else:
                art = parse_nook_painting(response)
                raw = _parse_payload(response, "art")["art"]
                drawing = raw if isinstance(raw, dict) and "layers" in raw else None
            design = NookDesign.model_validate(
                {**plan.object.model_dump(exclude={"brief"}), "art": art}
            )
            with self.host.lock, self.host.database.atomic():
                stage = "commit"
                if self._stale(epoch, dependencies):
                    status = "stale"
                else:
                    status = self.commit(
                        design,
                        sources,
                        dependencies,
                        existing,
                        brief=plan.object.brief,
                        drawing=drawing,
                    )
        except MainLLMError as error:
            if str(error) == "nook_output_limit":
                status = "output_limit"
            error_code = "output_limit" if status == "output_limit" else stage
            logging.getLogger(__name__).warning("nook_creation_failed stage=%s", error_code)
        except Exception:
            # No provider bodies, generated content or credentials in logs/status.
            error_code = stage
            logging.getLogger(__name__).warning("nook_creation_failed stage=%s", stage)
        finally:
            try:
                if run_id:
                    with self.host.database.connection() as db:
                        db.execute(
                            "UPDATE nook_runs SET status=?,error_code=? WHERE id=?",
                            (status, error_code, run_id),
                        )
            finally:
                self.busy.release()

    def _stale(self, epoch: int, dependencies: dict[str, str]) -> bool:
        if self.stopped.is_set() or epoch != self.epoch or self.readiness():
            return True
        try:
            return any(
                self.source(ref)["fingerprint"] != value for ref, value in dependencies.items()
            )
        except (KeyError, ValueError):
            return True

    def _validate_selection(
        self,
        design: NookSelection,
        sources: list[dict[str, Any]],
        existing: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        available = {s["ref"]: s for s in sources}
        if len(set(design.sources)) != len(design.sources) or any(
            ref not in available or available[ref]["reality_layer"] != design.reality_layer
            for ref in design.sources
        ):
            raise ValueError("unavailable or mixed-reality evidence")
        old = next((o for o in existing if o["id"] == design.update_id), None)
        if not design.update_id and any(set(design.sources) <= set(o["sources"]) for o in existing):
            raise ValueError("an existing keepsake already covers this story")
        if design.update_id and (not old or not old["displayed"]):
            raise ValueError("update target is unavailable")
        if old and old.get("pinned"):
            raise ValueError("treasured keepsake cannot be repainted automatically")
        if old and old["reality_layer"] != design.reality_layer:
            raise ValueError("cannot mix reality layers")
        return old

    def commit(
        self,
        design: NookDesign,
        sources: list[dict[str, Any]],
        dependencies: dict[str, str],
        existing: list[dict[str, Any]],
        *,
        brief: NookBrief | None = None,
        drawing: dict[str, Any] | None = None,
    ) -> str:
        old = self._validate_selection(design, sources, existing)
        identifier = design.update_id or uuid4().hex
        data = design.model_dump(mode="json", exclude={"update_id"})
        if drawing is not None:
            if render_drawing(drawing) != design.art.model_dump(mode="json"):
                raise ValueError("drawing source does not match final pixels")
            data["drawing"] = drawing
        if brief is not None:
            data["brief"] = brief.model_dump(mode="json")
        if old:
            data["sources"] = list(dict.fromkeys([*old["sources"], *design.sources]))
        displayed = True
        with self.host.database.connection() as db:
            occupied = {
                o["slot"]
                for o in existing
                if o["displayed"] and o["zone"] == design.zone and o["id"] != identifier
            }
            free = [slot for slot in range(3) if slot not in occupied]
            if design.slot in occupied:
                if free:
                    data["slot"] = free[0]
                else:
                    oldest = next(
                        (
                            o
                            for o in existing
                            if o["zone"] == design.zone and o["displayed"] and not o.get("pinned")
                        ),
                        None,
                    )
                    if oldest:
                        data["slot"] = oldest["slot"]
                        db.execute(
                            "UPDATE nook_objects SET displayed=0 WHERE id=?", (oldest["id"],)
                        )
                    else:
                        displayed = False
            if old is None:
                db.execute(
                    "INSERT INTO nook_objects(id,user_id,companion_id,relationship_id,displayed) "
                    "VALUES (?,?,?,?,?)",
                    (identifier, *self.host.key.values, displayed),
                )
            db.execute(
                "INSERT INTO nook_versions(object_id,created_at,data_json) VALUES (?,?,?)",
                (identifier, datetime.now(UTC).isoformat(), json.dumps(data, ensure_ascii=False)),
            )
            db.executemany(
                "INSERT OR IGNORE INTO nook_sources VALUES (?,?,?)",
                [(identifier, ref, value) for ref, value in dependencies.items()],
            )
        return "updated" if old else "created" if displayed else "stored"

    def cherish(self, identifier: str, pinned: bool) -> None:
        if not any(item["id"] == identifier for item in self.room()["items"]):
            raise ValueError("object unavailable")
        self.epoch += 1
        with self.host.database.connection() as db:
            db.execute("UPDATE nook_objects SET pinned=? WHERE id=?", (pinned, identifier))

    def visibility(self, identifier: str, displayed: bool) -> None:
        room = self.room()
        selected = next((o for o in room["items"] if o["id"] == identifier), None)
        if not selected:
            raise ValueError("object unavailable")
        if displayed and any(
            o["displayed"]
            and o["id"] != identifier
            and o["zone"] == selected["zone"]
            and o["slot"] == selected["slot"]
            for o in room["items"]
        ):
            raise ValueError("请先收起同一位置的物品。")
        self.epoch += 1
        with self.host.database.connection() as db:
            db.execute("UPDATE nook_objects SET displayed=? WHERE id=?", (displayed, identifier))


def install_routes(app: FastAPI, host: RomanceHost, authorized: Callable[..., Any]) -> None:
    @app.get("/api/nook", dependencies=[Depends(authorized)])
    def room(at: datetime | None = None) -> dict[str, Any]:
        with host.lock:
            return host.nook.room(at)

    @app.put("/api/nook/settings", dependencies=[Depends(authorized)])
    def settings(item: NookSettings) -> dict[str, Any]:
        with host.lock:
            host.save_settings(
                SettingsUpdate(
                    settings=host.settings.model_copy(
                        update={
                            "nook_enabled": item.enabled,
                            "nook_daily_limit": item.daily_limit,
                        }
                    )
                )
            )
            return host.nook.room()

    @app.post("/api/nook/create", dependencies=[Depends(authorized)])
    def create(item: NookRequest) -> dict[str, str]:
        with host.lock:
            host.scope(item.conversation_id)
            status = host.nook.start(item.conversation_id, manual=True)
            return {"status": status, "message": STATUSES[status]}

    @app.put("/api/nook/objects/{identifier}", dependencies=[Depends(authorized)])
    def visibility(identifier: str, item: NookVisibility) -> dict[str, Any]:
        with host.exclusive():
            if item.displayed is not None:
                host.nook.visibility(identifier, item.displayed)
            if item.pinned is not None:
                host.nook.cherish(identifier, item.pinned)
            return host.nook.room()
