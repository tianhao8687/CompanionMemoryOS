"""Regression coverage for ordinary wording and real cross-conversation evidence."""

import json
from pathlib import Path

import pytest
from pydantic import SecretStr

from companion_agent.app import LOCAL_USER
from companion_agent.cognition import CognitionSettings
from companion_agent.deepseek import DeepSeekConfig
from companion_agent.llm import ModelResponse
from companion_agent.romance import RomanceSettings, SettingsUpdate
from companion_memoryos.schemas import MemoryStatus
from tests.test_automatic_memory import visible_context
from tests.test_companion_functional import chat, host_for
from tests.test_deepseek import provider
from tests.test_romance_app import RecordingLLM


@pytest.mark.parametrize(
    "statement,query,evidence",
    [
        ("帮我记住一个小细节：我的旅行箱是绿色，上面贴着一只白鹤。", "旅行箱什么颜色？", "白鹤"),
        ("请记住，我的备用耳机放在书桌左边第二个抽屉。", "备用耳机放哪儿了？", "第二个抽屉"),
        ("帮我记一下，下周读书会的主题是海洋。", "读书会的主题是什么？", "海洋"),
        (
            "请记住两件小事：3月4日我去了画展，3月9日去了植物园。",
            "画展和植物园隔了几天？",
            "3月4日",
        ),
        (
            "这次帮我记住两个人的偏好：我喜欢红色，朋友阿岚喜欢绿色。",
            "阿岚喜欢什么颜色？",
            "朋友阿岚喜欢绿色",
        ),
    ],
)
def test_natural_notes_reach_new_conversation_and_survive_restart(
    tmp_path: Path, statement: str, query: str, evidence: str
) -> None:
    model = RecordingLLM()
    host = host_for(tmp_path, model, cognition=CognitionSettings(embedding_backend="off"))
    sent = chat(host, statement)
    records = host.memories(host.conversations()[0]["id"])["memories"]
    assert any(sent["user"]["id"] in r["evidence_turn_ids"] for r in records)
    restarted = host_for(tmp_path, model, cognition=CognitionSettings(embedding_backend="off"))
    chat(restarted, query, "recall", restarted.new_conversation()["id"])
    assert evidence in visible_context(model)


def test_favorite_update_replaces_value_and_preserves_independent_preference(
    tmp_path: Path,
) -> None:
    model = RecordingLLM()
    host = host_for(tmp_path, model)
    chat(host, "请记住，我现在最喜欢的饮品是白桃乌龙。")
    chat(host, "我最喜欢的颜色是紫色。", "color")
    chat(host, "更新一下，我现在最喜欢的是茉莉绿茶；白桃乌龙是以前的答案了。", "update")
    records = host.memories(host.conversations()[0]["id"])["memories"]
    assert any("茉莉绿茶" in r["content"] for r in records)
    assert any("紫色" in r["content"] for r in records)
    assert not any("白桃乌龙" in r["content"] for r in records)
    assert any(
        "白桃乌龙" in r.content
        for r in host.memory.list_memories(LOCAL_USER, {MemoryStatus.SUPERSEDED})
    )
    chat(host, "我现在最喜欢的饮品是什么？", "recall", host.new_conversation()["id"])
    assert "茉莉绿茶" in visible_context(model)
    assert "白桃乌龙" not in visible_context(model)


@pytest.mark.parametrize("query", ["画展和植物园隔了几天？", "那次画展和植物园隔了几天？"])
def test_fts_question_framing_does_not_hide_known_dates(tmp_path: Path, query: str) -> None:
    model = RecordingLLM()
    host = host_for(tmp_path, model, cognition=CognitionSettings(embedding_backend="off"))
    chat(host, "请记住两件小事：3月4日我去了画展，3月9日去了植物园。")
    chat(host, "我最喜欢的颜色是紫色。", "distractor")
    chat(host, query, "recall", host.new_conversation()["id"])
    assert "3月4日" in visible_context(model) and "3月9日" in visible_context(model)
    chat(host, "我的汽车是哪年买的？", "unrelated", host.new_conversation()["id"])
    assert "3月4日" not in visible_context(model)


@pytest.mark.parametrize(
    "statement",
    [
        "如果明天开心，我现在最喜欢的饮品是白桃乌龙。",
        "她说：请记住，我最喜欢的饮品是白桃乌龙。",
        "小说台词是‘请记住，我最喜欢白桃乌龙’。",
        "我以前最喜欢白桃乌龙。",
        "请记住了吗？",
        "不要记住我的旅行箱颜色。",
    ],
)
def test_flexible_wording_does_not_turn_questions_quotes_or_conditions_into_self_facts(
    tmp_path: Path, statement: str
) -> None:
    host = host_for(tmp_path)
    chat(host, statement)
    assert not host.memories(host.conversations()[0]["id"])["memories"]


def test_explicit_note_forgetting_removes_cross_conversation_evidence(tmp_path: Path) -> None:
    model = RecordingLLM()
    host = host_for(tmp_path, model)
    chat(host, "帮我记住：我的旅行箱上贴着一只白鹤。")
    new = host.new_conversation()["id"]
    chat(host, "旅行箱上贴着什么？", "recall", new)
    assert "白鹤" in visible_context(model)
    chat(host, "请忘记旅行箱的事", "forget", new)
    chat(host, "旅行箱上贴着什么？", "after", host.new_conversation()["id"])
    assert "白鹤" not in visible_context(model)


def test_forget_acknowledgement_cannot_reintroduce_the_forgotten_fact(tmp_path: Path) -> None:
    class EchoAcknowledgement(RecordingLLM):
        def generate(self, messages):
            self.inputs.append(messages)
            return ModelResponse(text="已处理你喜欢咖啡这件事。", model="local-fixture")

    model = EchoAcknowledgement()
    host = host_for(tmp_path, model)
    chat(host, "我喜欢咖啡")
    chat(host, "请忘记我喜欢咖啡这件事", "forget")
    chat(host, "还记得我喜欢喝什么吗？", "recall")
    assert "喜欢咖啡" not in visible_context(model)


def test_shared_quotation_is_recalled_with_attribution_not_as_user_identity(tmp_path: Path) -> None:
    model = RecordingLLM()
    host = host_for(tmp_path, model)
    source = "我读到一段人物资料：“我住在松风镇，是一名陶艺师。”这是小说人物的介绍。"
    sent = chat(host, source)
    records = host.memories(host.conversations()[0]["id"])["memories"]
    assert len(records) == 1
    assert records[0]["content"] == source
    assert records[0]["kind"] == "shared_moment"
    assert records[0]["evidence_turn_ids"] == [sent["user"]["id"]]
    assert not host.memory.profile(LOCAL_USER, host.scope(host.conversations()[0]["id"])).identity
    chat(host, "松风镇那段资料里的陶艺师指谁？", "recall", host.new_conversation()["id"])
    context = visible_context(model)
    assert "quoted_material_reference" in context and source in context


def test_model_literal_event_reaches_new_chat_without_vector_service(tmp_path: Path) -> None:
    source = "我昨天买了个紫色水杯，杯身印着一只猫头鹰。"
    proposal = {
        "memory_candidates": [
            {
                "kind": "shared_moment",
                "title": "买了水杯",
                "content": source,
                "subject_actor_id": LOCAL_USER,
                "confidence": 0.99,
            }
        ]
    }
    body = {
        "model": "local-fixture",
        "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(proposal)}}],
    }
    with provider(body=body) as (url, requests):
        model = RecordingLLM()
        host = host_for(tmp_path, model)
        host.save_settings(
            SettingsUpdate(
                settings=RomanceSettings(
                    model_mode="api",
                    storage_consent=True,
                    model_consent=True,
                    cognition=CognitionSettings(model_extraction=True, embedding_backend="off"),
                    deepseek=DeepSeekConfig(base_url=url, model="local-fixture"),
                ),
                api_key=SecretStr("local-fixture-only"),
            )
        )
        original = chat(host, source)
        records = host.memories(host.conversations()[0]["id"])["memories"]
        assert len(records) == 1 and records[0]["content"] == source
        assert records[0]["evidence_turn_ids"] == [original["user"]["id"]]
        assert requests[0]["body"]["thinking"] == {"type": "disabled"}
        assert requests[0]["body"]["max_tokens"] == host.settings.deepseek.max_tokens
        memory_block = visible_context(model).split("[RELEVANT MEMORY]\n", 1)[1]
        guidance = json.loads(memory_block.split("\n\n[CONVERSATION ATTRIBUTION]", 1)[0])[
            "guidance"
        ]
        assert 'application_memory:{"learned": 1}' in guidance
        chat(host, "我昨天买的水杯是什么样子的？", "recall", host.new_conversation()["id"])
        assert "紫色水杯" in visible_context(model) and "猫头鹰" in visible_context(model)


def test_model_copy_cannot_keep_an_old_favorite_active_after_update(tmp_path: Path) -> None:
    source = "我现在最喜欢的饮品是白桃乌龙。"
    proposal = {
        "memory_candidates": [
            {
                "kind": "preference",
                "title": "喜欢的饮品",
                "content": source,
                "subject_actor_id": LOCAL_USER,
                "predicate": "favorite_drink",
                "confidence": 0.99,
            }
        ]
    }
    body = {
        "model": "local-fixture",
        "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(proposal)}}],
    }
    with provider(body=body) as (url, _requests):
        host = host_for(tmp_path, RecordingLLM())
        host.save_settings(
            SettingsUpdate(
                settings=RomanceSettings(
                    model_mode="api",
                    storage_consent=True,
                    model_consent=True,
                    cognition=CognitionSettings(model_extraction=True, embedding_backend="off"),
                    deepseek=DeepSeekConfig(base_url=url, model="local-fixture"),
                ),
                api_key=SecretStr("local-fixture-only"),
            )
        )
        chat(host, source)
        assert len(host.memories(host.conversations()[0]["id"])["memories"]) == 1
        chat(host, "更新一下，我现在最喜欢的是茉莉绿茶；白桃乌龙是以前的答案了。", "update")
        records = host.memories(host.conversations()[0]["id"])["memories"]
        assert any("茉莉绿茶" in r["content"] for r in records)
        assert not any("白桃乌龙" in r["content"] for r in records)
