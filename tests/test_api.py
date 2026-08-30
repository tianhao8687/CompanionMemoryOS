from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from companion_memoryos.api import create_app
from companion_memoryos.config import load_config


def authorized_client(tmp_path: Path) -> tuple[TestClient, dict[str, str]]:
    app = create_app(tmp_path, load_config())
    token = (tmp_path / "api-token").read_text(encoding="utf-8").strip()
    return TestClient(app), {"Authorization": f"Bearer {token}"}


def test_health_is_public_but_memory_routes_require_auth(tmp_path: Path) -> None:
    client, _ = authorized_client(tmp_path)
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/v1/users/alice/memories").status_code == 401


def test_capture_recall_export_and_purge(tmp_path: Path) -> None:
    client, headers = authorized_client(tmp_path)
    capture = client.post(
        "/api/v1/memories",
        headers=headers,
        json={
            "user_id": "alice",
            "kind": "boundary",
            "title": "称呼边界",
            "content": "不要叫我主人",
            "consent": "granted",
            "explicit_user_request": True,
        },
    )
    assert capture.status_code == 200
    memory_id = capture.json()["memory"]["id"]
    recall = client.post(
        "/api/v1/recall",
        headers=headers,
        json={"user_id": "alice", "query": "称呼"},
    )
    assert recall.status_code == 200
    assert recall.json()["sections"]["boundaries"][0]["memory"]["id"] == memory_id
    exported = client.get("/api/v1/users/alice/export", headers=headers)
    assert len(exported.json()["memories"]) == 1
    purged = client.delete(
        f"/api/v1/memories/{memory_id}?user_id=alice&mode=purge",
        headers=headers,
    )
    assert purged.status_code == 200
    assert client.get("/api/v1/users/alice/export", headers=headers).json()["memories"] == []


def test_event_fallback_and_proactivity_are_available_over_api(tmp_path: Path) -> None:
    client, headers = authorized_client(tmp_path)
    archived = client.post(
        "/api/v1/events",
        headers=headers,
        json={
            "user_id": "alice",
            "session_id": "session-one",
            "role": "user",
            "content": "下班路上买了一枝白色郁金香",
            "consent": "granted",
        },
    )
    assert archived.status_code == 200
    event_id = archived.json()["event"]["id"]

    recall = client.post(
        "/api/v1/recall",
        headers=headers,
        json={"user_id": "alice", "query": "白色郁金香"},
    )
    assert recall.status_code == 200
    assert recall.json()["retrieval_outcome"] == "match"
    assert recall.json()["event_fallback"][0]["event"]["id"] == event_id

    now = datetime.now(UTC)
    proactive = client.post(
        "/api/v1/proactivity/evaluate",
        headers=headers,
        json={
            "user_id": "alice",
            "permission_granted": True,
            "last_user_message_at": (now - timedelta(days=1)).isoformat(),
            "has_relevant_reason": True,
            "as_of": now.isoformat(),
        },
    )
    assert proactive.status_code == 200
    assert proactive.json()["should_reach_out"] is True

    purged = client.delete(
        f"/api/v1/events/{event_id}?user_id=alice&mode=purge",
        headers=headers,
    )
    assert purged.status_code == 200
