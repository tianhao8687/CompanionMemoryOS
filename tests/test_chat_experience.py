"""Bookmarks and drafts use the original store, with live source validation."""

from pathlib import Path

from companion_agent.app import LOCAL_USER
from companion_agent.romance import RomanceSettings, romantic_rules
from tests.test_chat_features import seed
from tests.test_chat_images import png
from tests.test_romance_app import client_for, configure


def test_bookmarks_atomic_batch_restart_and_forget(tmp_path: Path) -> None:
    client = client_for(tmp_path)
    configure(client)
    host = client.app.state.host
    a = seed(host, "收藏原文，不能另建长期记忆")
    b = seed(host, "第二条")
    foreign = seed(host, "另一个人的消息", user_id="foreign", actor_id="foreign")
    response = client.put("/api/bookmarks", json={"ids": [a.id, foreign.id]})
    assert response.status_code == 422
    assert client.get("/api/bookmarks").json()["items"] == []
    for _ in range(2):
        assert client.put("/api/bookmarks", json={"ids": [a.id, b.id, a.id]}).status_code == 200
    page = client.get("/api/bookmarks?limit=1").json()
    assert page["has_more"] and len(page["items"]) == 1
    assert page["items"][0]["message"]["bookmarked"]
    assert len(client.get("/api/bookmarks?offset=1").json()["items"]) == 1
    with host.database.connection() as db:
        assert db.execute("SELECT count(*) FROM memories").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM chat_bookmarks").fetchone()[0] == 2
    client = client_for(tmp_path)
    assert len(client.get("/api/bookmarks").json()["items"]) == 2
    client.app.state.host.memory.forget_turn(a.id, LOCAL_USER)
    remaining = client.get("/api/bookmarks").json()["items"]
    assert [item["message"]["id"] for item in remaining] == [b.id]
    assert client.put("/api/bookmarks", json={"ids": [a.id]}).status_code == 422
    assert client.put("/api/bookmarks", json={"ids": [b.id], "saved": False}).status_code == 200
    assert client.get("/api/bookmarks").json()["items"] == []


def test_draft_anchor_photo_restart_and_source_cleanup(tmp_path: Path) -> None:
    client = client_for(tmp_path)
    configure(client)
    host = client.app.state.host
    source = seed(host, "作为阅读位置和引用来源")
    conversation = source.scope.conversation_id
    path = f"/api/conversations/{conversation}/ui-state"
    photo = client.post("/api/images?purpose=chat", content=png()).json()["id"]
    value = {
        "is_current": True,
        "text": "未发送的合成草稿",
        "quote_id": source.id,
        "image_ids": [photo],
        "anchor_id": source.id,
        "anchor_y": -14.5,
        "scroll_offset": 1400,
        "last_sequence": source.server_sequence,
    }
    assert client.put(path, json=value).status_code == 200
    other = host.new_conversation()["id"]
    assert client.get(f"/api/conversations/{other}/ui-state").json()["text"] == ""
    assert client.put(f"/api/conversations/{other}/ui-state", json=value).status_code == 422
    client = client_for(tmp_path)
    assert client.get(path).json() == value
    assert client.get(f"/api/images/{photo}").status_code == 200
    host = client.app.state.host
    with host.database.connection() as db:
        assert db.execute("SELECT count(*) FROM conversation_turns").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM memories").fetchone()[0] == 0
    host.memory.forget_turn(source.id, LOCAL_USER)
    restored = client.get(path).json()
    assert restored["quote_id"] is None and restored["anchor_id"] is None
    assert restored["scroll_offset"] == 0 and restored["text"] == value["text"]
    # A stale reader must not block saving a newer handwritten draft after forgetting.
    assert client.put(path, json={**value, "text": "更新后的草稿"}).status_code == 200
    assert client.get(path).json()["anchor_id"] is None
    assert client.get(path).json()["text"] == "更新后的草稿"
    assert client.put(path, json={"text": "x" * 6001}).status_code == 422
    assert client.put(path, json={"scroll_offset": -1}).status_code == 422


def test_ui_consent_withdrawal_clears_private_drafts_and_bookmarks(tmp_path: Path) -> None:
    client = client_for(tmp_path)
    configure(client)
    source = seed(client.app.state.host, "合成资料")
    path = f"/api/conversations/{source.scope.conversation_id}/ui-state"
    assert client.put(path, json={"text": "草稿"}).status_code == 200
    assert client.put("/api/bookmarks", json={"ids": [source.id]}).status_code == 200
    settings = client.get("/api/bootstrap").json()["settings"]
    settings["storage_consent"] = False
    assert client.put("/api/settings", json={"settings": settings}).status_code == 200
    assert client.get(path).json()["text"] == ""
    assert client.put(path, json={"text": "不可保存"}).status_code == 422
    with client.app.state.host.database.connection() as db:
        assert db.execute("SELECT count(*) FROM chat_ui_state").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM chat_bookmarks").fetchone()[0] == 0


def test_natural_rhythm_is_presentation_not_a_personality_override() -> None:
    setting = RomanceSettings(style="custom", custom_style="安静顺从，不抬杠。")
    rules = romantic_rules(setting)
    assert "[CHAT PRESENTATION]" in rules and "安静顺从，不抬杠。" in rules
    assert "不设固定段数或问题数量" in rules and "温柔、细腻，有一点俏皮" not in rules
    assert "[CHAT PRESENTATION]" not in romantic_rules(
        setting.model_copy(update={"natural_chat": False})
    )
