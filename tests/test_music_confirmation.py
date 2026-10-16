"""Delayed handoffs, independent permissions and late receipts, using synthetic players."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from companion_agent.automation import music_confirmation
from companion_agent.music import MusicInput
from companion_agent.music_requests import OPEN, STATE
from tests.test_music_requests import Player, pick_body, search_chat
from tests.test_music_requests import requests_app as request_fixture

requests_app = request_fixture


@pytest.fixture(autouse=True)
def clock(monkeypatch: Any) -> None:
    now = [0.0]
    monkeypatch.setattr(
        music_confirmation,
        "time",
        SimpleNamespace(
            monotonic=lambda: now[0],
            sleep=lambda seconds: now.__setitem__(0, now[0] + seconds),
        ),
    )


def delay_player(monkeypatch: Any, *, reads: int, paused: bool = False) -> None:
    original = Player.__call__
    count = [0]

    def delayed(self: Player, name: str, args: dict[str, Any]) -> dict[str, Any]:
        result = original(self, name, args)
        if name == "netease_playback_state":
            count[0] += 1
            if count[0] <= reads:
                result.update(song_id="123" if paused else "999", playback="paused")
        return result

    monkeypatch.setattr(Player, "__call__", delayed)


@pytest.mark.parametrize("platform", ["native", "stdio"])
def test_delayed_handoff_is_confirmed_with_one_open_and_one_model_receipt(
    requests_app: Any,
    monkeypatch: Any,
    platform: str,
) -> None:
    client, host, player, _, conversation = requests_app
    if platform == "stdio":
        native = host.tools.client
        target = host.tools.config.servers[0].model_copy(deep=True)
        server = host.tools.config.servers[0]
        server.transport, server.command = "stdio", sys.executable
        server.args = ["-m", "companion_agent.integrations.netease"]

        class Transport:
            def call(self, _: Any, *args: Any) -> Any:
                return native.call(target, *args)

        host.tools.client = Transport()
        host.tools.server_available = lambda candidate: candidate.id == "netease"
    delay_player(monkeypatch, reads=2)
    result = search_chat(requests_app)
    body = pick_body(result, conversation)
    assert client.post("/api/music/pick", json=body).json()["state"] == "verified"
    assert [name for name, _ in player.calls] == ["netease_open_song"] + [
        "netease_playback_state"
    ] * 3
    assert client.post("/api/music/pick", json=body).json()["operation"]["reused"]
    assert len(player.calls) == 4
    actions = host.tools.store.request_actions(
        conversation, f"music_card:{body['search_action_id']}:selected-1"
    )
    observed = [a for a in actions if a["tool_name"] == STATE]
    assert len(observed) == 1
    assert observed[0]["result"]["data"]["confirmation"]["checks"] == 3
    turn = host.memory.store.get_turn(result["assistant"]["id"], host.key.user_id)
    assert host.public_turn(turn)["music_cards"][0]["state"] == "verified"


@pytest.mark.parametrize("paused,expected", [(False, "not_started"), (True, "paused")])
def test_confirmation_stops_without_replaying_when_player_does_not_start(
    requests_app: Any,
    monkeypatch: Any,
    paused: bool,
    expected: str,
) -> None:
    client, host, player, _, conversation = requests_app
    delay_player(monkeypatch, reads=100, paused=paused)
    result = search_chat(requests_app)
    body = pick_body(result, conversation)
    assert client.post("/api/music/pick", json=body).json()["state"] == expected
    assert [name for name, _ in player.calls].count("netease_open_song") == 1
    assert [name for name, _ in player.calls].count("netease_playback_state") == 4
    turn = host.memory.store.get_turn(result["assistant"]["id"], host.key.user_id)
    assert host.public_turn(turn)["music_cards"][0]["state"] == expected


def test_preflight_is_not_reused_as_the_post_handoff_observation(requests_app: Any) -> None:
    _, host, player, model, _ = requests_app
    model.plan = [(STATE, {}), *model.plan, (OPEN, {"song_id": "123"}), (STATE, {})]
    for rule in host.tools.config.servers[0].tools.values():
        rule.mode = "allow"
    result = search_chat(requests_app, play=True)
    assert result["assistant"]["music_cards"][0]["state"] == "verified"
    assert [name for name, _ in player.calls] == [
        "netease_playback_state",
        "netease_open_song",
        "netease_playback_state",
    ]


@pytest.mark.parametrize(
    "reason,status", [("player_closed", "succeeded"), ("media_unavailable", "failed")]
)
def test_cold_start_waits_for_media_session_without_repeating_song(
    requests_app: Any, monkeypatch: Any, reason: str, status: str
) -> None:
    client, _, player, _, conversation = requests_app
    original = Player.__call__
    reads = [0]

    def starting(self: Player, name: str, args: dict[str, Any]) -> dict[str, Any]:
        result = original(self, name, args)
        if name == "netease_playback_state":
            reads[0] += 1
            if reads[0] <= 2:
                return {"status": status, "available": False, "reason": reason}
        return result

    monkeypatch.setattr(Player, "__call__", starting)
    result = search_chat(requests_app)
    response = client.post("/api/music/pick", json=pick_body(result, conversation)).json()
    assert response["state"] == "verified"
    assert [name for name, _ in player.calls] == ["netease_open_song"] + [
        "netease_playback_state"
    ] * 3


def test_open_does_not_bypass_disabled_read_permission(requests_app: Any) -> None:
    client, host, player, _, conversation = requests_app
    result = search_chat(requests_app)
    host.tools.config.servers[0].tools["netease_playback_state"].mode = "off"
    assert (
        client.post("/api/music/pick", json=pick_body(result, conversation)).json()["state"]
        == "requested"
    )
    assert [name for name, _ in player.calls] == ["netease_open_song"]


def test_late_poll_updates_card_once_and_survives_subsequent_track_change(
    requests_app: Any,
    monkeypatch: Any,
) -> None:
    client, host, player, _, conversation = requests_app
    delay_player(monkeypatch, reads=4)
    result = search_chat(requests_app)
    assert (
        client.post("/api/music/pick", json=pick_body(result, conversation)).json()["state"]
        == "not_started"
    )
    session = host.music.apply(MusicInput(conversation_id=conversation, action="start", quiet=True))
    assert session["receipt_revision"] == 1
    late = session["media"]
    count = len(player.calls)
    assert not host.music_requests.observe(conversation, late)
    assert not host.music_requests.observe(conversation, late | {"song_id": "999"})
    turn = host.memory.store.get_turn(result["assistant"]["id"], host.key.user_id)
    assert host.public_turn(turn)["music_cards"][0]["state"] == "verified"
    assert len(player.calls) == count  # History/receipt reconciliation never controls the player.


def test_same_title_without_id_or_album_remains_unverified(
    requests_app: Any, monkeypatch: Any
) -> None:
    client, host, _, _, conversation = requests_app
    original = Player.__call__

    def incomplete(self: Player, name: str, args: dict[str, Any]) -> dict[str, Any]:
        result = original(self, name, args)
        if name == "netease_playback_state":
            result.pop("song_id", None)
            result["album"] = ""
        return result

    monkeypatch.setattr(Player, "__call__", incomplete)
    result = search_chat(requests_app)
    assert (
        client.post("/api/music/pick", json=pick_body(result, conversation)).json()["state"]
        == "unverified"
    )
    session = host.music.apply(MusicInput(conversation_id=conversation, action="start", quiet=True))
    assert "receipt_revision" not in session


@pytest.mark.parametrize("restriction", ["forgotten", "expired", "other_conversation"])
def test_late_confirmation_respects_source_and_request_scope(
    requests_app: Any,
    monkeypatch: Any,
    restriction: str,
) -> None:
    client, host, player, _, conversation = requests_app
    delay_player(monkeypatch, reads=4)
    result = search_chat(requests_app)
    client.post("/api/music/pick", json=pick_body(result, conversation))
    with host.database.connection() as db:
        if restriction == "forgotten":
            db.execute(
                "UPDATE conversation_turns SET metadata_json=? WHERE id=?",
                (
                    json.dumps({"content_redacted_at": "synthetic"}),
                    result["user"]["id"],
                ),
            )
        elif restriction == "expired":
            db.execute(
                "UPDATE agent_actions SET updated_at=? WHERE tool_name=?",
                (
                    (datetime.now(UTC) - timedelta(minutes=3)).isoformat(),
                    OPEN,
                ),
            )
        else:
            conversation = "another-synthetic-conversation"
    assert not host.music_requests.observe(conversation, player("netease_playback_state", {}))


def test_low_execution_budget_does_not_start_another_read(
    requests_app: Any, monkeypatch: Any
) -> None:
    _, host, player, _, conversation = requests_app
    search_chat(requests_app)
    for rule in host.tools.config.servers[0].tools.values():
        rule.mode = "allow"
    host.tools.invoke(OPEN, {"song_id": "123"}, conversation, "find-1")
    delay_player(monkeypatch, reads=100)
    result = host.tools.invoke(STATE, {}, conversation, "find-1", timeout=4)
    assert result["data"]["confirmation"]["checks"] == 1
    assert len(player.calls) == 2
