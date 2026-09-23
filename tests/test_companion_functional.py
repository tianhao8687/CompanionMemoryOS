from __future__ import annotations

import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from companion_agent.app import LOCAL_USER, ChatInput, RomanceHost
from companion_agent.automation.loop import ModelStep, ToolCall
from companion_agent.automation.models import AutomationConfig
from companion_agent.channels import ChannelConfig, IncomingMessage, WeixinClient
from companion_agent.cognition import CognitionSettings, Embeddings
from companion_agent.context import ChatMessage
from companion_agent.deepseek import DeepSeekConfig, DeepSeekLLM
from companion_agent.llm import MainLLMError, ModelResponse
from companion_agent.romance import RomanceSettings, SettingsUpdate
from companion_agent.streaming import listener, read_sse
from companion_memoryos.schemas import MemoryStatus
from tests.test_agent_automation import FakeMCP
from tests.test_deepseek import provider
from tests.test_romance_app import RecordingLLM, client_for, configure, message


def host_for(path: Path, model: Any = None, **changes: Any) -> RomanceHost:
    host = RomanceHost(path, llm=model)
    host.save_settings(
        SettingsUpdate(
            settings=RomanceSettings(
                storage_consent=True,
                model_consent=True,
                **changes,
            )
        )
    )
    return host


def chat(
    host: RomanceHost, text: str, key: str = "one", conversation: str | None = None
) -> dict[str, Any]:
    return host.chat(
        ChatInput(
            conversation_id=conversation or host.conversations()[0]["id"],
            request_id=key,
            content=text,
        )
    )


def test_offline_mode_never_calls_model_or_embedding_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("offline mode opened network")

    monkeypatch.setattr("urllib.request.OpenerDirector.open", forbidden)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "not-a-real-key")
    host = host_for(
        tmp_path, cognition=CognitionSettings(model_extraction=True, embedding_backend="api")
    )
    assert host.public_settings()["model_ready"]
    assert host.memory.turn_interpreter is None
    assert host.memory.embeddings.backend == "local"
    assert chat(host, "我喜欢咖啡")["assistant"]["content"]
    assert len(host.memories(host.conversations()[0]["id"])["memories"]) == 1


@pytest.mark.parametrize(
    "text",
    [
        "他说他喜欢咖啡",
        "如果我喜欢咖啡",
        "“我喜欢咖啡”是他的话",
        "我可能喜欢咖啡",
        "我喜欢咖啡吗？",
    ],
)
def test_natural_extraction_does_not_promote_quoted_or_uncertain_text(
    tmp_path: Path, text: str
) -> None:
    host = host_for(tmp_path)
    chat(host, text)
    records = host.memories(host.conversations()[0]["id"])
    assert not records["candidates"] and not records["memories"]


def test_preference_automatic_correct_forget_and_source_evidence(tmp_path: Path) -> None:
    client = client_for(tmp_path, RecordingLLM())
    configure(client)
    payload = message(client, "我喜欢咖啡")
    first = client.post("/api/chat", json=payload)
    assert first.status_code == 200, first.text
    host: RomanceHost = client.app.state.host
    record = host.memories(payload["conversation_id"])["memories"][0]
    assert record["evidence_turn_ids"] == [first.json()["user"]["id"]]
    response = client.put(f"/api/memories/{record['id']}", json={"content": "我不喜欢咖啡"})
    assert response.status_code == 200, response.text
    corrected = response.json()["memory"]
    assert corrected["content"] == "我不喜欢咖啡"
    assert host.memory.store.get(record["id"], LOCAL_USER).status is MemoryStatus.SUPERSEDED
    assert client.post(f"/api/memories/{corrected['id']}/forget", json={}).status_code == 200
    client.post("/api/chat", json=payload)  # Replay cannot resurrect forgotten memory.
    assert not host.memories(payload["conversation_id"])["memories"]


def test_automatic_preferences_cross_chats_and_negation_supersedes(tmp_path: Path) -> None:
    model = RecordingLLM()
    host = host_for(tmp_path, model)
    chat(host, "我喜欢咖啡")
    new = host.new_conversation()["id"]
    chat(host, "我不喜欢咖啡", "two", new)
    records = host.memories(new)["memories"]
    assert len(records) == 1 and records[0]["content"] == "我不喜欢咖啡"
    chat(host, "还记得我喜欢什么吗", "three", new)
    context = "\n".join(m.content for m in model.inputs[-1])
    assert "我不喜欢咖啡" in context
    with host.database.connection() as db:
        assert db.execute("SELECT count(*) FROM memory_embeddings").fetchone()[0] >= 1


def test_feedback_is_grounded_and_persisted(tmp_path: Path) -> None:
    host = host_for(tmp_path)
    chat(host, "以后少说教，先听我讲")
    memory = host.memories(host.conversations()[0]["id"])["memories"]
    assert len(memory) == 1 and memory[0]["metadata"]["reflection"]
    restarted = host_for(tmp_path)
    assert restarted.memory.store.get(memory[0]["id"], LOCAL_USER).content == "以后少说教，先听我讲"


def test_embedding_http_uses_separate_credentials_and_rejects_bad_vectors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COMPANION_EMBEDDING_API_KEY", "embedding-only")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "must-not-be-sent")
    with provider(body={"data": [{"embedding": [0.2, 0.4, 0.6]}]}) as (url, requests):
        embeddings = Embeddings(
            CognitionSettings(
                embedding_backend="api",
                embedding=DeepSeekConfig(
                    base_url=url,
                    model="embedding-test",
                    api_key_env="COMPANION_EMBEDDING_API_KEY",
                ),
            ),
            offline=False,
        )
        assert embeddings.encode("咖啡") == [0.2, 0.4, 0.6]
        assert requests[0]["path"] == "/embeddings"
        assert requests[0]["authorization"] == "Bearer embedding-only"
    with provider(body={"data": [{"embedding": [float("nan")]}]}) as (url, _):
        embeddings = Embeddings(
            CognitionSettings(
                embedding_backend="api",
                embedding=DeepSeekConfig(
                    base_url=url,
                    model="embedding-test",
                ),
            ),
            offline=False,
        )
        with pytest.raises(ValueError, match="embedding_service_unavailable"):
            embeddings.encode("test")


def test_embedding_failure_falls_back_without_losing_chat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = host_for(tmp_path, RecordingLLM())

    def failed(text: str) -> list[float]:
        raise ValueError("provider unavailable")

    monkeypatch.setattr(host.memory.embeddings, "encode", failed)
    assert chat(host, "你好")["assistant"]["content"]
    assert host.public_settings()["embedding_status"] == "unavailable_using_fts"


def event_host(path: Path, **changes: Any) -> tuple[RomanceHost, dict[str, Any]]:
    host = host_for(path, proactive_enabled=True, quiet_start=0, quiet_end=0, **changes)
    chat(host, "我明天下午有面试，有点紧张")
    event = host.continuity.events()[0]
    assert event["status"] == "candidate" and event["due_at"] is None
    host.continuity.change(event["id"], "scheduled", due=datetime.now(UTC) + timedelta(minutes=1))
    return host, event


def test_event_outreach_is_once_and_unanswered_events_stay_quiet(tmp_path: Path) -> None:
    host, event = event_host(tmp_path)
    when = datetime.now(UTC) + timedelta(hours=5)
    host.continuity.tick(when)
    host.continuity.tick(when + timedelta(days=1))
    row = next(row for row in host.continuity.events() if row["id"] == event["id"])
    assert row["status"] == "waiting"
    assert len([t for t in host.memory.list_turns(LOCAL_USER) if t.metadata.get("proactive")]) == 1
    assert host.tools.store.notifications()[0]["title"] == "想起你的一件事"


@pytest.mark.parametrize("text", ["面试取消了，先别问我", "别主动联系我"])
def test_event_cancellation_survives_restart(tmp_path: Path, text: str) -> None:
    host, _event = event_host(tmp_path)
    chat(host, text, "cancel")
    restarted = RomanceHost(tmp_path)
    restarted.continuity.tick(datetime.now(UTC) + timedelta(days=1))
    assert restarted.continuity.events()[0]["status"] == "cancelled"
    assert not [t for t in restarted.memory.list_turns(LOCAL_USER) if t.metadata.get("proactive")]
    if "主动" in text:
        assert not restarted.settings.proactive_enabled


def test_outreach_respects_quiet_hours_and_idle_window(tmp_path: Path) -> None:
    host, _event = event_host(tmp_path)
    host.continuity.tick(datetime.now(UTC) + timedelta(minutes=2))
    assert host.continuity.events()[0]["status"] == "scheduled"
    when = datetime.now(UTC) + timedelta(hours=5)
    hour = (when.hour + 8) % 24
    host.settings.quiet_start = hour
    host.settings.quiet_end = (hour + 1) % 24
    host.continuity.tick(when)
    row = host.continuity.events()[0]
    assert row["status"] == "scheduled" and "quiet_mode" in row["reason"]


class ResumeModel:
    tool_name = ""
    fail_resume = False

    def generate(self, messages: list[ChatMessage]) -> ModelResponse:
        return ModelResponse(text="普通回复", model="resume-test")

    def generate_step(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], timeout: float
    ) -> ModelStep:
        if messages[-1]["role"] == "tool":
            return ModelStep(
                model="resume-test",
                text="操作完成，后续也核对好了。",
                message={"role": "assistant", "content": "操作完成，后续也核对好了。"},
                total_tokens=10,
            )
        resumed = "continuation：" in str(messages[-1].get("content", ""))
        if resumed and self.fail_resume:
            raise MainLLMError("main_llm_timeout")
        call = ToolCall(
            id="clock" if resumed else "send",
            name="local_time" if resumed else self.tool_name,
            arguments="{}" if resumed else json.dumps({"contact": "小雨", "text": "晚安"}),
        )
        return ModelStep(
            model="resume-test",
            calls=[call],
            total_tokens=10,
            message={
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {"name": call.name, "arguments": call.arguments},
                    }
                ],
            },
        )


def approval_host(path: Path) -> tuple[RomanceHost, ResumeModel, FakeMCP, str]:
    model = ResumeModel()
    host = host_for(path, model)
    fake = FakeMCP()
    host.tools.client = fake
    host.tools.configure(
        AutomationConfig.model_validate(
            {"servers": [{"id": "test", "label": "test", "command": "unused", "enabled": True}]}
        )
    )
    host.tools.discover("test")
    model.tool_name = host.tools.definitions()[-1]["function"]["name"]
    response = chat(host, "帮我给小雨发晚安，然后核对当前时间")
    assert response["execution"]["status"] == "pending"
    return host, model, fake, host.tools.store.actions()[0]["id"]


def test_approval_resumes_after_restart_with_original_budget_and_no_repeat(tmp_path: Path) -> None:
    _host, model, fake, action = approval_host(tmp_path)
    restarted = RomanceHost(tmp_path, llm=model)
    restarted.tools.client = fake
    result = restarted.decide_action(action, True)
    assert result["continuation"]["execution"] == {
        "status": "completed",
        "steps": 3,
        "tool_calls": 2,
    }
    assert len(fake.calls) == 1
    again = restarted.resume(action)
    assert again and again["reused"] and len(fake.calls) == 1
    turns = restarted.memory.list_turns(LOCAL_USER)
    assert sum(t.role.value == "user" for t in turns) == 1
    assert sum(t.role.value == "assistant" for t in turns) == 2


def test_new_user_turn_prevents_old_approval(tmp_path: Path) -> None:
    host, _model, fake, action = approval_host(tmp_path)
    host.injected_llm = RecordingLLM()
    host.agent = host.make_agent(host.settings, None)
    chat(host, "先别发了", "new-goal")
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        host.decide_action(action, True)
    assert not fake.calls
    assert host.decide_action(action, False)["status"] == "denied"


def test_failed_continuation_retry_does_not_reexecute_effect(tmp_path: Path) -> None:
    host, model, fake, action = approval_host(tmp_path)
    model.fail_resume = True
    result = host.decide_action(action, True)
    assert result["status"] == "succeeded" and "continuation_error" in result
    assert len(fake.calls) == 1
    model.fail_resume = False
    assert host.resume(action)["execution"]["status"] == "completed"
    assert len(fake.calls) == 1


def test_resume_cannot_reset_step_budget(tmp_path: Path) -> None:
    host, _model, fake, action = approval_host(tmp_path)
    host.tools.config.loop.max_steps = 1
    result = host.decide_action(action, True)
    assert result["continuation"]["execution"]["status"] == "limited"
    assert len(fake.calls) == 1


def channel_host(path: Path) -> RomanceHost:
    host = host_for(path)
    host.channels.configure(
        ChannelConfig(enabled=True, conversation_id=host.conversations()[0]["id"])
    )
    return host


def test_channel_identity_dedup_and_shared_memory_across_restart(tmp_path: Path) -> None:
    host = channel_host(tmp_path)
    item = IncomingMessage(delivery_id="wx-1", sender_id="demo-owner", text="我喜欢咖啡")
    host.channels.receive(item)
    host.channels.process()
    restarted = RomanceHost(tmp_path)
    restarted.channels.receive(item)
    restarted.channels.process()
    assert len(restarted.memory.list_turns(LOCAL_USER)) == 2
    assert len(restarted.channels.public()["deliveries"]) == 1
    assert len(restarted.memories(restarted.channels.config.conversation_id)["memories"]) == 1
    with pytest.raises(ValueError, match="not authorized"):
        restarted.channels.receive(item.model_copy(update={"sender_id": "stranger"}))
    with pytest.raises(ValueError, match="different content"):
        restarted.channels.receive(item.model_copy(update={"text": "changed"}))


def test_channel_send_uncertainty_never_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = channel_host(tmp_path)
    host.channels.configure(host.channels.config.model_copy(update={"transport": "weixin"}))
    attempts: list[str] = []

    def failed(*args: Any, **kwargs: Any) -> None:
        attempts.append("sent")
        raise ValueError("timeout")

    monkeypatch.setattr(WeixinClient, "send", failed)
    host.channels.receive(
        IncomingMessage(delivery_id="1", sender_id="demo-owner", text="你好", context_token="ctx")
    )
    host.channels.process()
    assert host.channels.public()["deliveries"][0]["status"] == "uncertain"
    restarted = RomanceHost(tmp_path)
    restarted.channels.process()
    assert attempts == ["sent"]


def test_weixin_http_text_contract_and_credentials_not_public(tmp_path: Path) -> None:
    with provider(body={"ret": 0}) as (url, requests):
        WeixinClient(url, "private-token").send(
            "owner", "private-context", "stable-delivery", "你好"
        )
    assert requests[0]["path"] == "/ilink/bot/sendmessage"
    payload = requests[0]["body"]["msg"]
    assert payload["client_id"] == "stable-delivery" and payload["to_user_id"] == "owner"
    assert payload["item_list"] == [{"type": 1, "text_item": {"text": "你好"}}]
    host = channel_host(tmp_path)
    host.channels.session_token = "private-token"
    assert "private-token" not in json.dumps(host.channels.public())


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example",
        "http://ilinkai.weixin.qq.com",
        "https://ilinkai.weixin.qq.com.evil.example",
        "https://user:pass@ilinkai.weixin.qq.com",
    ],
)
def test_weixin_rejects_credential_redirect_endpoints(url: str) -> None:
    with pytest.raises(ValueError):
        WeixinClient(url, "secret")


def sse(chunks: list[dict[str, Any]], done: bool = True) -> bytes:
    result = b"".join(b"data: " + json.dumps(c).encode() + b"\n\n" for c in chunks)
    return result + (b"data: [DONE]\n\n" if done else b"")


def test_real_http_stream_text_and_private_reasoning_filter() -> None:
    events: list[dict[str, Any]] = []
    chunks = [
        {"model": "fake", "choices": [{"delta": {"reasoning_content": "SECRET"}}]},
        {"choices": [{"delta": {"content": "你好"}}]},
        {"choices": [{"delta": {"content": "，我在"}, "finish_reason": "stop"}]},
    ]
    token = listener.set(events.append)
    try:
        with provider(raw=sse(chunks)) as (url, requests):
            result = DeepSeekLLM(DeepSeekConfig(base_url=url), api_key="fixture-key").generate(
                [ChatMessage(role="user", content="你好")]
            )
    finally:
        listener.reset(token)
    assert result.text == "你好，我在"
    assert requests[0]["body"]["stream"] is True
    assert "SECRET" not in json.dumps(events)
    assert [e["text"] for e in events if e["type"] == "delta"] == ["你好", "，我在"]


def test_incomplete_stream_is_not_accepted() -> None:
    with pytest.raises(MainLLMError, match="incomplete_output"):
        read_sse(
            io.BytesIO(sse([{"choices": [{"delta": {"content": "partial"}}]}], done=False)), 10000
        )


def test_fragmented_tool_stream_is_assembled_without_exposing_arguments() -> None:
    chunks = [
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call1",
                                "function": {"name": "local_time", "arguments": "{"},
                            }
                        ]
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "delta": {"tool_calls": [{"index": 0, "function": {"arguments": "}"}}]},
                    "finish_reason": "tool_calls",
                }
            ]
        },
    ]
    events: list[dict[str, Any]] = []
    token = listener.set(events.append)
    try:
        envelope = read_sse(io.BytesIO(sse(chunks)), 10000)
    finally:
        listener.reset(token)
    call = envelope["choices"][0]["message"]["tool_calls"][0]
    assert call["function"] == {"name": "local_time", "arguments": "{}"}
    assert all(e["type"] == "reset" for e in events)


def test_stream_endpoint_commits_once_and_reports_errors(tmp_path: Path) -> None:
    client = client_for(tmp_path)
    configure(client)
    payload = message(client, "你好")
    response = client.post("/api/chat/stream", json=payload)
    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[-1]["type"] == "done"
    assert events[-2]["result"]["assistant"]["content"]
    client.post("/api/chat/stream", json=payload)
    assert (
        len(
            client.get(f"/api/conversations/{payload['conversation_id']}/messages").json()[
                "messages"
            ]
        )
        == 2
    )
    configure(client, storage_consent=False)
    response = client.post("/api/chat/stream", json=message(client, "拒绝存储", "no-consent"))
    assert '"type": "error"' in response.text


def test_offline_reminder_is_an_actual_persistent_job(tmp_path: Path) -> None:
    host = host_for(tmp_path)
    result = chat(host, "5 分钟后提醒我喝水")
    assert result["execution"]["status"] == "completed"
    assert len(host.tools.store.jobs()) == 1
    restarted = RomanceHost(tmp_path)
    restarted.tools.scheduler.tick(datetime.now(UTC) + timedelta(minutes=6))
    assert restarted.tools.store.jobs()[0]["status"] == "completed"
    assert restarted.tools.store.notifications()[0]["message"] == "喝水"
