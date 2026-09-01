from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from companion_memoryos.api import create_app
from companion_memoryos.config import load_config


def authorized_client(tmp_path: Path) -> tuple[TestClient, dict[str, str]]:
    app = create_app(tmp_path, load_config())
    token = (tmp_path / "api-token").read_text(encoding="utf-8").strip()
    return TestClient(app), {"Authorization": f"Bearer {token}"}


def test_companion_experience_routes_complete_a_follow_up_without_reasking(
    tmp_path: Path,
) -> None:
    client, headers = authorized_client(tmp_path)
    scope = {
        "companion_id": "companion-a",
        "relationship_id": "relationship-a",
        "conversation_id": "conversation-a",
    }
    turn_response = client.post(
        "/api/v1/turns",
        headers=headers,
        json={
            "user_id": "alice",
            "scope": scope,
            "actor_id": "alice",
            "role": "user",
            "content": "今天面试结束了",
            "consent": "granted",
            "retrieval_keys": ["求职进展"],
            "episode_id": "interview-one",
        },
    )
    assert turn_response.status_code == 200
    turn_id = turn_response.json()["turn"]["id"]
    stored = client.post(
        "/api/v1/open-loops",
        headers=headers,
        json={
            "user_id": "alice",
            "scope": {key: value for key, value in scope.items() if key != "conversation_id"},
            "kind": "event_outcome",
            "summary": "面试的后续",
            "topic_keys": ["面试"],
            "consent": "granted",
            "source_turn_id": turn_id,
        },
    )
    assert stored.status_code == 200
    loop_id = stored.json()["open_loop"]["id"]
    listed = client.get("/api/v1/users/alice/open-loops", headers=headers)
    assert [item["id"] for item in listed.json()] == [loop_id]

    planned = client.post(
        "/api/v1/response-plans",
        headers=headers,
        json={
            "user_id": "alice",
            "scope": scope,
            "trigger_turn_id": turn_id,
            "goal": "check_in",
            "current_topic_keys": ["面试"],
        },
    )
    assert planned.status_code == 200
    plan = planned.json()
    assert [beat["kind"] for beat in plan["beats"]] == ["acknowledgement", "follow_up"]
    loaded = client.get(f"/api/v1/response-plans/{plan['id']}?user_id=alice", headers=headers)
    assert loaded.status_code == 200
    for beat in plan["beats"]:
        receipt = client.post(
            f"/api/v1/response-plans/{plan['id']}/beats/{beat['id']}/sent",
            headers=headers,
            json={
                "user_id": "alice",
                "rendered_text": "面试聊得怎么样？",
                "task_policy_version": plan["policy_version"],
            },
        )
        assert receipt.status_code == 200
    assert receipt.json()["status"] == "completed"
    loop = client.get("/api/v1/users/alice/open-loops", headers=headers).json()[0]
    assert loop["status"] == "waiting_for_reply"
    assert loop["follow_up_count"] == 1
    exported = client.get("/api/v1/users/alice/export", headers=headers).json()
    assert exported["response_plans"][0]["id"] == plan["id"]
    assert exported["open_loops"][0]["id"] == loop_id


def test_raw_feedback_repair_and_interrupt_are_available_without_a_memory_card(
    tmp_path: Path,
) -> None:
    client, headers = authorized_client(tmp_path)
    scope = {"relationship_id": "relationship-a", "conversation_id": "conversation-a"}
    turn = client.post(
        "/api/v1/turns",
        headers=headers,
        json={
            "user_id": "alice",
            "scope": scope,
            "actor_id": "alice",
            "role": "user",
            "content": "奶奶送的蓝色杯子",
            "consent": "granted",
        },
    ).json()["turn"]
    repaired = client.post(
        "/api/v1/repairs",
        headers=headers,
        json={
            "user_id": "alice",
            "scope": scope,
            "kind": "wrong_reference",
            "evidence_kind": "turn",
            "evidence_id": turn["id"],
        },
    )
    assert repaired.status_code == 200
    assert repaired.json()["reference_feedback"]["evidence_id"] == turn["id"]
    feedback = client.get("/api/v1/users/alice/reference-feedback", headers=headers)
    assert len(feedback.json()) == 1

    planned = client.post(
        "/api/v1/response-plans",
        headers=headers,
        json={
            "user_id": "alice",
            "scope": scope,
            "trigger_turn_id": turn["id"],
            "goal": "listen",
        },
    )
    assert planned.status_code == 200
    plan_id = planned.json()["id"]
    interrupted = client.post(
        "/api/v1/response-plans/interrupt",
        headers=headers,
        json={"user_id": "alice", "scope": scope},
    )
    assert interrupted.status_code == 200
    assert interrupted.json()["cancelled_response_plan_ids"] == [plan_id]
    listed = client.get("/api/v1/users/alice/response-plans", headers=headers).json()
    assert listed[0]["status"] == "cancelled"


def test_interpreted_staged_response_can_be_resolved_after_the_first_beat(
    tmp_path: Path,
) -> None:
    client, headers = authorized_client(tmp_path)
    scope = {"relationship_id": "relationship-a", "conversation_id": "conversation-a"}
    turn = client.post(
        "/api/v1/turns",
        headers=headers,
        json={
            "user_id": "alice",
            "scope": scope,
            "actor_id": "alice",
            "role": "user",
            "content": "先听我说，别给建议",
            "consent": "granted",
        },
    ).json()["turn"]
    staged = client.post(
        "/api/v1/response-plans/interpreted-staged",
        headers=headers,
        json={"user_id": "alice", "scope": scope, "turn_id": turn["id"]},
    )
    assert staged.status_code == 200
    payload = staged.json()
    assert payload["interpretation"]["suggested_goal"] == "listen"
    assert payload["plan"]["resolution_status"] == "pending"
    plan = payload["plan"]
    receipt = client.post(
        f"/api/v1/response-plans/{plan['id']}/beats/{plan['beats'][0]['id']}/sent",
        headers=headers,
        json={
            "user_id": "alice",
            "rendered_text": "嗯，我听着。",
            "task_policy_version": plan["policy_version"],
        },
    )
    assert receipt.status_code == 200
    assert receipt.json()["status"] == "active"
    resolved = client.post(
        f"/api/v1/response-plans/{plan['id']}/resolve",
        headers=headers,
        json={
            "user_id": "alice",
            "expected_revision": 0,
            "resolution_key": str(uuid4()),
        },
    )
    assert resolved.status_code == 200
    assert resolved.json()["resolution_status"] == "resolved"


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
    assert purged.json()["status"] == "primary_store_purged"
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
        json={
            "user_id": "alice",
            "scope": {"conversation_id": "session-one"},
            "query": "白色郁金香",
        },
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
    assert purged.json()["status"] == "primary_store_purged"


def test_correction_and_personal_time_anchor_are_available_over_api(tmp_path: Path) -> None:
    client, headers = authorized_client(tmp_path)
    captured = client.post(
        "/api/v1/memories",
        headers=headers,
        json={
            "user_id": "alice",
            "kind": "preference",
            "title": "称呼",
            "content": "叫我小禾",
            "stable_key": "preferred_name",
            "consent": "granted",
            "explicit_user_request": True,
        },
    )
    memory_id = captured.json()["memory"]["id"]
    corrected = client.post(
        f"/api/v1/memories/{memory_id}/correct",
        headers=headers,
        json={"user_id": "alice", "content": "叫我禾禾"},
    )
    assert corrected.status_code == 200
    assert corrected.json()["memory"]["supersedes_id"] == memory_id

    anchor = client.post(
        "/api/v1/time-anchors",
        headers=headers,
        json={
            "user_id": "alice",
            "name": "备考期",
            "start_at": "2026-03-01T00:00:00Z",
            "end_at": "2026-04-01T00:00:00Z",
            "consent": "granted",
        },
    )
    assert anchor.status_code == 200
    assert anchor.json()["stored"] is True
    listed = client.get("/api/v1/users/alice/time-anchors", headers=headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 1


def test_relationship_ledger_state_policy_and_use_routes(tmp_path: Path) -> None:
    client, headers = authorized_client(tmp_path)
    scope = {
        "companion_id": "companion",
        "relationship_id": "relationship",
        "conversation_id": "conversation",
    }
    turn = client.post(
        "/api/v1/turns",
        headers=headers,
        json={
            "user_id": "alice",
            "scope": scope,
            "actor_id": "alice",
            "role": "user",
            "content": "以后叫我禾禾",
            "consent": "granted",
            "idempotency_key": "api-turn-1",
        },
    )
    assert turn.status_code == 200
    turn_id = turn.json()["turn"]["id"]
    assert turn.json()["turn"]["idempotency_key"] == "api-turn-1"

    memory = client.post(
        "/api/v1/memories",
        headers=headers,
        json={
            "user_id": "alice",
            "scope": scope,
            "kind": "preference",
            "title": "称呼",
            "content": "叫我禾禾",
            "stable_key": "preferred_name",
            "predicate": "preferred_name",
            "evidence_turn_ids": [turn_id],
            "consent": "granted",
            "explicit_user_request": True,
        },
    )
    assert memory.status_code == 200
    memory_id = memory.json()["memory"]["id"]

    state = client.post(
        "/api/v1/state/query",
        headers=headers,
        json={
            "user_id": "alice",
            "scope": scope,
            "predicate": "preferred_name",
        },
    )
    assert state.status_code == 200
    assert state.json()["resolution_status"] == "resolved"

    constraint = client.post(
        "/api/v1/policy-constraints",
        headers=headers,
        json={
            "user_id": "alice",
            "scope": scope,
            "action": "proactive_contact",
            "effect": "deny",
            "reason_code": "user_boundary",
            "source_turn_id": turn_id,
            "source_direct_user_instruction": True,
        },
    )
    assert constraint.status_code == 200
    constraint_id = constraint.json()["id"]
    gate = client.post(
        "/api/v1/policy/evaluate",
        headers=headers,
        json={
            "user_id": "alice",
            "scope": scope,
            "actions": ["proactive_contact"],
        },
    )
    assert gate.json()["allowed"] is False

    use = client.post(
        "/api/v1/memory-uses",
        headers=headers,
        json={
            "user_id": "alice",
            "scope": scope,
            "memory_id": memory_id,
            "response_group_id": "response",
            "use_mode": "natural",
            "purpose": "personalization",
        },
    )
    assert use.status_code == 200

    revoked = client.delete(
        f"/api/v1/policy-constraints/{constraint_id}?user_id=alice&mode=revoke",
        headers=headers,
    )
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"
    purged = client.delete(
        f"/api/v1/policy-constraints/{constraint_id}?user_id=alice&mode=purge",
        headers=headers,
    )
    assert purged.status_code == 200
    assert purged.json()["status"] == "primary_store_purged"
