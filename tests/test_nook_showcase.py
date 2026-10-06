from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from companion_agent.journal import MomentInput
from companion_agent.showcase import collection, showcase_app
from tests.test_romance_app import client_for, configure


def test_curated_collection_uses_normal_sources_and_preserves_user_changes(tmp_path: Path) -> None:
    app = showcase_app(tmp_path)
    host = app.state.host
    try:
        room = host.nook.room()
        assert len(room["items"]) == 5
        assert all(o["pinned"] and o["displayed"] for o in room["items"])
        assert all(o["reality_layer"] == "roleplay" for o in room["items"])
        for record, item in zip(collection(), room["items"], strict=True):
            image = files("companion_agent").joinpath("showcase_assets/nook", record["image"])
            assert hashlib.sha256(image.read_bytes()).hexdigest() == record["sha256"]
            assert item["art"] == record["art"]
            assert any(s["conversation_id"] for s in item["evidence"])
        host.nook.visibility(room["items"][0]["id"], False)
        restarted = showcase_app(tmp_path).state.host
        try:
            items = restarted.nook.room()["items"]
            assert len(items) == 5 and not items[0]["displayed"]
            assert all(o["id"] == old["id"] for o, old in zip(items, room["items"], strict=True))
        finally:
            restarted.memory.close_indexer()
            restarted.nook.close()
        reference = room["items"][1]["sources"][0].split(":", 1)[1]
        host.memory.forget(reference, host.key.user_id)
        assert len(host.nook.room()["items"]) == 4
    finally:
        host.memory.close_indexer()
        host.nook.close()


def test_showcase_refuses_unmarked_application_data(tmp_path: Path) -> None:
    (tmp_path / "existing.txt").write_text("keep me")
    with pytest.raises(ValueError, match="empty directory"):
        showcase_app(tmp_path)
    assert list(tmp_path.iterdir()) == [tmp_path / "existing.txt"]


def test_today_fictional_journal_is_an_immediately_usable_source(tmp_path: Path) -> None:
    client = client_for(tmp_path)
    configure(client)
    host = client.app.state.host
    entry = host.journal.moment(
        MomentInput(
            request_id="fictional-cat",
            conversation_id=host.conversations()[0]["id"],
            title="小窝的虚构小猫",
            content="我们为小窝创作了一只虚构的小猫。",
            happened_on=datetime.now(ZoneInfo(host.settings.calendar_timezone)).date(),
            reality_layer="roleplay",
        )
    )
    assert datetime.fromisoformat(entry["event_at"]) <= datetime.now(UTC)
    for ref in ["memory:" + entry["id"], "turn:" + entry["evidence_turn_ids"][0]]:
        assert host.nook.source(ref)["reality_layer"] == "roleplay"
