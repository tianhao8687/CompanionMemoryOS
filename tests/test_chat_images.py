"""Real HTTP/application paths with synthetic PNGs and a recording model, never live calls."""

import base64
import json
import struct
import zlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from companion_agent.app import LOCAL_USER, create_app
from companion_agent.deepseek import DeepSeekConfig, DeepSeekLLM
from companion_agent.images import MAX_IMAGE_BYTES, validate_png
from companion_agent.local_data import apply_pending_restore, backup_bytes, stage_restore
from companion_memoryos.schemas import TurnDeletionState
from tests.test_deepseek import provider
from tests.test_romance_app import RecordingLLM, client_for, configure, message


def png(width: int = 2, height: int = 2) -> bytes:
    def chunk(kind: bytes, content: bytes) -> bytes:
        return (
            struct.pack(">I", len(content))
            + kind
            + content
            + struct.pack(">I", zlib.crc32(kind + content))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress((b"\0" + b"\xff\0\0\xff" * width) * height))
        + chunk(b"IEND", b"")
    )


def upload(client: TestClient, purpose: str = "chat") -> str:
    reply = client.post(f"/api/images?purpose={purpose}", content=png())
    assert reply.status_code == 200, reply.text
    return str(reply.json()["id"])


def test_image_chat_retry_history_restart_and_wire(tmp_path: Path) -> None:
    model = RecordingLLM()
    client = client_for(tmp_path, model)
    configure(client, model_mode="api")
    image = upload(client)
    payload = {**message(client, ""), "image_ids": [image]}
    model.fail = True
    assert client.post("/api/chat", json=payload).status_code == 502
    model.fail = False
    reply = client.post("/api/chat", json=payload)
    assert reply.status_code == 200, reply.text
    assert reply.json()["user"]["image_ids"] == [image]
    last = model.inputs[-1][-1]
    assert last.image_urls == ["data:image/png;base64," + base64.b64encode(png()).decode()]
    assert "base64" not in json.dumps(last.model_dump())
    host = client.app.state.host
    wire = DeepSeekLLM(host.settings.deepseek, api_key="synthetic").payload(model.inputs[-1])
    assert wire["messages"][-1]["content"][1]["type"] == "image_url"
    assert "source_turn_id" not in json.dumps(wire)
    assert client.post("/api/chat", json=payload).json()["reused"]
    assert len(model.inputs) == 2
    other = upload(client)
    assert client.post("/api/chat", json={**payload, "image_ids": [other]}).status_code == 409
    restarted = client_for(tmp_path, model)
    assert restarted.get(f"/api/images/{other}").status_code == 404
    history = restarted.get(f"/api/conversations/{payload['conversation_id']}/messages").json()[
        "messages"
    ]
    assert len(history) == 2 and history[0]["image_ids"] == [image]
    assert restarted.get(f"/api/images/{image}").content == png()
    assert (
        restarted.post("/api/chat", json=message(restarted, "继续看看", "followup")).status_code
        == 200
    )
    assert any(part.image_urls for part in model.inputs[-1][:-1])
    conversation = restarted.post("/api/conversations", json={}).json()["id"]
    assert (
        restarted.post(
            "/api/chat", json={**message(restarted, "你好", "new"), "conversation_id": conversation}
        ).status_code
        == 200
    )
    assert not any(part.image_urls for part in model.inputs[-1])


def test_appearance_and_both_profiles_survive_backup_but_are_not_vision(tmp_path: Path) -> None:
    model = RecordingLLM()
    source = tmp_path / "source"
    client = client_for(source, model)
    settings = configure(
        client,
        style="custom",
        custom_style="花艺师，温顺。",
        user_persona="我是住在海边的画家。",
        model_mode="api",
    )
    ids = {
        field: upload(client, purpose)
        for field, purpose in (
            ("background_image", "background"),
            ("user_avatar", "user_avatar"),
            ("companion_avatar", "companion_avatar"),
        )
    }
    settings.update(ids)
    assert client.put("/api/settings", json={"settings": settings}).status_code == 200
    assert client.post("/api/chat", json=message(client)).status_code == 200
    assert "我是住在海边的画家。" in model.inputs[-1][0].content
    assert not any(part.image_urls for part in model.inputs[-1])
    for image in ids.values():
        assert image not in model.inputs[-1][0].content
        assert client.delete(f"/api/images/{image}").status_code == 409
    target = tmp_path / "restored"
    target.mkdir()
    stage_restore(target, backup_bytes(client.app.state.host.database))
    apply_pending_restore(target)
    restored = client_for(target, model)
    assert (
        restored.get("/api/bootstrap").json()["settings"]["user_persona"]
        == settings["user_persona"]
    )
    for image in ids.values():
        assert restored.get(f"/api/images/{image}").content == png()
    settings["background_image"] = None
    assert restored.put("/api/settings", json={"settings": settings}).status_code == 200
    assert restored.get(f"/api/images/{ids['background_image']}").status_code == 404


@pytest.mark.parametrize(
    "change",
    [
        "deletion_state='forgotten'",
        "consent='denied'",
        'metadata_json=\'{"content_redacted_at":"synthetic"}\'',
    ],
)
def test_forgetting_or_redacting_source_deletes_image_bytes(tmp_path: Path, change: str) -> None:
    model = RecordingLLM()
    client = client_for(tmp_path, model)
    configure(client, model_mode="api")
    image = upload(client)
    result = client.post("/api/chat", json={**message(client, "这张照片"), "image_ids": [image]})
    assert result.status_code == 200, result.text
    source = result.json()["user"]["id"]
    host = client.app.state.host
    with host.database.connection() as db:
        db.execute(f"UPDATE conversation_turns SET {change} WHERE id=?", (source,))
        assert db.execute("SELECT 1 FROM romance_images WHERE id=?", (image,)).fetchone() is None
    assert client.get(f"/api/images/{image}").status_code == 404
    assert host.images.ids(host.memory.store.get_turn(source, LOCAL_USER)) == []


def test_image_auth_validation_capability_and_scope(tmp_path: Path) -> None:
    model = RecordingLLM()
    client = client_for(tmp_path, model)
    configure(client)
    image = upload(client)
    payload = {**message(client), "image_ids": [image]}
    assert client.post("/api/chat", json=payload).status_code == 422
    assert not model.inputs  # Offline never pretends to see an image.
    assert client.post("/api/images?purpose=background", content=b"not an image").status_code == 422
    assert (
        client.post(
            "/api/images?purpose=background", content=b"x" * (MAX_IMAGE_BYTES + 1)
        ).status_code
        == 413
    )
    broken = bytearray(png())
    broken[-5] ^= 1
    assert client.post("/api/images?purpose=chat", content=bytes(broken)).status_code == 422
    configure(client, model_mode="api")
    avatar = upload(client, "user_avatar")
    assert client.post("/api/chat", json={**payload, "image_ids": [avatar]}).status_code == 409
    assert client.post("/api/chat", json=payload).status_code == 200
    assert client.post("/api/chat", json={**payload, "request_id": "another"}).status_code == 409
    assert client.delete(f"/api/images/{image}").status_code == 409
    native = TestClient(
        create_app(tmp_path / "native", client_token="synthetic"), base_url="http://127.0.0.1"
    )
    assert native.get(f"/api/images/{image}").status_code == 401
    unauthed = TestClient(client.app, base_url="http://127.0.0.1")
    assert unauthed.get(f"/api/images/{image}").status_code == 401


def test_natural_forgetting_removes_photo_and_reply_across_restart(tmp_path: Path) -> None:
    model = RecordingLLM()
    client = client_for(tmp_path, model)
    configure(client, model_mode="api")
    image = upload(client)
    payload = {**message(client, "备用门卡放在玄关藤篮最下层。"), "image_ids": [image]}
    result = client.post("/api/chat", json=payload)
    assert result.status_code == 200, result.text
    saved = result.json()
    assert model.inputs[-1][-1].image_urls
    forgotten = client.post(
        "/api/chat", json=message(client, "请把备用门卡放在哪里这件事忘掉。", "forget")
    )
    assert forgotten.status_code == 200, forgotten.text
    assert not any(part.image_urls for part in model.inputs[-1])
    assert client.get(f"/api/images/{image}").status_code == 404
    with client.app.state.host.database.connection() as db:
        assert db.execute("SELECT 1 FROM romance_images WHERE id=?", (image,)).fetchone() is None
    restarted = client_for(tmp_path, model)
    for role in ("user", "assistant"):
        turn = restarted.app.state.host.memory.store.get_turn(saved[role]["id"], LOCAL_USER)
        assert turn.deletion_state is TurnDeletionState.FORGOTTEN
        assert turn.content == "[已遗忘指定位置]"
    history = restarted.get(f"/api/conversations/{payload['conversation_id']}/messages").json()[
        "messages"
    ]
    assert {saved["user"]["id"], saved["assistant"]["id"]}.isdisjoint(
        item["id"] for item in history
    )
    assert restarted.get(f"/api/images/{image}").status_code == 404
    recalled = restarted.post("/api/chat", json=message(restarted, "备用门卡放在哪里？", "recall"))
    assert recalled.status_code == 200, recalled.text
    assert not any(part.image_urls or "藤篮" in part.content for part in model.inputs[-1])


def test_bounded_vision_history_and_discarded_draft(tmp_path: Path) -> None:
    model = RecordingLLM()
    client = client_for(tmp_path, model)
    configure(client, model_mode="api")
    draft = upload(client)
    assert client.delete(f"/api/images/{draft}").status_code == 200
    assert client.get(f"/api/images/{draft}").status_code == 404
    for index in range(3):
        ids = [upload(client) for _ in range(2)]
        result = client.post(
            "/api/chat", json={**message(client, "看看图片", str(index)), "image_ids": ids}
        )
        assert result.status_code == 200, result.text
    assert sum(len(part.image_urls) for part in model.inputs[-1]) == 4
    assert any("部分历史图片本轮未附带" in part.content for part in model.inputs[-1])
    with pytest.raises(ValueError):
        validate_png(png(2049, 1))


def test_image_reaches_local_http_provider_through_application(tmp_path: Path) -> None:
    with provider() as (url, requests):
        config = DeepSeekConfig(base_url=url, max_tokens=128)
        model = DeepSeekLLM(config, api_key="synthetic-vision-test", use_environment=False)
        client = TestClient(
            create_app(tmp_path, llm=model),
            base_url="http://127.0.0.1",
            headers={"X-Companion-Client": "local-web"},
        )
        client.get("/")
        settings = client.get("/api/bootstrap").json()["settings"]
        settings.update(
            model_mode="api",
            vision="enabled",
            storage_consent=True,
            model_consent=True,
            deepseek=config.model_dump(),
        )
        saved = client.put(
            "/api/settings", json={"settings": settings, "api_key": "synthetic-vision-test"}
        )
        assert saved.status_code == 200, saved.text
        image = upload(client)
        reply = client.post(
            "/api/chat", json={**message(client, "图里是什么？"), "image_ids": [image]}
        )
        assert reply.status_code == 200, reply.text
        assert len(requests) == 1
        parts = requests[0]["body"]["messages"][-1]["content"]
        assert parts[0] == {"type": "text", "text": "图里是什么？"}
        assert (
            parts[1]["image_url"]["url"]
            == "data:image/png;base64," + base64.b64encode(png()).decode()
        )
