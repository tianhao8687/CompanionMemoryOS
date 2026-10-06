"""Keepsake identity, provenance and ordinary chat share the actual application."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from companion_agent.app import LOCAL_USER
from companion_agent.evidence_policy import filter_recent_turns
from companion_agent.nook_art import NookBrief, NookDesign, PixelArt
from companion_agent.nook_drawing import render_drawing
from companion_memoryos.schemas import (
    ConsentState,
    ExperienceEvidenceKind,
    MemoryReferenceFeedbackInput,
    MemoryUsePlan,
    ProcessTurnRequest,
    ReferenceFeedbackKind,
)
from tests.test_chat_features import seed
from tests.test_nook_drawing import material_drawing
from tests.test_romance_app import RecordingLLM, client_for, configure


def put_object(host: Any, title: str = "黑白小猫", slot: int = 0) -> dict[str, Any]:
    turn = seed(
        host,
        f"我们共同创作了一只虚构的{title}，它只是故事里的角色。",
        metadata={"process_reality_layer": "roleplay"},
    )
    source = host.nook.source(f"turn:{turn.id}")
    drawing = material_drawing()
    design = NookDesign(
        title=title,
        meaning="共同创作的角色，趴在小窝里。",
        sources=[source["ref"]],
        reality_layer="roleplay",
        zone="desk",
        slot=slot,
        art=PixelArt.model_validate(render_drawing(drawing)),
    )
    brief = NookBrief(subject=title, form="低低趴着", materials="黑白短毛", story_detail="白爪")
    host.nook.commit(
        design,
        [source],
        {source["ref"]: source["fingerprint"]},
        host.nook.room()["items"],
        brief=brief,
        drawing=drawing,
    )
    return next(o for o in host.nook.room()["items"] if o["title"] == title)


def test_keepsake_enters_cross_session_chat_as_data_with_deletion_lineage(tmp_path: Path) -> None:
    model = RecordingLLM()
    client = client_for(tmp_path, model)
    configure(client)
    host = client.app.state.host
    item = put_object(host)
    conversation = client.post("/api/conversations").json()["id"]
    response = client.post(
        "/api/chat",
        json={
            "conversation_id": conversation,
            "request_id": "cat-followup",
            "content": "我们聊聊小窝里的黑白小猫吧。",
        },
    )
    assert response.status_code == 200, response.text
    sent = model.inputs[-1]
    data = next(m.content for m in sent if "[APPLICATION KEEPSAKES]" in m.content)
    assert "黑白小猫" in data and "roleplay" in data and "palette" not in data
    assert "黑白小猫" not in sent[0].content
    reply = host.memory.store.get_turn(response.json()["assistant"]["id"], LOCAL_USER)
    origin = item["sources"][0].split(":", 1)[1]
    assert origin in reply.metadata["context_turn_ids"]
    host.memory.forget_turn(origin, LOCAL_USER)
    assert not host.nook.room()["items"]
    assert not filter_recent_turns(
        host.memory, host.key, [reply], MemoryUsePlan(), datetime.now(UTC)
    )


def test_artistic_description_is_not_injected_into_ordinary_chat(tmp_path: Path) -> None:
    model = RecordingLLM()
    client = client_for(tmp_path, model)
    configure(client)
    host = client.app.state.host
    item = put_object(host)
    conversation = client.post("/api/conversations").json()["id"]
    request = {
        "conversation_id": conversation,
        "request_id": "normal",
        "content": "我想和你聊两句。",
    }
    assert client.post("/api/chat", json=request).status_code == 200
    assert not any("[APPLICATION KEEPSAKES]" in m.content for m in model.inputs[-1])
    request.update(request_id="artwork", content="小窝里的黑白小猫有什么故事？")
    assert client.post("/api/chat", json=request).status_code == 200
    data = next(m.content for m in model.inputs[-1] if "[APPLICATION KEEPSAKES]" in m.content)
    assert "artistic_interpretation_not_testimony" in data
    assert item["sources"][0] in data


@pytest.mark.parametrize("loss", ["correct", "restrict"])
def test_invalid_source_never_enters_chat_or_historical_room(tmp_path: Path, loss: str) -> None:
    client = client_for(tmp_path)
    configure(client)
    host = client.app.state.host
    item = put_object(host)
    origin = item["sources"][0].split(":", 1)[1]
    turn = host.memory.store.get_turn(origin, LOCAL_USER)
    if loss == "correct":
        with host.database.connection() as db:
            db.execute(
                "UPDATE conversation_turns SET content=? WHERE id=?", ("更正了这个故事", origin)
            )
    else:
        host.memory.record_reference_feedback(
            MemoryReferenceFeedbackInput(
                user_id=LOCAL_USER,
                scope=turn.scope,
                kind=ReferenceFeedbackKind.DO_NOT_REFERENCE,
                evidence_kind=ExperienceEvidenceKind.TURN,
                evidence_id=origin,
            )
        )
    request = ProcessTurnRequest(
        user_id=LOCAL_USER,
        scope=turn.scope,
        content="那只猫呢？",
        consent=ConsentState.GRANTED,
        idempotency_key="source-loss",
    )
    assert host.nook.chat_context(request) == ({}, [])
    assert not host.nook.room()["timeline"]


def test_original_source_is_private_validated_and_survives_restart(tmp_path: Path) -> None:
    client = client_for(tmp_path)
    configure(client)
    host = client.app.state.host
    item = put_object(host)
    assert "drawing" not in item
    private = host.nook.room(include_source=True)["items"][0]
    assert render_drawing(private["drawing"]) == item["art"]
    restarted = client_for(tmp_path)
    assert restarted.app.state.host.nook.room(include_source=True)["items"][0] == private
    with pytest.raises(ValueError, match="does not match"):
        host.nook.commit(
            NookDesign.model_validate(
                {
                    k: item[k]
                    for k in ("title", "meaning", "sources", "reality_layer", "zone", "slot", "art")
                }
            ),
            [host.nook.source(ref) for ref in item["sources"]],
            {},
            [],
            drawing={**material_drawing(), "palette": ["#FFFFFF"] * 4},
        )


def test_treasured_art_cannot_be_overwritten_or_displaced_by_auto_creation(tmp_path: Path) -> None:
    client = client_for(tmp_path)
    configure(client)
    host = client.app.state.host
    initial = []
    for index in range(3):
        item = put_object(host, f"猫{index}", index)
        initial.append(item)
        assert (
            client.put(f"/api/nook/objects/{item['id']}", json={"pinned": True}).status_code == 200
        )
    fourth = put_object(host, "新猫")
    room = host.nook.room()
    assert not fourth["displayed"]
    assert {o["id"] for o in room["items"] if o["displayed"]} == {o["id"] for o in initial}
    original = initial[0]
    design = NookDesign.model_validate(
        {
            **{
                k: original[k]
                for k in ("title", "meaning", "sources", "reality_layer", "zone", "slot", "art")
            },
            "update_id": original["id"],
        }
    )
    with pytest.raises(ValueError, match="treasured"):
        host.nook.commit(
            design, [host.nook.source(ref) for ref in original["sources"]], {}, room["items"]
        )
    client.put(f"/api/nook/objects/{original['id']}", json={"pinned": False})
    assert not host.nook.room()["items"][0]["pinned"]


def test_four_pixel_stroke_is_supported_without_altering_source_or_palette() -> None:
    source = {
        "size": 48,
        "outline": -1,
        "palette": ["#101010"],
        "layers": [{"name": "tail", "outline": -1, "ops": [["line", 0, 4, [[10, 10], [10, 20]]]]}],
    }
    before = json.dumps(source)
    result = render_drawing(source)
    assert sum(c == "0" for c in result["rows"][15]) == 4
    assert json.dumps(source) == before
    source["layers"][0]["ops"][0][2] = 49
    with pytest.raises(ValueError):
        render_drawing(source)


def test_existing_layered_keepsake_is_updated_with_two_calls_and_keeps_original(
    tmp_path: Path,
) -> None:
    from companion_agent.context import ChatMessage
    from companion_agent.llm import ModelResponse
    from tests.test_memory_nook import Artist, create

    class LayerArtist(Artist):
        def generate(self, messages: list[ChatMessage]) -> ModelResponse:
            data = json.loads(messages[-1].content)
            if "drawing" in data:
                self.paintings.append(messages)
                return ModelResponse(
                    text='{"edits":[{"layer":1,"ops":[["pixel",2,40,43]]}]}',
                    model="synthetic-layer-artist",
                )
            return super().generate(messages)

    model = LayerArtist()
    client = client_for(tmp_path, model)
    configure(client, nook_enabled=True)
    host = client.app.state.host
    old = put_object(host)
    before = host.nook.room(include_source=True)["items"][0]
    room = create(client)
    assert room["status"] == "updated"
    assert len(model.drafts) == len(model.paintings) == 1
    new = host.nook.room(include_source=True)["items"][0]
    assert new["id"] == old["id"]
    assert new["drawing"]["layers"][0] == before["drawing"]["layers"][0]
    assert new["art"]["rows"][43][40] == "2"
    assert (
        host.nook.room(datetime.fromisoformat(old["created_at"]))["items"][0]["art"] == old["art"]
    )
