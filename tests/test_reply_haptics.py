"""Real chat/store/tool flow with a scripted model and synthetic Android transport."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from companion_agent.app import create_app
from companion_agent.automation.loop import ModelStep
from companion_agent.automation.models import AutomationConfig, ToolRule
from companion_agent.integrations.droid_android import AndroidPhoneClient
from companion_agent.llm import MainLLMError
from companion_agent.reply_haptics import TOOL, VIBRATE, refused
from tests.test_app_assistant import setup_host
from tests.test_droid_android import Phone, tool
from tests.test_music_requests import SongModel
from tests.test_romance_app import HEADERS

PHRASE = "听到你终于通过了，我真的特别替你开心！"


class ReplyModel(SongModel):
    def __init__(self) -> None:
        super().__init__()
        self.plan = []
        self.reply = PHRASE
        self.before_final = lambda: None
        self.offered: set[str] = set()

    def generate_step(self, messages, tools, timeout) -> ModelStep:
        self.offered.update(tool["function"]["name"] for tool in tools)
        if self.plan:
            return super().generate_step(messages, tools, timeout)
        self.before_final()
        return ModelStep(
            model="synthetic",
            message={"role": "assistant", "content": self.reply},
            text=self.reply,
            total_tokens=50,
        )


@pytest.fixture
def companion(tmp_path: Path):
    phone, model = Phone(), ReplyModel()
    phone.catalog = [
        tool("vibrate_pattern", {"timings": {"type": "array"}}, ["timings"]),
        tool("cancel_vibration", {}, []),
    ]
    native = AndroidPhoneClient(phone)
    app = create_app(
        tmp_path,
        llm=model,
        background_services=False,
        interactive_tools=True,
        native_phone=native,
    )
    host = app.state.host
    with TestClient(app, base_url="http://127.0.0.1", headers=HEADERS) as client:
        client.get("/")
        conversation = setup_host(host)
        template = native.template()
        template.enabled = True
        template.tools = {item["name"]: ToolRule(mode="allow") for item in phone.catalog}
        host.tools.configure(AutomationConfig(servers=[template], reply_haptics_enabled=True))
        host.tools.discover("droid")
        yield client, host, phone, model, conversation


def chat(fixture: Any, *, key="reply-1", text="我终于通过考试了", prepare=True):
    client, _, _, model, conversation = fixture
    model.plan = [(TOOL, {"phrase": PHRASE})] if prepare else []
    return client.post(
        "/api/chat",
        json={"conversation_id": conversation, "request_id": key, "content": text},
    )


def age_touch(host: Any) -> None:
    with host.database.connection() as db:
        db.execute(
            "UPDATE agent_actions SET created_at=? WHERE tool_name=?",
            ((datetime.now(UTC) - timedelta(seconds=21)).isoformat(), VIBRATE),
        )


def test_emotional_reply_delivers_after_completion_only_once(companion):
    _, host, phone, model, _ = companion

    def before_final():
        assert not phone.calls, "A prepared expression must not vibrate before the reply."

    model.before_final = before_final
    response = chat(companion)
    assert response.status_code == 200, response.text
    assert response.json()["assistant"]["content"] == PHRASE
    assert TOOL in model.offered
    assert len(phone.calls) == 1
    assert phone.calls[0]["arguments"] == {"timings": [0, 80, 200, 80], "repeat": -1}
    age_touch(host)
    assert chat(companion).json()["reused"]
    assert len(phone.calls) == 1


def test_stream_keeps_expression_quiet_and_returns_the_completed_reply(companion):
    client, _, phone, model, conversation = companion
    model.plan = [(TOOL, {"phrase": PHRASE})]
    response = client.post(
        "/api/chat/stream",
        json={
            "conversation_id": conversation,
            "request_id": "stream-touch",
            "content": "我终于通过考试了",
        },
    )
    events = [json.loads(line) for line in response.text.splitlines()]
    result = next(event["result"] for event in events if event["type"] == "result")
    assert result["assistant"]["content"] == PHRASE
    assert events[-1]["type"] == "done" and len(phone.calls) == 1
    assert not any(
        "工具权限" in event.get("message", "") or event["type"] == "error" for event in events
    )


def test_manual_touch_is_not_followed_by_an_automatic_touch(companion):
    client, _, phone, model, conversation = companion
    model.plan = [
        (VIBRATE, {"timings": [0, 80, 200, 80], "repeat": -1}),
        (TOOL, {"phrase": PHRASE}),
    ]
    response = client.post(
        "/api/chat",
        json={
            "conversation_id": conversation,
            "request_id": "manual-touch",
            "content": "拍我两下吧，我终于通过考试了",
        },
    )
    assert response.status_code == 200 and len(phone.calls) == 1


@pytest.mark.parametrize("prepare,reply", [(False, PHRASE), (True, "嗯，我听着呢。")])
def test_no_cue_or_changed_final_sentence_does_not_vibrate(companion, prepare, reply):
    companion[3].reply = reply
    assert chat(companion, prepare=prepare).status_code == 200
    assert not companion[2].calls


@pytest.mark.parametrize("restriction", ["disabled", "ask", "off", "loop", "disconnected"])
def test_configuration_and_permissions_are_checked_even_for_unoffered_calls(companion, restriction):
    _, host, phone, model, _ = companion
    if restriction == "disabled":
        host.tools.config.reply_haptics_enabled = False
    elif restriction == "loop":
        host.tools.config.loop.enabled = False
    elif restriction == "disconnected":
        host.tools.config.servers[0].enabled = False
    else:
        host.tools.config.servers[0].tools["vibrate_pattern"].mode = restriction
    assert chat(companion).status_code == 200
    assert TOOL not in model.offered
    assert not phone.calls
    assert not any(row["status"] == "pending" for row in host.tools.store.actions())


def test_recheck_consent_after_preparation_and_suppress_cancelled_or_failed_reply(companion):
    _, host, phone, model, _ = companion
    model.before_final = lambda: setattr(host.tools.config, "reply_haptics_enabled", False)
    assert chat(companion).status_code == 200
    assert not phone.calls
    host.tools.config.reply_haptics_enabled = True
    model.before_final = lambda: host.loop.cancel("cancelled")
    assert chat(companion, key="cancelled").status_code == 502
    assert not phone.calls

    def fail():
        raise MainLLMError("main_llm_invalid_output")

    model.before_final = fail
    assert chat(companion, key="failed").status_code != 200
    assert not phone.calls


@pytest.mark.parametrize("status", ["succeeded", "failed", "uncertain"])
def test_cooldown_covers_device_failures_and_new_conversations(companion, status):
    _, host, phone, _, _ = companion
    phone.result = {"status": status}
    assert chat(companion).status_code == 200
    assert len(phone.calls) == 1
    assert chat(companion, key="reply-2").status_code == 200
    assert len(phone.calls) == 1
    other = (*companion[:4], host.new_conversation()["id"])
    assert chat(other, key="reply-3").status_code == 200
    assert len(phone.calls) == 1
    age_touch(host)
    assert chat(other, key="reply-4").status_code == 200
    assert len(phone.calls) == 2


def test_direct_refusal_persists_without_widening_any_permissions(companion):
    client, host, phone, _, _ = companion
    before = host.tools.config.servers[0].model_dump()
    assert chat(companion, text="别震了，我不喜欢这样").status_code == 200
    assert not phone.calls
    assert not host.tools.config.reply_haptics_enabled
    assert host.tools.config.servers[0].model_dump() == before
    assert client.get("/api/automation").json()["config"]["reply_haptics_enabled"] is False


@pytest.mark.parametrize("text", ["别震了", "关掉随回复触感", "不要自动震动", "我不喜欢震动"])
def test_direct_refusals(text):
    assert refused(text)


@pytest.mark.parametrize("text", ["‘别震了’是台词", "如果我说别震了呢", "我没有说不要震动"])
def test_quotes_hypotheticals_and_negated_refusals_are_not_settings_changes(text):
    assert not refused(text)


def test_existing_configuration_does_not_enable_reply_haptics():
    assert not AutomationConfig().reply_haptics_enabled
