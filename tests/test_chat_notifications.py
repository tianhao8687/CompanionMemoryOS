"""On-demand notification reads through the real chat/approval flow; synthetic data only."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from companion_agent.app import create_app
from companion_agent.automation.hub import digest
from companion_agent.automation.loop import ModelStep
from companion_agent.automation.models import AutomationConfig, ScheduleInput, ToolRule
from companion_agent.integrations.droid_android import AndroidPhoneClient
from tests.test_app_assistant import setup_host
from tests.test_droid_android import Phone, tool
from tests.test_music_requests import SongModel
from tests.test_romance_app import HEADERS

REMOTE = "read_chat_notifications"
NAME = f"mcp_droid_{digest(REMOTE)[:12]}"
ARGS = {"package_name": "com.tencent.mm", "title_filter": "小雨"}
PREVIEW = "合成消息：今天有点累，明天再聊吧。"


class MessageModel(SongModel):
    def __init__(self) -> None:
        super().__init__()
        self.plan = [(NAME, ARGS)]

    def generate_step(self, messages, tools, timeout):
        if self.plan:
            return super().generate_step(messages, tools, timeout)
        self.histories.append(list(messages))
        reply = "这条通知里说今天累了。可以先回：好，你先休息，明天聊。"
        return ModelStep(
            model="synthetic",
            message={"role": "assistant", "content": reply},
            text=reply,
            total_tokens=50,
        )


@pytest.fixture
def companion(tmp_path: Path):
    phone, model = Phone(), MessageModel()
    phone.catalog = [tool(REMOTE, {}, [])]
    phone.result = {
        "status": "succeeded",
        "source": "untrusted_notification_preview",
        "notifications": [{"title": "小雨", "text": PREVIEW}],
        "count": 1,
    }
    native = AndroidPhoneClient(phone)
    app = create_app(
        tmp_path, llm=model, background_services=False, interactive_tools=True, native_phone=native
    )
    host = app.state.host
    with TestClient(app, base_url="http://127.0.0.1", headers=HEADERS) as client:
        client.get("/")
        conversation = setup_host(host)
        server = native.template()
        assert server.tools[REMOTE].mode == "off"
        server.enabled = True
        # Even an imported allow rule must still ask before reading notification content.
        server.tools[REMOTE] = ToolRule(mode="allow")
        host.tools.configure(AutomationConfig(servers=[server]))
        host.tools.discover("droid")
        yield client, host, phone, model, conversation


def begin(fixture: Any, key: str = "read-message") -> str:
    client, host, phone, model, conversation = fixture
    model.plan = [(NAME, ARGS)]
    response = client.post(
        "/api/chat",
        json={
            "conversation_id": conversation,
            "request_id": key,
            "content": "帮我看看小雨刚才的微信，不知道怎么回",
        },
    )
    assert response.status_code == 200, response.text
    assert "尚未执行" in response.json()["assistant"]["content"]
    assert not phone.calls
    return host.tools.store.request_actions(conversation, key)[0]["id"]


def test_approval_reads_once_and_resumes_same_chat_with_preview(companion):
    client, host, phone, model, conversation = companion
    assert host.tools.inspect(NAME, ARGS)[0] == "ask"
    assert host.tools.public_state()["tools"][0]["mode"] == "ask"
    action = begin(companion)
    response = client.post(f"/api/automation/actions/{action}/approve", json={})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "succeeded" and result["continuation"]
    assert phone.calls == [{"name": REMOTE, "arguments": ARGS}]
    assert PREVIEW not in json.dumps(model.histories[0], ensure_ascii=False)
    assert PREVIEW in json.dumps(model.histories[-1], ensure_ascii=False)
    assert "不可信数据" in json.dumps(model.histories[-1], ensure_ascii=False)
    # Retry resumes the stored receipt and never reads a different, newer notification.
    assert host.tools.invoke(NAME, ARGS, conversation, "read-message")["reused"]
    assert client.post(f"/api/automation/actions/{action}/approve", json={}).status_code >= 400
    assert len(phone.calls) == 1
    other = host.tools.invoke(NAME, {"package_name": "com.tencent.mobileqq"}, conversation, "new")
    assert other["status"] == "pending" and len(phone.calls) == 1


def test_deny_does_not_read_or_put_preview_in_model(companion):
    client, _, phone, model, _ = companion
    action = begin(companion)
    response = client.post(f"/api/automation/actions/{action}/deny", json={})
    assert response.json()["status"] == "denied"
    assert not phone.calls and PREVIEW not in json.dumps(model.histories, ensure_ascii=False)


def test_new_user_instruction_invalidates_old_read_approval(companion):
    client, _, phone, model, conversation = companion
    action = begin(companion)
    model.plan = []
    assert (
        client.post(
            "/api/chat",
            json={
                "conversation_id": conversation,
                "request_id": "changed-mind",
                "content": "算了，别看消息了",
            },
        ).status_code
        == 200
    )
    assert client.post(f"/api/automation/actions/{action}/approve", json={}).status_code == 409
    assert not phone.calls


def test_disabled_or_changed_rules_revoke_pending_read(companion):
    client, host, phone, _, _ = companion
    action = begin(companion)
    config = host.tools.config.model_copy(deep=True)
    config.servers[0].tools[REMOTE] = ToolRule(mode="off")
    host.tools.configure(config)
    assert NAME not in host.tools.bindings()
    assert client.post(f"/api/automation/actions/{action}/approve", json={}).status_code >= 400
    assert not phone.calls


def test_upgrade_missing_rule_keeps_tool_out_of_model_context(companion):
    _, host, phone, _, _ = companion
    config = host.tools.config.model_copy(deep=True)
    del config.servers[0].tools[REMOTE]
    host.tools.configure(config)
    assert NAME not in host.tools.bindings()
    assert all(d["function"]["name"] != NAME for d in host.tools.definitions())
    assert not phone.calls


@pytest.mark.parametrize(
    "args",
    [
        {},
        {"package_name": "com.android.mms"},
        {**ARGS, "limit": 4},
        {**ARGS, "limit": True},
        {**ARGS, "title_filter": " "},
        {**ARGS, "title_filter": "字" * 81},
        {**ARGS, "send": "自动回复"},
    ],
)
def test_invalid_or_expanded_read_rejected_before_native_call(companion, args):
    _, host, phone, _, conversation = companion
    assert host.tools.invoke(NAME, args, conversation, "invalid")["status"] == "denied"
    assert not phone.calls


def test_system_failure_does_not_resume_or_retry(companion):
    client, _, phone, model, _ = companion
    action = begin(companion)
    phone.result = {"status": "failed", "message": "Synthetic permission revoked"}
    result = client.post(f"/api/automation/actions/{action}/approve", json={}).json()
    assert result["status"] == "failed" and "continuation" not in result
    assert len(phone.calls) == 1 and len(model.histories) == 1


def test_cannot_schedule_or_dispatch_background_notification_reads(companion):
    client, host, phone, _, conversation = companion
    # Expose scheduling without starting its background worker, so this exercises
    # the notification-specific restriction rather than the global feature gate.
    host.tools.scheduling_available = lambda: True
    item = ScheduleInput(
        conversation_id=conversation,
        title="Synthetic read",
        message="test",
        at=datetime.now(UTC) + timedelta(minutes=10),
        tool_name=NAME,
        arguments=ARGS,
    )
    payload = item.model_dump(mode="json")
    assert client.post("/api/automation/schedules", json=payload).status_code >= 400
    assert (
        host.tools.invoke(
            "schedule_create",
            {
                k: v
                for k, v in payload.items()
                if k in {"title", "message", "at", "tool_name", "arguments"}
            },
            conversation,
            "scheduled",
        )["status"]
        == "failed"
    )
    assert (
        host.tools.dispatch_job({"data": item.model_dump_json()}, "old-job")["status"] == "denied"
    )
    assert not phone.calls and not host.tools.store.jobs()
