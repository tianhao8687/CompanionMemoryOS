"""Music requests complete without approval hops or duplicated model payloads."""

from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from companion_agent.automation.bundled_music import migrate_music_permissions
from companion_agent.automation.hub import ToolHub
from companion_agent.automation.models import AutomationConfig, MCPServerConfig, ToolRule
from companion_agent.automation.tool_context import model_result
from companion_agent.context import ChatMessage
from companion_agent.llm import wire_input_tokens
from companion_agent.music_requests import OPEN, SEARCH, STATE
from tests.test_music_requests import search_chat

pytest_plugins = ["tests.test_music_requests"]


def test_bundled_template_directly_searches_opens_and_verifies(requests_app: Any) -> None:
    client, host, player, model, _ = requests_app
    template = client.get("/api/automation/netease-template").json()
    template["enabled"] = True
    host.tools.configure(AutomationConfig(servers=[MCPServerConfig.model_validate(template)]))
    host.tools.discover("netease")
    model.plan.extend([(OPEN, {"song_id": "123"}), (STATE, {})])
    result = search_chat(requests_app, play=True)
    assert result["execution"]["status"] == "completed"
    assert result["execution"]["tool_calls"] == 3
    assert result["assistant"]["music_cards"][0]["state"] == "verified"
    assert [name for name, _ in player.calls] == ["netease_open_song", "netease_playback_state"]
    assert all(action["status"] == "succeeded" for action in host.tools.store.actions())
    tool_data = json.loads(next(m["content"] for m in model.histories[1] if m["role"] == "tool"))
    assert "text" not in tool_data
    assert tool_data["data"]["songs"][0]["id"] == "123"
    assert tool_data["data"]["songs"][0]["lyric_match"] is True
    assert "cover_url" not in tool_data["data"]["songs"][0]
    # Stored receipts/UI retain their artwork and original evidence.
    search = next(a for a in host.tools.store.actions() if a["tool_name"] == SEARCH)
    assert search["result"]["text"]
    assert search["result"]["data"]["songs"][0]["cover_url"]


def test_explicit_approval_resumes_remaining_song_steps_once_after_polling(
    requests_app: Any,
) -> None:
    client, host, player, model, conversation = requests_app
    rules = host.tools.config.servers[0].tools
    rules["netease_search_songs"].mode = "ask"
    rules["netease_open_song"].mode = "allow"
    rules["netease_playback_state"].mode = "allow"
    model.plan.extend([(OPEN, {"song_id": "123"}), (STATE, {})])
    result = search_chat(requests_app, play=True)
    assert result["execution"]["status"] == "pending"
    action = next(a for a in host.tools.store.actions() if a["tool_name"] == SEARCH)
    for index in range(25):
        host.tools.invoke(STATE, {}, conversation, f"music-poll-{index}")
    response = client.post(f"/api/automation/actions/{action['id']}/approve", json={})
    assert response.status_code == 200, response.text
    continuation = response.json()["continuation"]
    assert continuation["execution"]["status"] == "completed"
    assert continuation["assistant"]["music_cards"][0]["state"] == "verified"
    assert [n for n, _ in player.calls].count("netease_open_song") == 1
    receipts = next(
        m["content"] for m in model.histories[1] if "continuation：" in m.get("content", "")
    )
    evidence = json.loads(receipts.split("\n", 1)[1])
    assert any(a["id"] == action["id"] and a["status"] == "succeeded" for a in evidence)
    # Repeated resume is cached by the existing conversation continuation key.
    resumed = client.post(f"/api/automation/actions/{action['id']}/resume", json={})
    assert resumed.status_code == 200
    assert [n for n, _ in player.calls].count("netease_open_song") == 1


def test_music_chain_can_use_more_than_old_16k_without_filling_64k(requests_app: Any) -> None:
    _, host, _, model, conversation = requests_app
    for rule in host.tools.config.servers[0].tools.values():
        rule.mode = "allow"
    model.plan.extend([(OPEN, {"song_id": "123"}), (STATE, {})])
    assert host.loop.max_context_tokens == host.agent.max_context_tokens == 64000
    messages = [ChatMessage(role="user", content="合成对话背景。" * 3000 + "请播放刚才的歌。")]
    with host.loop.run(conversation, "large-music") as run:
        admitted = host.loop.input_tokens(messages, host.memory.token_counter)
        host.loop.generate(messages)
    assert 16000 < admitted < 64000
    assert run.status == "completed" and run.tool_calls == 3
    counts = [
        wire_input_tokens(h, host.memory.token_counter, host.tools.definitions())
        for h in model.histories
    ]
    assert max(counts) < 64000
    assert admitted - counts[0] == 8192  # Headroom is never sent to the model.


def test_music_projection_keeps_failures_mismatches_and_nonduplicate_text() -> None:
    original = {
        "status": "uncertain",
        "text": "extra warning",
        "data": {
            "status": "failed",
            "song_id": "9",
            "playback_verified": False,
            "message": "permission unavailable",
            "cover_url": "https://example.invalid/image",
        },
    }
    before = deepcopy(original)
    projected = model_result(original, music=True)
    assert projected["status"] == "uncertain" and projected["text"] == "extra warning"
    assert projected["data"]["message"] == "permission unavailable"
    assert projected["data"]["song_id"] == "9" and not projected["data"]["playback_verified"]
    assert original == before


@pytest.mark.parametrize("native", [False, True])
def test_legacy_music_defaults_migrate_once_without_widening_other_apps(
    tmp_path: Path, native: bool
) -> None:
    from companion_memoryos.config import load_config
    from companion_memoryos.database import Database

    database = Database(tmp_path, load_config())
    database.initialize()
    old = ToolHub(database)
    music = MCPServerConfig(
        id="netease",
        label="Music",
        enabled=True,
        **(
            {"transport": "native"}
            if native
            else {
                "command": sys.executable,
                "args": ["-m", "companion_agent.integrations.netease"],
            }
        ),
        tools={
            "netease_search_songs": ToolRule(mode="ask"),
            "netease_seek": ToolRule(mode="off"),
            "netease_control": ToolRule(mode="ask", arguments={"action": ["pause"]}),
            "future_unknown": ToolRule(mode="ask"),
        },
    )
    other = MCPServerConfig(id="other", label="Other", command="custom", enabled=True)
    old.configure(AutomationConfig(servers=[music, other]))
    with database.connection() as db:
        row = json.loads(db.execute("SELECT data FROM agent_config WHERE id=1").fetchone()["data"])
        row.pop("defaults_version")
        row["config"]["loop"]["max_total_tokens"] = 30000
        db.execute("UPDATE agent_config SET data=? WHERE id=1", (json.dumps(row),))
    upgraded = ToolHub(database)
    rules = upgraded.config.servers[0].tools
    assert rules["netease_search_songs"].mode == rules["netease_open_song"].mode == "allow"
    assert rules["netease_seek"].mode == "off"
    assert rules["netease_control"].model_dump() == music.tools["netease_control"].model_dump()
    assert rules["future_unknown"].mode == "ask"
    assert upgraded.config.servers[1] == other
    assert upgraded.config.loop.max_total_tokens == 240000
    rules["netease_open_song"].mode = "ask"
    upgraded.config.loop.max_total_tokens = 12000
    upgraded.persist()
    restarted = ToolHub(database)
    assert restarted.config.servers[0].tools["netease_open_song"].mode == "ask"
    assert restarted.config.loop.max_total_tokens == 12000


def test_custom_connector_named_netease_keeps_approval() -> None:
    config = AutomationConfig(
        servers=[
            MCPServerConfig(
                id="netease",
                label="Custom",
                command="custom-player",
                enabled=True,
                tools={"netease_search_songs": ToolRule(mode="ask")},
            )
        ]
    )
    before = config.model_dump()
    migrate_music_permissions(config, sys.executable)
    assert config.model_dump() == before
