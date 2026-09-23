"""Capability checks through the real offline chat pipeline, without review clicks."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import SecretStr

from companion_agent.app import LOCAL_USER
from companion_agent.cognition import CognitionSettings
from companion_agent.context import ChatMessage
from companion_agent.deepseek import DeepSeekConfig
from companion_agent.llm import MainLLMError, ModelResponse
from companion_agent.offline import OfflineModel
from companion_agent.romance import RomanceSettings, SettingsUpdate
from companion_memoryos.schemas import MemoryStatus
from tests.test_companion_functional import chat, host_for
from tests.test_deepseek import provider
from tests.test_romance_app import RecordingLLM, client_for


def visible_context(model: RecordingLLM) -> str:
    return "\n".join(message.content for message in model.inputs[-1])


@pytest.mark.parametrize(
    "statement",
    [
        "我喜欢咖啡",
        "我不喜欢咖啡",
        "我爱喝拿铁",
        "我喜欢喝咖啡。",
        "我讨厌香菜！",
        "回复短一点",
        "以后先听我讲",
        "我现在不喜欢喝咖啡了",
    ],
)
def test_clear_statements_become_memory_without_any_confirmation(
    tmp_path: Path, statement: str
) -> None:
    host = host_for(tmp_path)
    result = chat(host, statement)
    records = host.memories(host.conversations()[0]["id"])
    assert len(records["memories"]) == 1
    assert records["memories"][0]["evidence_turn_ids"] == [result["user"]["id"]]
    assert not records["candidates"]
    assert "确认" not in result["assistant"]["content"]
    assert "手札" not in result["assistant"]["content"]


@pytest.mark.parametrize(
    "statement",
    [
        "她说：我喜欢咖啡",
        "如果明天有空，我喜欢咖啡",
        "我可能喜欢咖啡",
        "我喜欢咖啡吗？",
        "我喜欢咖啡吗",
        "我以前喜欢咖啡",
        "“我喜欢咖啡”",
        "小说里的我喜欢咖啡",
        "我喜欢用身份证当密码",
        "最近苦味让我很舒服",
    ],
)
def test_uncertain_quoted_sensitive_or_unsupported_statements_stay_out(
    tmp_path: Path, statement: str
) -> None:
    host = host_for(tmp_path)
    result = chat(host, statement)
    assert not host.memories(host.conversations()[0]["id"])["memories"]
    assert "确认" not in result["assistant"]["content"]


def test_automatic_memory_recall_survives_restart_and_new_chat(tmp_path: Path) -> None:
    host = host_for(tmp_path)
    chat(host, "我喜欢咖啡")
    restarted = host_for(tmp_path)
    result = chat(restarted, "还记得我喜欢喝什么吗？", "recall", restarted.new_conversation()["id"])
    assert "我喜欢咖啡" in result["assistant"]["content"]
    assert "确认" not in result["assistant"]["content"]


def test_natural_correction_replaces_same_subject_despite_minor_wording(tmp_path: Path) -> None:
    host = host_for(tmp_path)
    first = chat(host, "我喜欢喝咖啡")
    chat(host, "不对，我现在不喜欢咖啡了", "change")
    records = host.memories(first["user"].get("conversation_id", host.conversations()[0]["id"]))
    assert len(records["memories"]) == 1
    assert records["memories"][0]["content"] == "我现在不喜欢咖啡了"
    assert len(host.memory.list_memories(LOCAL_USER, {MemoryStatus.SUPERSEDED})) == 1
    result = chat(host, "还记得我喜欢喝什么吗？", "recall", host.new_conversation()["id"])
    assert "我现在不喜欢咖啡了" in result["assistant"]["content"]
    assert "我喜欢喝咖啡" not in result["assistant"]["content"]


def test_independent_preferences_and_communication_requirements_coexist(tmp_path: Path) -> None:
    host = host_for(tmp_path)
    chat(host, "我喜欢咖啡，我不喜欢香菜。回复短一点。先听我讲")
    assert len(host.memories(host.conversations()[0]["id"])["memories"]) == 4


@pytest.mark.parametrize(
    "instruction",
    [
        "忘掉咖啡的喜好",
        "请忘记我喜欢咖啡这件事",
        "把关于咖啡的记忆忘掉",
        "忘掉这件事",
    ],
)
def test_natural_forgetting_blocks_memory_and_old_source_context(
    tmp_path: Path, instruction: str
) -> None:
    model = RecordingLLM()
    host = host_for(tmp_path, model)
    chat(host, "我喜欢咖啡")
    chat(host, instruction, "forget")
    assert not host.memories(host.conversations()[0]["id"])["memories"]
    chat(host, "还记得我喜欢喝什么吗？", "recall")
    assert "我喜欢咖啡" not in visible_context(model)
    restarted = host_for(tmp_path, model)
    chat(restarted, "还记得我喜欢喝什么吗？", "later", restarted.new_conversation()["id"])
    assert "我喜欢咖啡" not in visible_context(model)


def test_forget_all_versions_without_touching_other_preferences(tmp_path: Path) -> None:
    host = host_for(tmp_path)
    chat(host, "我喜欢咖啡")
    chat(host, "我不喜欢咖啡了", "change")
    chat(host, "我喜欢绿茶", "other")
    chat(host, "忘掉咖啡的喜好", "forget")
    records = host.memories(host.conversations()[0]["id"])["memories"]
    assert [r["content"] for r in records] == ["我喜欢绿茶"]
    assert len(host.memory.list_memories(LOCAL_USER, {MemoryStatus.FORGOTTEN})) == 2
    assert (
        "我喜欢绿茶"
        in chat(host, "还记得我喜欢喝什么吗？", "recall", host.new_conversation()["id"])[
            "assistant"
        ]["content"]
    )


def test_quoted_forget_does_not_act_and_unclear_target_does_not_claim_success(
    tmp_path: Path,
) -> None:
    host = host_for(tmp_path)
    chat(host, "我喜欢咖啡")
    chat(host, "她说：忘掉咖啡的喜好", "quote")
    result = chat(host, "忘掉不存在的喜好", "unknown")
    assert "暂时没有改动" in result["assistant"]["content"]
    assert len(host.memories(host.conversations()[0]["id"])["memories"]) == 1


def test_learning_happens_before_generation_and_retry_does_not_resurrect(tmp_path: Path) -> None:
    model = RecordingLLM()
    host = host_for(tmp_path, model)
    model.fail = True
    with pytest.raises(MainLLMError):
        chat(host, "我喜欢咖啡", "original")
    record = host.memories(host.conversations()[0]["id"])["memories"][0]
    host.memory.forget(record["id"], LOCAL_USER)
    model.fail = False
    chat(host, "我喜欢咖啡", "original")
    assert not host.memories(host.conversations()[0]["id"])["memories"]


def test_can_learn_again_only_from_a_new_statement_after_forgetting(tmp_path: Path) -> None:
    host = host_for(tmp_path)
    chat(host, "我喜欢咖啡")
    chat(host, "忘掉咖啡的喜好", "forget")
    chat(host, "我喜欢咖啡", "new-statement")
    assert len(host.memories(host.conversations()[0]["id"])["memories"]) == 1


def test_forget_is_applied_even_when_reply_generation_fails(tmp_path: Path) -> None:
    model = RecordingLLM()
    host = host_for(tmp_path, model)
    chat(host, "我喜欢咖啡")
    model.fail = True
    with pytest.raises(MainLLMError):
        chat(host, "忘掉咖啡的喜好", "forget")
    assert not host.memories(host.conversations()[0]["id"])["memories"]
    model.fail = False
    chat(host, "还记得我喜欢喝什么吗？", "recall")
    assert "我喜欢咖啡" not in visible_context(model)


def test_forget_also_hides_an_assistant_recall_from_a_different_conversation(
    tmp_path: Path,
) -> None:
    class RecordingOffline(RecordingLLM):
        def generate(self, messages: list[ChatMessage]) -> ModelResponse:
            super().generate(messages)
            return OfflineModel().generate(messages)

    model = RecordingOffline()
    host = host_for(tmp_path, model)
    chat(host, "我喜欢咖啡")
    second = host.new_conversation()["id"]
    recalled = chat(host, "还记得我喜欢喝什么吗？", "recall", second)
    assert "我喜欢咖啡" in recalled["assistant"]["content"]
    chat(host, "忘掉咖啡的喜好", "forget", second)
    chat(host, "还记得我喜欢喝什么吗？", "after", second)
    assert "我喜欢咖啡" not in visible_context(model)


@pytest.mark.parametrize("case", ["low_confidence", "invented", "other_person", "hypothetical"])
def test_model_proposals_cannot_skip_evidence_checks_or_ask_for_review(
    tmp_path: Path, case: str
) -> None:
    content = "下雨的日子我觉得舒服"
    statement = "如果" + content if case == "hypothetical" else content
    claim = {
        "title": "天气偏好",
        "content": "我喜欢下雪" if case == "invented" else content,
        "subject_actor_id": "someone-else" if case == "other_person" else LOCAL_USER,
        "predicate": "likes_weather",
        "confidence": 0.2 if case == "low_confidence" else 0.99,
    }
    body = {
        "model": "local-fixture",
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "content": json.dumps({"state_claims": [claim]}, ensure_ascii=False),
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
                    deepseek=DeepSeekConfig(base_url=url, model="local-fixture"),
                ),
                api_key=SecretStr("local-fixture-only"),
            )
        )
        reply = chat(host, statement)
        assert len(requests) == 1
        assert not host.memories(host.conversations()[0]["id"])["memories"]
        assert not host.memories(host.conversations()[0]["id"])["candidates"]
        assert "确认" not in reply["assistant"]["content"]


def test_legacy_setting_and_frontend_have_no_memory_review_flow(tmp_path: Path) -> None:
    legacy = CognitionSettings.model_validate({"confirm_preferences_automatically": False})
    assert "confirm_preferences_automatically" not in legacy.model_dump()
    host = host_for(tmp_path, cognition=legacy)
    chat(host, "我喜欢咖啡")
    assert len(host.memories(host.conversations()[0]["id"])["memories"]) == 1
    client = client_for(tmp_path)
    html = client.get("/").text
    web = Path(__file__).parents[1] / "companion_agent" / "web"
    ui = html + (web / "life.js").read_text(encoding="utf-8")
    ui += (web / "app.js").read_text(encoding="utf-8")
    for obsolete in ["待你确认的小事", "确认记住", "不记这条", "auto-confirm-memory"]:
        assert obsolete not in ui
    settings = client.get("/api/bootstrap").json()
    assert "confirm_preferences_automatically" not in json.dumps(settings)
