from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from typing import Any

import pytest
from fastapi.testclient import TestClient

from companion_agent.app import LOCAL_USER, RomanceHost, create_app
from companion_agent.context import ChatMessage
from companion_agent.llm import MainLLMError, ModelResponse
from companion_agent.persona.loader import load_persona
from companion_agent.romance import RomanceSettings
from companion_memoryos.schemas import ConsentState, ConversationRole, ConversationTurnInput

HEADERS = {"X-Companion-Client": "local-web", "Origin": "http://127.0.0.1"}


class RecordingLLM:
    def __init__(self) -> None:
        self.inputs: list[list[ChatMessage]] = []
        self.fail = False

    def generate(self, messages: list[ChatMessage]) -> ModelResponse:
        self.inputs.append(messages)
        if self.fail:
            raise MainLLMError("main_llm_timeout")
        return ModelResponse(text="我在，慢慢说。", model="deepseek-test-double")


def client_for(path: Path, model: RecordingLLM | None = None) -> TestClient:
    client = TestClient(create_app(path, llm=model), base_url="http://127.0.0.1", headers=HEADERS)
    assert client.get("/").status_code == 200
    return client


def configure(client: TestClient, **changes: Any) -> dict[str, Any]:
    settings = RomanceSettings(
        storage_consent=True, model_consent=True, romance_consent=True
    ).model_dump(mode="json")
    settings.update(changes)
    response = client.put("/api/settings", json={"settings": settings})
    assert response.status_code == 200, response.text
    return settings


def message(
    client: TestClient, content: str = "以后叫我小雨", key: str = "first"
) -> dict[str, str]:
    conversation = client.get("/api/bootstrap").json()["conversations"][0]["id"]
    return {"conversation_id": conversation, "request_id": key, "content": content}


def test_static_bootstrap_and_security(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    client = TestClient(app, base_url="http://127.0.0.1")
    assert client.get("/api/health").json()["status"] == "ok"
    assert client.get("/api/bootstrap").status_code == 401
    response = client.get("/")
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=strict" in response.headers["set-cookie"]
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200
    assert client.get("/api/bootstrap").status_code == 200
    assert client.post("/api/conversations").status_code == 403
    assert (
        client.post(
            "/api/conversations", headers={**HEADERS, "Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    assert client.get("/api/bootstrap", headers={"Host": "evil.example"}).status_code == 400


def test_chat_requires_consent_and_key_before_storing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    client = client_for(tmp_path)
    payload = message(client)
    assert client.post("/api/chat", json=payload).status_code == 403
    configure(client, model_mode="api")
    response = client.post("/api/chat", json=payload)
    assert response.status_code == 502 and "api_key_missing" in response.text
    host: RomanceHost = client.app.state.host  # type: ignore[union-attr]
    assert host.memory.list_turns(LOCAL_USER) == []


def test_separate_ports_do_not_overwrite_browser_session(tmp_path: Path) -> None:
    first = TestClient(create_app(tmp_path / "a"), base_url="http://127.0.0.1:8765")
    second = TestClient(create_app(tmp_path / "b"), base_url="http://127.0.0.1:8766")
    first.get("/")
    second.get("/")
    first.cookies.update(second.cookies)
    second.cookies.update(first.cookies)
    assert first.get("/api/bootstrap").status_code == 200
    assert second.get("/api/bootstrap").status_code == 200


def test_chat_memory_replay_and_persistence(tmp_path: Path) -> None:
    model = RecordingLLM()
    client = client_for(tmp_path, model)
    configure(client, user_name="小雨", companion_name="知夏")
    payload = message(client)
    response = client.post("/api/chat", json=payload)
    assert response.status_code == 200, response.text
    repeated = client.post("/api/chat", json=payload)
    assert repeated.json()["reused"] and len(model.inputs) == 1
    assert client.post("/api/chat", json={**payload, "content": "换一个内容"}).status_code == 409
    client.post(
        "/api/chat", json={**payload, "content": "先听我说完，不要给建议", "request_id": "second"}
    )
    context = "\n".join(part.content for part in model.inputs[-1])
    assert "知夏" in context and "小雨" in context and "romantic_partner" in context
    assert "我在，慢慢说。" in context
    memory = client.get(f"/api/memories/{payload['conversation_id']}").json()
    assert memory["relationship"]["identity"]["type"] == "romantic_partner"
    assert memory["relationship"]["stage"] == "new"
    assert memory["states"]
    restarted = client_for(tmp_path, model)
    assert restarted.get("/api/bootstrap").json()["settings"]["companion_name"] == "知夏"
    history = restarted.get(f"/api/conversations/{payload['conversation_id']}/messages").json()
    assert [item["role"] for item in history["messages"]] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert restarted.post("/api/chat", json=payload).json()["reused"]
    assert len(model.inputs) == 2


def test_custom_style_persists_and_reaches_model_without_default_examples(tmp_path: Path) -> None:
    model = RecordingLLM()
    client = client_for(tmp_path, model)
    custom = (
        "沉静的成年男友，喜欢旧电影，说话直接，偶尔有冷幽默。\n"
        "示例只示范语气：\n你：今晚散步？\n我：走，顺路买橘子。"
    )
    configure(client, style="custom", custom_style="  " + custom + "  ")
    restarted = client_for(tmp_path, model)
    settings = restarted.get("/api/bootstrap").json()["settings"]
    assert settings["style"] == "custom" and settings["custom_style"] == custom
    response = restarted.post("/api/chat", json=message(restarted, "晚上好"))
    assert response.status_code == 200, response.text
    assert custom in model.inputs[-1][0].content
    system = model.inputs[-1][0].content
    assert system.index("[PERSONA]") < system.index("[SELECTED INTERACTION STYLE]")
    assert "示例只示范语气，不是真实经历" in system
    assert "Example (fictional style demonstration" not in model.inputs[-1][0].content
    assert "不能假装已有共同经历" in model.inputs[-1][0].content
    # Switching presets retains the draft, but no longer injects it into the request.
    settings["style"] = "playful"
    assert restarted.put("/api/settings", json={"settings": settings}).status_code == 200
    assert (
        restarted.post("/api/chat", json=message(restarted, "聊聊电影", "preset")).status_code
        == 200
    )
    assert custom not in model.inputs[-1][0].content
    assert restarted.get("/api/bootstrap").json()["settings"]["custom_style"] == custom


def test_custom_style_validates_blank_and_supports_complete_prompt(tmp_path: Path) -> None:
    client = client_for(tmp_path, RecordingLLM())
    settings = configure(client)
    response = client.put(
        "/api/settings", json={"settings": {**settings, "style": "custom", "custom_style": "  "}}
    )
    assert response.status_code == 422
    assert client.get("/api/bootstrap").json()["settings"]["style"] == "gentle"
    configure(client, style="custom", custom_style="自然表达，保留自己的判断。" * 300)
    response = client.post("/api/chat", json=message(client))
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("style", ["gentle", "custom"])
def test_settings_reload_persona_without_losing_session_key_or_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, style: str
) -> None:
    import yaml

    from companion_agent import romance

    persona_path = tmp_path / "persona.yaml"
    definition = load_persona().model_dump(mode="json")
    definition["invariants"].append(
        {"id": "reload_probe", "severity": "hard", "description": "数字来源需要可以核对"}
    )
    persona_path.write_text(yaml.safe_dump(definition, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(romance, "load_persona", lambda: load_persona(persona_path))
    model = RecordingLLM()
    client = client_for(tmp_path / "data", model)
    settings = configure(client, style=style, custom_style="温暖，喜欢听对方说话。")
    secret = "sk-synthetic-persona-reload-test"
    saved = client.put("/api/settings", json={"settings": settings, "api_key": secret})
    assert saved.status_code == 200 and saved.json()["key_source"] == "session"
    payload = message(client, "晚上好", "before-reload")
    before = client.post("/api/chat", json=payload)
    assert before.status_code == 200, before.text
    assert ("数字来源需要可以核对" in model.inputs[-1][0].content) == (style != "custom")

    definition["invariants"][-1]["description"] = "时间来源需要可以核对"
    persona_path.write_text(yaml.safe_dump(definition, allow_unicode=True), encoding="utf-8")
    # Saving unchanged public settings reloads the source without sending another key.
    reloaded = client.put("/api/settings", json={"settings": settings})
    assert reloaded.status_code == 200 and reloaded.json()["key_source"] == "session"
    host: RomanceHost = client.app.state.host  # type: ignore[union-attr]
    assert host.api_key == secret
    after = client.post(
        "/api/chat", json={**payload, "content": "继续聊吧", "request_id": "after-reload"}
    )
    assert after.status_code == 200, after.text
    context = model.inputs[-1][0].content
    assert ("时间来源需要可以核对" in context) == (style != "custom")
    assert "数字来源需要可以核对" not in context
    for invariant in definition["invariants"]:
        included = style != "custom"
        assert (f"{invariant['severity']}/{invariant['id']}" in context) == included
    reply_ids = {result.json()["assistant"]["id"] for result in (before, after)}
    versions = {
        turn.metadata["persona_version"]
        for turn in host.memory.list_turns(LOCAL_USER)
        if turn.id in reply_ids
    }
    assert len(versions) == (1 if style == "custom" else 2)
    history = client.get(f"/api/conversations/{payload['conversation_id']}/messages").json()
    assert len(history["messages"]) == 4
    assert secret not in reloaded.text and secret not in client.get("/api/bootstrap").text


def test_failed_generation_retry_does_not_duplicate(tmp_path: Path) -> None:
    model = RecordingLLM()
    client = client_for(tmp_path, model)
    configure(client)
    payload = message(client, "今天有点累")
    model.fail = True
    assert client.post("/api/chat", json=payload).status_code == 502
    path = f"/api/conversations/{payload['conversation_id']}/messages"
    history = client.get(path).json()["messages"]
    assert len(history) == 1 and history[0]["request_id"] == payload["request_id"]
    model.fail = False
    assert client.post("/api/chat", json=payload).status_code == 200
    assert len(client.get(path).json()["messages"]) == 2


def test_explicit_memory_survives_new_conversation_and_corrections(tmp_path: Path) -> None:
    model = RecordingLLM()
    client = client_for(tmp_path, model)
    configure(client)
    original = message(client, "以后叫我小雨")
    assert client.post("/api/chat", json=original).status_code == 200
    second = client.post("/api/conversations", json={}).json()["id"]
    cards = client.get(f"/api/memories/{second}").json()["memories"]
    assert any("小雨" in card["content"] for card in cards)
    revised = {"conversation_id": second, "request_id": "rename", "content": "以后叫我小晴"}
    assert client.post("/api/chat", json=revised).status_code == 200
    assert client.post("/api/chat", json=original).json()["reused"]
    cards = client.get(f"/api/memories/{second}").json()["memories"]
    assert any("小晴" in card["content"] for card in cards)
    assert all("小雨" not in card["content"] for card in cards)
    query = {
        "conversation_id": second,
        "request_id": "recall-name",
        "content": "我希望你叫我什么名字？",
    }
    assert client.post("/api/chat", json=query).status_code == 200
    assert "小晴" in "\n".join(item.content for item in model.inputs[-1])


@pytest.mark.parametrize("content", ["他说：以后叫我小雨", "假如以后叫我小雨", "“以后叫我小雨”"])
def test_quoted_or_hypothetical_name_not_promoted(tmp_path: Path, content: str) -> None:
    client = client_for(tmp_path, RecordingLLM())
    configure(client)
    payload = message(client, content)
    assert client.post("/api/chat", json=payload).status_code == 200
    assert not client.get(f"/api/memories/{payload['conversation_id']}").json()["memories"]


def test_explicit_note_is_evidence_backed(tmp_path: Path) -> None:
    client = client_for(tmp_path, RecordingLLM())
    configure(client)
    payload = message(client, "记住：我最喜欢白色郁金香。")
    result = client.post("/api/chat", json=payload)
    assert result.status_code == 200
    cards = client.get(f"/api/memories/{payload['conversation_id']}").json()["memories"]
    assert cards and cards[0]["evidence_turn_ids"] == [result.json()["user"]["id"]]
    assert "白色郁金香" in cards[0]["content"]


def test_separate_conversations_and_pagination(tmp_path: Path) -> None:
    client = client_for(tmp_path, RecordingLLM())
    configure(client)
    first = message(client)
    assert client.post("/api/chat", json=first).status_code == 200
    second = client.post("/api/conversations", json={}).json()
    assert client.get(f"/api/conversations/{second['id']}/messages").json()["messages"] == []
    history_url = f"/api/conversations/{first['conversation_id']}/messages"
    latest = client.get(history_url + "?limit=1").json()
    assert latest["has_more"] and latest["messages"][0]["role"] == "assistant"
    before = latest["messages"][0]["sequence"]
    assert client.get(history_url + f"?before={before}").json()["messages"][0]["role"] == "user"
    assert (
        client.post("/api/chat", json={**first, "conversation_id": "foreign-id"}).status_code == 404
    )


def test_keys_never_persist_or_appear_in_responses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    client = client_for(tmp_path)
    settings = configure(client)
    secret = "sk-very-private-test-value"
    response = client.put("/api/settings", json={"settings": settings, "api_key": secret})
    assert response.json()["key_configured"] and secret not in response.text
    assert secret not in client.get("/api/bootstrap").text
    assert secret not in client.get("/api/export").text
    assert secret.encode() not in (tmp_path / "companion-memoryos.db").read_bytes()
    restarted = client_for(tmp_path)
    assert not restarted.get("/api/bootstrap").json()["key_configured"]
    invalid = client.put(
        "/api/settings", json={"settings": settings, "api_key": secret + "\ninvalid"}
    )
    assert invalid.status_code == 422 and secret not in invalid.text


def test_custom_endpoint_does_not_inherit_environment_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "official-provider-secret")
    client = client_for(tmp_path)
    settings = configure(client, model_mode="api")
    settings["deepseek"]["base_url"] = "https://other-provider.example/v1"
    assert client.put("/api/settings", json={"settings": settings}).status_code == 400
    assert (
        client.put(
            "/api/settings", json={"settings": settings, "api_key": "custom-secret"}
        ).status_code
        == 200
    )
    restarted = client_for(tmp_path)
    assert not restarted.get("/api/bootstrap").json()["key_configured"]
    host: RomanceHost = restarted.app.state.host  # type: ignore[union-attr]
    with pytest.raises(MainLLMError, match="api_key_missing"):
        assert host.agent.main_llm
        host.agent.main_llm.generate([ChatMessage(role="user", content="你好")])


def test_connection_check_does_not_store_chat(tmp_path: Path) -> None:
    model = RecordingLLM()
    client = client_for(tmp_path, model)
    configure(client)
    assert client.post("/api/connection", json={}).status_code == 200
    assert len(model.inputs) == 1
    payload = message(client)
    assert (
        client.get(f"/api/conversations/{payload['conversation_id']}/messages").json()["messages"]
        == []
    )


def test_consent_revocation_and_identity_switch(tmp_path: Path) -> None:
    model = RecordingLLM()
    client = client_for(tmp_path, model)
    configure(client)
    payload = message(client)
    assert client.post("/api/chat", json=payload).status_code == 200
    configure(client, romance_consent=False)
    assert (
        client.get(f"/api/memories/{payload['conversation_id']}").json()["relationship"][
            "identity"
        ]["type"]
        == "companion"
    )
    configure(client, romance_consent=True)
    assert (
        client.get(f"/api/memories/{payload['conversation_id']}").json()["relationship"][
            "identity"
        ]["type"]
        == "romantic_partner"
    )
    configure(client, model_consent=False)
    assert client.post("/api/chat", json={**payload, "request_id": "second"}).status_code == 403
    assert len(model.inputs) == 1


def test_history_excludes_forgotten_turns(tmp_path: Path) -> None:
    client = client_for(tmp_path, RecordingLLM())
    configure(client)
    payload = message(client)
    host: RomanceHost = client.app.state.host  # type: ignore[union-attr]
    stored = host.memory.append_turn(
        ConversationTurnInput(
            user_id=LOCAL_USER,
            scope=host.scope(payload["conversation_id"]),
            actor_id=LOCAL_USER,
            role=ConversationRole.USER,
            content="这句已经遗忘",
            consent=ConsentState.GRANTED,
        )
    )
    assert stored.turn
    host.memory.forget_turn(stored.turn.id, LOCAL_USER)
    assert (
        "这句已经遗忘"
        not in client.get(f"/api/conversations/{payload['conversation_id']}/messages").text
    )


def test_payload_limits(tmp_path: Path) -> None:
    client = client_for(tmp_path)
    assert (
        client.post("/api/chat", content=json.dumps({"content": "a" * 40_000})).status_code == 413
    )
    configure(client)
    assert client.post("/api/chat", json=message(client, " ")).status_code == 422


def test_concurrent_mutations_return_busy(tmp_path: Path) -> None:
    started, release = Event(), Event()

    class SlowLLM(RecordingLLM):
        def generate(self, messages: list[ChatMessage]) -> ModelResponse:
            started.set()
            assert release.wait(timeout=15)
            return super().generate(messages)

    client = client_for(tmp_path, SlowLLM())
    configure(client)
    payload = message(client)
    with ThreadPoolExecutor() as executor:
        pending = executor.submit(client.post, "/api/chat", json=payload)
        try:
            assert started.wait(timeout=15)
            assert client.post("/api/conversations", json={}).status_code == 409
        finally:
            release.set()
        assert pending.result(timeout=15).status_code == 200
