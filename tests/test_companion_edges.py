from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr

from companion_agent.app import LOCAL_USER, RomanceHost
from companion_agent.channels import ChannelConfig, IncomingMessage, WeixinClient
from companion_agent.cognition import CognitionSettings
from companion_agent.deepseek import DeepSeekConfig
from companion_agent.llm import MainLLMError
from companion_agent.romance import RomanceSettings, SettingsUpdate
from tests.test_companion_functional import (
    approval_host,
    channel_host,
    chat,
    event_host,
    host_for,
)
from tests.test_deepseek import provider
from tests.test_romance_app import RecordingLLM, client_for, configure, message


def test_offline_recall_references_confirmed_memory_in_empty_new_chat(tmp_path: Path) -> None:
    host = host_for(tmp_path)
    chat(host, "我不喜欢咖啡")
    empty_chat = host.new_conversation()["id"]
    response = chat(host, "还记得我喜欢什么吗？", "new-chat", empty_chat)
    assert "我不喜欢咖啡" in response["assistant"]["content"]


def test_reminder_quoted_by_someone_else_does_not_create_job(tmp_path: Path) -> None:
    host = host_for(tmp_path)
    chat(host, "有人说“5 分钟后提醒我喝水”，这是什么意思？")
    assert not host.tools.store.jobs()


def test_cancel_event_does_not_depend_on_successful_model_response(tmp_path: Path) -> None:
    model = RecordingLLM()
    host, _event = event_host(tmp_path, model=model)
    model.fail = True
    with pytest.raises(MainLLMError):
        chat(host, "面试取消了，先别问我", "cancellation")
    assert host.continuity.events()[0]["status"] == "cancelled"


def test_deleted_event_source_cannot_trigger_outreach(tmp_path: Path) -> None:
    host, event = event_host(tmp_path)
    host.memory.forget_turn(event["source_turn"], LOCAL_USER)
    host.continuity.tick(datetime.now(UTC) + timedelta(hours=5))
    assert host.continuity.events()[0]["status"] == "invalidated"
    assert not host.tools.store.notifications()


def test_failed_resume_consumes_budget_and_eventual_retry_stops(tmp_path: Path) -> None:
    host, model, fake, action = approval_host(tmp_path)
    host.tools.config.loop.max_steps = 2
    model.fail_resume = True
    assert host.decide_action(action, True)["continuation_error"]
    model.fail_resume = False
    response = host.resume(action)
    assert response and response["execution"]["status"] == "limited"
    assert len(fake.calls) == 1


def test_checkpoint_is_durable_before_pending_reply_is_committed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host, model, fake, old_action = approval_host(tmp_path)
    assert host.decide_action(old_action, False)["status"] == "denied"
    original = host.memory.append_turn

    def fail_assistant(item: Any) -> Any:
        if item.role.value == "assistant":
            raise ValueError("simulated commit failure")
        return original(item)

    monkeypatch.setattr(host.memory, "append_turn", fail_assistant)
    with pytest.raises(ValueError, match="commit failure"):
        chat(host, "再试一次发晚安", "second")
    action = host.tools.store.actions()[0]["id"]
    with host.database.connection() as db:
        assert db.execute(
            "SELECT source_turn FROM agent_checkpoints WHERE action_id=?", (action,)
        ).fetchone()
    restarted = RomanceHost(tmp_path, llm=model)
    restarted.tools.client = fake
    assert restarted.decide_action(action, True)["continuation"]["assistant"]["content"]
    assert len(fake.calls) == 1


def test_legacy_freeform_memory_can_be_corrected(tmp_path: Path) -> None:
    client = client_for(tmp_path, RecordingLLM())
    configure(client)
    payload = message(client, "记住：最喜欢的杯子是蓝色的")
    assert client.post("/api/chat", json=payload).status_code == 200
    memory = client.get(f"/api/memories/{payload['conversation_id']}").json()["memories"][0]
    response = client.put(
        f"/api/memories/{memory['id']}",
        json={
            "content": "最喜欢的杯子是白色的",
            "conversation_id": payload["conversation_id"],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["memory"]["content"] == "最喜欢的杯子是白色的"


def test_model_extractor_adopts_literal_grounded_preference_without_review(tmp_path: Path) -> None:
    content = "下雨的日子我觉得舒服"
    proposal = {
        "topics": ["雨天"],
        "state_claims": [
            {
                "title": "天气偏好",
                "content": content,
                "subject_actor_id": LOCAL_USER,
                "predicate": "likes_weather",
                "confidence": 0.95,
            }
        ],
    }
    body = {
        "model": "local-interpreter",
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "content": json.dumps(proposal, ensure_ascii=False),
                },
            }
        ],
    }
    with provider(body=body) as (url, requests):
        host = host_for(tmp_path, RecordingLLM())
        host.save_settings(
            SettingsUpdate(
                settings=RomanceSettings(
                    model_mode="api",
                    storage_consent=True,
                    model_consent=True,
                    cognition=CognitionSettings(model_extraction=True),
                    deepseek=DeepSeekConfig(base_url=url, model="local-interpreter"),
                ),
                api_key=SecretStr("local-fixture-key"),
            )
        )
        chat(host, content)
        memories = host.memories(host.conversations()[0]["id"])
        assert len(requests) == 1 and requests[0]["path"] == "/chat/completions"
        assert len(memories["memories"]) == 1 and not memories["candidates"]
        assert memories["memories"][0]["evidence_turn_ids"]
    client = client_for(tmp_path, RecordingLLM())
    candidate = memories["memories"][0]
    assert candidate["scope"]["conversation_id"] is None
    new_chat = client.post("/api/conversations", json={}).json()["id"]
    assert client.get(f"/api/memories/{new_chat}").json()["memories"][0]["id"] == candidate["id"]


def test_weixin_poll_filters_sender_deduplicates_and_persists_cursor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = channel_host(tmp_path)
    host.channels.configure(host.channels.config.model_copy(update={"transport": "weixin"}))
    host.channels.session_token = "fake-token"
    cursors: list[str] = []
    sends: list[str] = []

    def updates(client: WeixinClient, cursor: str) -> dict[str, Any]:
        cursors.append(cursor)
        return {
            "get_updates_buf": "next-page",
            "msgs": [
                {
                    "message_id": "one",
                    "from_user_id": "demo-owner",
                    "message_type": 1,
                    "context_token": "ctx",
                    "item_list": [{"type": 1, "text_item": {"text": "你好"}}],
                },
                {
                    "message_id": "other",
                    "from_user_id": "stranger",
                    "message_type": 1,
                    "context_token": "ctx",
                    "item_list": [{"type": 1, "text_item": {"text": "窃取记忆"}}],
                },
            ],
        }

    monkeypatch.setattr(WeixinClient, "updates", updates)
    monkeypatch.setattr(WeixinClient, "send", lambda *args: sends.append("sent"))
    host.channels.tick()
    host.channels.tick()
    assert cursors == ["", "next-page"] and sends == ["sent"]
    assert len(host.memory.list_turns(LOCAL_USER)) == 2


def test_weixin_login_binds_owner_without_returning_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = channel_host(tmp_path)
    host.channels.configure(
        ChannelConfig(transport="weixin", conversation_id=host.conversations()[0]["id"])
    )

    def request(client: WeixinClient, endpoint: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        if endpoint == "get_bot_qrcode":
            return {"qrcode": "code", "qrcode_img_content": "https://example.com/login"}
        return {
            "status": "confirmed",
            "bot_token": "private-token",
            "ilink_user_id": "owner-123",
            "baseurl": "https://ilinkai.weixin.qq.com",
        }

    monkeypatch.setattr(WeixinClient, "request", request)
    assert host.channels.login()["status"] == "wait"
    result = host.channels.login(True)
    assert result["owner_id"] == "owner-123" and host.channels.token() == "private-token"
    assert "private-token" not in json.dumps(result)
    assert b"private-token" not in host.database.path.read_bytes()


def test_interrupted_outbox_is_not_sent_after_restart(tmp_path: Path) -> None:
    host = channel_host(tmp_path)
    host.channels.receive(IncomingMessage(delivery_id="1", sender_id="demo-owner", text="你好"))
    host.channels.process()
    with host.database.connection() as db:
        db.execute("UPDATE agent_outbox SET status='sending'")
    restarted = RomanceHost(tmp_path)
    restarted.channels.process()
    assert restarted.channels.public()["deliveries"][0]["status"] == "uncertain"
