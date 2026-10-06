"""Pixel-room contracts using synthetic sources and recording model substitutes."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event
from typing import Any

import pytest
from pydantic import ValidationError

from companion_agent.app import LOCAL_USER
from companion_agent.context import ChatMessage
from companion_agent.llm import MainLLMError, ModelResponse
from companion_agent.nook_art import PixelArt, parse_nook_plan
from companion_agent.streaming import listener
from companion_memoryos.schemas import (
    ConsentState,
    ConversationRole,
    ExperienceEvidenceKind,
    MemoryReferenceFeedbackInput,
    MemoryScope,
    ReferenceFeedbackKind,
    Sensitivity,
)
from tests.test_chat_features import seed
from tests.test_journal import moment
from tests.test_romance_app import RecordingLLM, client_for, configure, message


def pixels() -> dict[str, Any]:
    # A synthetic pixel fixture, not evidence of a live model's artistic quality.
    rows = ["." * 32 for _ in range(32)]
    for y in range(7, 25):
        width = 4 if y < 11 else 12
        left = (32 - width) // 2
        rows[y] = "." * left + "0" + "1" * (width - 2) + "0" + "." * left
    return {"palette": ["#47614C", "#A6C4A0"], "rows": rows}


def visual_brief() -> dict[str, str]:
    return {
        "subject": "咖啡小火箭",
        "form": "厚杯身、右侧开口把手、底部小翼和喷焰。",
        "materials": "奶油陶瓷杯和绿色小翼，左上受光。",
        "story_detail": "杯身的一颗小星星。",
    }


def test_nook_packaged_art_matches_both_clients() -> None:
    root = Path(__file__).resolve().parents[1]
    web = root / "companion_agent/web/nook"
    flutter = root / "clients/xinyu_flutter/assets/nook"
    layout = json.loads((web / "room.json").read_text(encoding="utf-8"))
    for name in ("room.json", layout["image"]):
        assert (web / name).read_bytes() == (flutter / name).read_bytes()
    assert (web / layout["image"]).read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


class Artist(RecordingLLM):
    def __init__(self) -> None:
        super().__init__()
        self.drafts: list[list[ChatMessage]] = []
        self.paintings: list[list[ChatMessage]] = []
        self.patch: dict[str, Any] = {}
        self.invalid = False
        self.unchanged = False
        self.painting_error = False
        self.wait_stage = "design"
        self.entered: Event | None = None
        self.release: Event | None = None
        self.streams: list[Any] = []

    def generate(self, messages: list[ChatMessage]) -> ModelResponse:
        if "像素艺术家" not in messages[0].content:
            return super().generate(messages)
        self.streams.append(listener.get())
        data = json.loads(messages[-1].content)
        painting = "brief" in data
        (self.paintings if painting else self.drafts).append(messages)
        waiting = self.wait_stage == ("paint" if painting else "design")
        if self.entered and waiting:
            self.entered.set()
        if self.release and waiting:
            assert self.release.wait(10)
        if painting:
            output = {"art": self.patch.get("art", pixels())}
            if self.painting_error:
                output["sources"] = ["turn:invented"]
            return ModelResponse(text=json.dumps(output), model="synthetic-pixel-artist")
        source = data["sources"][0]
        old = next((o for o in data["objects"] if o["displayed"]), None)
        design = {
            "title": "咖啡小火箭",
            "meaning": "由你的咖啡火箭比喻想到的一盏小灯。",
            "sources": [source["ref"]],
            "reality_layer": source["reality_layer"],
            "zone": "desk",
            "slot": 0,
            "brief": visual_brief(),
            "update_id": old["id"] if old else None,
            **{k: v for k, v in self.patch.items() if k != "art"},
        }
        return ModelResponse(
            text="not json"
            if self.invalid
            else json.dumps({"object": None if self.unchanged else design}),
            model="synthetic-pixel-artist",
        )


def setup(tmp_path: Path, **settings: Any) -> tuple[Any, Artist, Any]:
    model = Artist()
    client = client_for(tmp_path, model)
    configure(client, nook_enabled=True, nook_daily_limit=12, **settings)
    return client, model, client.app.state.host


def create(client: Any) -> dict[str, Any]:
    response = client.post(
        "/api/nook/create",
        json={
            "conversation_id": message(client)["conversation_id"],
        },
    )
    assert response.status_code == 200, response.text
    worker = client.app.state.host.nook.worker
    if worker:
        worker.join(10)
        assert not worker.is_alive()
    data = client.get("/api/nook")
    assert data.status_code == 200, data.text
    return data.json()


def test_artist_creates_original_pixels_tracks_evidence_and_survives_restart(
    tmp_path: Path,
) -> None:
    client, model, host = setup(tmp_path)
    source = seed(host, "我是靠咖啡续航的小火箭。")
    data = create(client)
    assert data["status"] == "created"
    item = data["items"][0]
    assert item["art"] == pixels()
    assert item["sources"] == [f"turn:{source.id}"]
    assert item["evidence"][0]["content"] == source.content
    assert source.content not in model.drafts[0][0].content
    assert source.content in model.drafts[0][1].content
    assert model.streams == [None, None]
    painting = json.loads(model.paintings[0][-1].content)
    assert painting == {"brief": visual_brief(), "zone": "desk"}
    assert source.content not in model.paintings[0][-1].content
    restarted = client_for(tmp_path)
    assert restarted.get("/api/nook").json()["items"][0] == item


def test_update_timeline_and_hiding_are_not_memory_deletion(tmp_path: Path) -> None:
    client, model, host = setup(tmp_path)
    source = seed(host, "我是靠咖啡续航的小火箭。")
    first = create(client)
    item = first["items"][0]
    seed(host, "小火箭完成了这个项目。")
    model.patch = {"title": "完成任务的小火箭"}
    updated = create(client)
    assert updated["status"] == "updated" and len(updated["items"]) == 1
    assert updated["items"][0]["id"] == item["id"]
    assert json.loads(model.paintings[-1][-1].content)["previous_art"] == item["art"]
    before = client.get("/api/nook", params={"at": first["timeline"][0]}).json()
    assert before["items"][0]["title"] == "咖啡小火箭"
    assert len(updated["timeline"]) == 2
    path = f"/api/nook/objects/{item['id']}"
    assert client.put(path, json={"displayed": False}).status_code == 200
    assert not client.get("/api/nook").json()["items"][0]["displayed"]
    assert host.memory.store.get_turn(source.id, LOCAL_USER).content == source.content
    assert client.put(path, json={"displayed": True}).status_code == 200


@pytest.mark.parametrize("action", ["forget", "redact", "restrict"])
def test_source_loss_removes_every_sprite_and_historical_version(
    tmp_path: Path, action: str
) -> None:
    client, _, host = setup(tmp_path)
    source = seed(host, "我是靠咖啡续航的小火箭。")
    before = create(client)
    if action == "forget":
        host.memory.forget_turn(source.id, LOCAL_USER)
    elif action == "redact":
        with host.database.connection() as db:
            db.execute("UPDATE conversation_turns SET content='已更正' WHERE id=?", (source.id,))
    else:
        host.memory.record_reference_feedback(
            MemoryReferenceFeedbackInput(
                user_id=LOCAL_USER,
                scope=source.scope,
                kind=ReferenceFeedbackKind.DO_NOT_REFERENCE,
                evidence_kind=ExperienceEvidenceKind.TURN,
                evidence_id=source.id,
            )
        )
    data = client.get("/api/nook", params={"at": before["timeline"][0]}).json()
    assert data["items"] == [] and data["timeline"] == []
    with host.database.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM nook_versions").fetchone()[0] == 0


def test_correcting_a_memory_invalidates_its_keepsake(tmp_path: Path) -> None:
    client, _, host = setup(tmp_path)
    source = seed(host, "我是靠咖啡续航的小火箭。")
    saved = moment(client, source_ids=[source.id], content=source.content)
    assert create(client)["items"]
    response = client.put(
        f"/api/memories/{saved['id']}",
        json={
            "content": "小火箭是故事人物的比喻，不是我的经历。",
            "conversation_id": message(client)["conversation_id"],
        },
    )
    assert response.status_code == 200
    assert client.get("/api/nook").json()["items"] == []


def test_foreign_sensitive_assistant_and_unconsented_sources_never_reach_artist(
    tmp_path: Path,
) -> None:
    client, model, host = setup(tmp_path)
    own = seed(host, "我喜欢自己设计咖啡杯。")
    seed(host, "sensitive-secret", sensitivity=Sensitivity.SENSITIVE)
    revoked = seed(host, "unconsented-secret")
    with host.database.connection() as db:
        db.execute(
            "UPDATE conversation_turns SET consent=? WHERE id=?",
            (ConsentState.DENIED.value, revoked.id),
        )
    seed(host, "assistant-invented-secret", role=ConversationRole.ASSISTANT)
    seed(
        host,
        "foreign-secret",
        scope=MemoryScope(
            companion_id="other",
            relationship_id="other",
            conversation_id=own.scope.conversation_id,
        ),
    )
    assert create(client)["items"]
    prompt = model.drafts[0][1].content
    assert own.content in prompt and "secret" not in prompt


@pytest.mark.parametrize(
    "patch",
    [
        {"sources": ["turn:invented"]},
        {"reality_layer": "roleplay"},
        {"update_id": "another-object"},
        {"zone": "execute_code"},
        {"art": {"palette": ["#000000"], "rows": ["F" * 32] * 32}},
    ],
)
def test_invalid_or_fabricated_output_is_not_published(
    tmp_path: Path, patch: dict[str, Any]
) -> None:
    client, model, host = setup(tmp_path)
    seed(host, "我喜欢咖啡火箭。")
    model.patch = patch
    data = create(client)
    assert data["status"] == "failed" and data["items"] == []
    assert len(model.drafts) == 1


@pytest.mark.parametrize("stage", ["design", "paint"])
@pytest.mark.parametrize("change", ["forget", "disable", "hide"])
def test_late_generation_cannot_restore_revoked_or_hidden_content(
    tmp_path: Path, change: str, stage: str
) -> None:
    client, model, host = setup(tmp_path)
    source = seed(host, "我的咖啡火箭。")
    item = create(client)["items"][0]
    model.entered, model.release = Event(), Event()
    model.wait_stage = stage
    client.post("/api/nook/create", json={"conversation_id": message(client)["conversation_id"]})
    assert model.entered.wait(5)
    try:
        assert client.get("/api/nook").status_code == 200  # Model wait owns no app lock.
        if change == "forget":
            host.memory.forget_turn(source.id, LOCAL_USER)
        elif change == "disable":
            assert client.put("/api/nook/settings", json={"enabled": False}).status_code == 200
        else:
            assert (
                client.put(f"/api/nook/objects/{item['id']}", json={"displayed": False}).status_code
                == 200
            )
    finally:
        model.release.set()
        host.nook.worker.join(10)
    data = client.get("/api/nook").json()
    assert len(model.paintings) == (1 if stage == "design" else 2)
    if change == "forget":
        assert data["items"] == []
    else:
        assert len(data["timeline"]) == 1
    if change == "hide":
        assert data["items"][0]["displayed"] is False


def test_output_limit_is_explained_without_publishing_or_retrying(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, model, host = setup(tmp_path)
    seed(host, "我把自己的小杯子叫作咖啡火箭。")
    original = model.generate
    calls = 0

    def limited(messages: list[ChatMessage]) -> ModelResponse:
        nonlocal calls
        if "像素艺术家" in messages[0].content:
            calls += 1
            raise MainLLMError("nook_output_limit")
        return original(messages)

    monkeypatch.setattr(model, "generate", limited)
    room = create(client)
    assert room["status"] == "output_limit" and "提高输出" in room["message"]
    assert room["items"] == [] and room["timeline"] == []
    assert room["remaining_today"] == 11 and calls == 1


def test_failed_call_budget_survives_restart_and_no_automatic_retry(tmp_path: Path) -> None:
    client, model, host = setup(tmp_path)
    client.put("/api/nook/settings", json={"enabled": True, "daily_limit": 1})
    seed(host, "我是靠咖啡续航的小火箭。")
    model.invalid = True
    assert create(client)["status"] == "failed"
    assert host.nook.start(message(client)["conversation_id"]) == "limit"
    assert len(model.drafts) == 1
    restarted = client_for(tmp_path, model)
    response = restarted.post(
        "/api/nook/create", json={"conversation_id": message(restarted)["conversation_id"]}
    )
    assert response.json()["status"] == "limit"
    assert restarted.get("/api/nook").json()["remaining_today"] == 0


def test_offline_and_unconsented_runs_do_not_fake_art(tmp_path: Path) -> None:
    client = client_for(tmp_path)
    configure(client, nook_enabled=True)
    seed(client.app.state.host, "我喜欢向日葵。")
    assert create(client)["status"] == "offline"
    configure(client, storage_consent=False)
    assert client.get("/api/nook").status_code != 200


def test_chat_schedules_art_without_leaking_into_stream_and_retries_do_not_duplicate(
    tmp_path: Path,
) -> None:
    client, model, host = setup(tmp_path)
    payload = message(client, "我是一只靠咖啡续航的小火箭。")
    response = client.post("/api/chat/stream", json=payload)
    assert response.status_code == 200
    host.nook.worker.join(10)
    assert client.get("/api/nook").json()["items"]
    assert '"palette"' not in response.text and model.streams == [None, None]
    client.post("/api/chat/stream", json=payload)
    assert len(model.drafts) == 1


def test_unchanged_plan_never_calls_painter(tmp_path: Path) -> None:
    client, model, host = setup(tmp_path)
    seed(host, "今天和往常一样。")
    model.unchanged = True
    room = create(client)
    assert room["status"] == "unchanged" and room["items"] == []
    assert len(model.drafts) == 1 and model.paintings == []


def test_unwrapped_blueprint_requires_complete_strict_fields() -> None:
    blueprint = {
        "title": "合成设计",
        "meaning": "合成测试中的纪念品。",
        "sources": ["turn:synthetic"],
        "reality_layer": "real_world",
        "zone": "desk",
        "slot": 0,
        "brief": visual_brief(),
    }
    assert parse_nook_plan(json.dumps(blueprint)) == parse_nook_plan(
        json.dumps({"object": blueprint})
    )
    for bad in (
        {k: v for k, v in blueprint.items() if k != "sources"},
        {**blueprint, "art": pixels()},
        {**blueprint, "brief": {**visual_brief(), "form": "长" * 241}},
        {"object": blueprint, "sources": ["turn:invented"]},
    ):
        with pytest.raises(ValueError):
            parse_nook_plan(json.dumps(bad))


def test_painter_cannot_replace_selection_or_publish_partial_plan(tmp_path: Path) -> None:
    client, model, host = setup(tmp_path)
    seed(host, "我给自己的咖啡杯起了名字。")
    model.painting_error = True
    room = create(client)
    assert room["status"] == "failed" and room["items"] == [] and room["timeline"] == []
    assert len(model.drafts) == len(model.paintings) == 1


def test_pixel_schema_rejects_active_content_empty_and_oversized_art() -> None:
    for art in (
        {"palette": ["url(https://example.com)"], "rows": ["0" * 32] * 32},
        {"palette": ["#000000"], "rows": ["." * 32] * 32},
        {"palette": ["#000000"], "rows": ["0" * 33] * 32},
    ):
        with pytest.raises(ValidationError):
            PixelArt.model_validate(art)


def test_timeline_before_first_creation_is_empty_and_naive_time_rejected(tmp_path: Path) -> None:
    client, _, host = setup(tmp_path)
    seed(host, "小火箭。")
    create(client)
    past = datetime.now(UTC) - timedelta(days=10)
    assert client.get("/api/nook", params={"at": past.isoformat()}).json()["items"] == []
    assert client.get("/api/nook?at=2026-01-01T00:00:00").status_code == 409
