from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from companion_agent.app import RomanceHost, create_app
from companion_agent.focus import FocusAction, FocusClock, FocusNotice, FocusStart

HEADERS = {"X-Companion-Client": "local-web", "Origin": "http://127.0.0.1"}


@pytest.fixture
def focus(tmp_path: Path) -> tuple[RomanceHost, list[float]]:
    host = RomanceHost(tmp_path)
    clock = [datetime(2026, 10, 13, 7, tzinfo=UTC).timestamp()]
    host.focus.clock = lambda: clock[0]
    return host, clock


def start(host: RomanceHost, request_id: str = "session-1", **changes: Any) -> dict[str, Any]:
    return host.focus.start(
        FocusStart(
            request_id=request_id,
            conversation_id=host.conversations()[0]["id"],
            **changes,
        ),
        "Asia/Shanghai",
    )


def action(host: RomanceHost, snapshot: dict[str, Any], name: str) -> dict[str, Any]:
    session = snapshot["session"]
    return host.focus.act(
        FocusAction.model_validate(
            {"session_id": session["id"], "revision": session["revision"], "action": name}
        ),
        "Asia/Shanghai",
    )


def test_pause_resume_restart_and_no_automatic_next_phase(
    focus: tuple[RomanceHost, list[float]],
) -> None:
    host, clock = focus
    snapshot = start(host, focus_minutes=1, rest_minutes=1)
    clock[0] += 17
    paused = action(host, snapshot, "pause")
    assert paused["session"]["remaining_seconds"] == 43
    clock[0] += 3600
    restarted = FocusClock(host.database, host.focus.scope, clock=lambda: clock[0])
    assert restarted.read("Asia/Shanghai")["session"] == paused["session"]
    resumed = action(host, paused, "resume")
    assert resumed["session"]["deadline"] == clock[0] + 43
    assert host.focus.quiet()
    clock[0] += 4000
    complete = host.focus.read("Asia/Shanghai")
    assert complete["session"]["phase"] == "focus_done"
    assert complete["today"] == {"date": "2026-10-13", "count": 1, "minutes": 1}
    assert not host.focus.quiet()
    resting = action(host, complete, "rest")
    assert resting["session"]["deadline"] == clock[0] + 60
    clock[0] += 10
    paused_rest = action(host, resting, "pause")
    clock[0] += 200
    assert host.focus.read("Asia/Shanghai")["session"]["remaining_seconds"] == 50
    action(host, paused_rest, "resume")
    clock[0] += 51
    done = host.focus.read("Asia/Shanghai")
    assert done["session"]["phase"] == "done"
    assert done["today"]["count"] == 1


def test_retries_stale_tabs_and_completion_count_once(
    focus: tuple[RomanceHost, list[float]],
) -> None:
    host, clock = focus
    original = start(host, focus_minutes=1)
    assert start(host, focus_minutes=1) == original
    with pytest.raises(HTTPException):
        start(host, intention="changed")
    with pytest.raises(HTTPException):
        start(host, "second")
    paused = action(host, original, "pause")
    with pytest.raises(HTTPException):
        action(host, original, "resume")
    assert host.focus.quiet()
    resumed = action(host, paused, "resume")
    clock[0] += 60
    with pytest.raises(HTTPException):
        action(host, resumed, "pause")
    for _ in range(3):
        latest = host.focus.read("Asia/Shanghai")
        assert latest["session"]["phase"] == "focus_done"
        assert latest["today"]["count"] == 1
    ended = action(host, latest, "finish")
    with pytest.raises(HTTPException):
        action(host, ended, "resume")
    assert ended["today"]["count"] == 1


def test_early_finish_does_not_claim_completion_and_clear_does_not_resurrect(
    focus: tuple[RomanceHost, list[float]],
) -> None:
    host, clock = focus
    original = start(host, intention="私人任务")
    clock[0] += 30
    ended = action(host, original, "finish")
    assert ended["today"]["count"] == 1
    assert ended["session"]["remaining_seconds"] == 1770
    host.focus.clear_history()
    assert host.focus.read("Asia/Shanghai")["session"] is None
    assert host.focus.export() == []
    with host.database.connection() as db:
        row = db.execute("SELECT * FROM romance_focus_sessions").fetchone()
        assert "私人任务" not in str(dict(row))
    with pytest.raises(HTTPException):
        start(host, intention="私人任务")
    active = start(host, "new")
    host.focus.clear_history()
    assert host.focus.read("Asia/Shanghai")["session"] == active["session"]


def test_daily_stats_group_by_start_day_and_relationship_scope(
    focus: tuple[RomanceHost, list[float]],
) -> None:
    host, clock = focus
    clock[0] = datetime(2026, 10, 13, 15, 59, 30, tzinfo=UTC).timestamp()
    start(host, focus_minutes=1)
    clock[0] += 90
    today = host.focus.read("Asia/Shanghai")
    assert today["today"] == {"date": "2026-10-14", "count": 0, "minutes": 0}
    other = FocusClock(host.database, "other-relationship", clock=lambda: clock[0])
    assert other.read("Asia/Shanghai")["today"]["count"] == 0
    assert other.read("Asia/Shanghai")["session"] is None
    clock[0] += 86400
    assert host.focus.read("Asia/Shanghai")["today"]["count"] == 0


def test_two_simultaneous_starts_have_only_one_winner(
    focus: tuple[RomanceHost, list[float]],
) -> None:
    host, _ = focus

    def attempt(request_id: str) -> str:
        try:
            start(host, request_id)
            return "started"
        except HTTPException:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(attempt, ["first", "second"])) == ["conflict", "started"]


def test_elapsed_activity_extension_and_notice_are_not_task_completion(
    focus: tuple[RomanceHost, list[float]],
) -> None:
    host, clock = focus
    original = start(host, focus_minutes=1)
    clock[0] += 15
    paused = action(host, original, "pause")
    clock[0] += 300
    assert paused["session"]["elapsed_seconds"] == 15
    resumed = action(host, paused, "resume")
    clock[0] += 45
    reached = host.focus.read("Asia/Shanghai")
    assert reached["session"]["elapsed_seconds"] == 60
    assert reached["session"]["phase"] == "focus_done"
    assert "rewards" not in reached
    notice = FocusNotice(
        session_id=reached["session"]["id"], revision=reached["session"]["revision"]
    )
    assert host.focus.claim_notice(notice, "Asia/Shanghai")
    assert not host.focus.claim_notice(notice, "Asia/Shanghai")
    extended = action(host, reached, "extend")
    assert extended["session"]["id"] == original["session"]["id"]
    assert extended["session"]["remaining_seconds"] == 300
    clock[0] += 20
    ended = action(host, extended, "finish")
    assert ended["session"]["elapsed_seconds"] == 80
    assert ended["session"]["completed_at"] is None
    assert [event["action"] for event in ended["session"]["events"]] == [
        "start",
        "pause",
        "resume",
        "timer_elapsed",
        "extend",
        "finish",
    ]
    assert host.memory.list_turns(host.key.user_id) == []
    assert host.memory.store.list_memories(host.key.user_id) == []
    assert resumed["session"]["deadline"] < clock[0]


def test_return_days_later_is_ended_and_does_not_notify_again(
    focus: tuple[RomanceHost, list[float]],
) -> None:
    host, clock = focus
    start(host, focus_minutes=30, intention="整理资料")
    deadline = clock[0] + 1800
    clock[0] += 2 * 86400
    old = host.focus.read("Asia/Shanghai")["session"]
    assert old["phase"] == "focus_done"
    assert old["ended_at"] == deadline
    assert old["elapsed_seconds"] == 1800
    assert not host.focus.quiet()
    assert not host.focus.claim_notice(
        FocusNotice(session_id=old["id"], revision=old["revision"]), "Asia/Shanghai"
    )
    assert "当前计时状态=focus_done" in host.focus.context()
    fresh = start(host, "two-days-later")
    assert fresh["session"]["id"] != old["id"]


def test_api_consent_validation_security_export_and_no_model_call(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    client = TestClient(app, base_url="http://127.0.0.1", headers=HEADERS)
    assert client.get("/api/focus").status_code == 401
    client.get("/")
    settings = client.get("/api/bootstrap").json()["settings"]
    payload = {
        "request_id": "web-focus",
        "conversation_id": app.state.host.conversations()[0]["id"],
        "focus_minutes": 1,
        "intention": "写一个开头",
    }
    assert client.post("/api/focus", json=payload).status_code == 403
    settings["storage_consent"] = True
    client.put("/api/settings", json={"settings": settings})
    assert not settings["model_consent"]
    for duration in [0, 121, 1.5, True]:
        assert (
            client.post("/api/focus", json={**payload, "focus_minutes": duration}).status_code
            == 422
        )
    assert client.post("/api/focus", json={**payload, "intention": "x" * 161}).status_code == 422
    assert (
        client.post("/api/focus", json={**payload, "conversation_id": "missing"}).status_code == 404
    )
    assert (
        client.post("/api/focus", json=payload, headers={"Origin": "https://evil.test"}).status_code
        == 403
    )
    started = client.post("/api/focus", json=payload)
    assert started.status_code == 200
    assert client.get("/api/export").json()["focus"][0]["intention"] == "写一个开头"
    session = started.json()["session"]
    settings["storage_consent"] = False
    client.put("/api/settings", json={"settings": settings})
    paused = client.post(
        "/api/focus/action",
        json={
            "session_id": session["id"],
            "revision": session["revision"],
            "action": "pause",
        },
    ).json()["session"]
    assert (
        client.post(
            "/api/focus/action",
            json={
                "session_id": paused["id"],
                "revision": paused["revision"],
                "action": "resume",
            },
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/focus/action",
            json={
                "session_id": paused["id"],
                "revision": paused["revision"],
                "action": "finish",
            },
        ).status_code
        == 200
    )
    assert client.delete("/api/focus/history").status_code == 200
    assert client.get("/api/export").json()["focus"] == []
    assert app.state.host.memory.list_turns(app.state.host.key.user_id) == []


def test_focus_defers_proactive_check_without_changing_preference(
    focus: tuple[RomanceHost, list[float]], monkeypatch: pytest.MonkeyPatch
) -> None:
    host, clock = focus
    host.settings = host.settings.model_copy(
        update={
            "storage_consent": True,
            "model_consent": True,
            "proactive_enabled": True,
        }
    )
    calls: list[datetime] = []
    monkeypatch.setattr(host.continuity, "_tick", calls.append)
    start(host, focus_minutes=1)
    host.continuity.tick()
    assert calls == []
    assert host.settings.proactive_enabled
    clock[0] += 61
    host.continuity.tick()
    assert len(calls) == 1
