"""Ordinary factual questions must receive an explicit, evidence-backed recall plan."""

import json
from pathlib import Path

import pytest

from companion_memoryos.config import load_config
from companion_memoryos.discourse import grounded_model_signals, interpret_explicit_discourse
from companion_memoryos.schemas import DiscourseSignal, MemoryScope
from tests.test_companion_functional import chat, host_for
from tests.test_romance_app import RecordingLLM


@pytest.mark.parametrize(
    "text",
    [
        "我那把折叠伞是什么颜色，伞柄上有什么？",
        "我那把折叠伞有几根伞骨、花了多少钱？",
        "我的杯子上印着什么？",
        "我的备用耳机放哪儿了？",
        "备用耳机放哪儿了？",
        "我的汽车是哪年买的？",
        "那次画展和植物园隔了几天？",
        "之前那本小说叫什么名字？",
        "我的伞是不是青绿色的？",
        "我的行李箱什么颜色",
        "我最喜欢的饮品是什么？",
        "回到我最初说的那只便携水壶，它是什么颜色，盖子上画着什么？我有说过为什么买它吗？",
        "说回我之前提过的那本画册，它是什么颜色？",
        "我有说过那只杯子在哪里买的吗？",
    ],
)
def test_personal_fact_questions_are_recall_requests(text: str) -> None:
    result = interpret_explicit_discourse(
        user_id="u", scope=MemoryScope(), turn_id="t", content=text, config=load_config()
    )
    assert result.user_asked_memory_question
    assert DiscourseSignal.MEMORY_QUESTION in grounded_model_signals(
        text, [DiscourseSignal.MEMORY_QUESTION], evidence_text=text
    )
    # A model's unrelated evidence span cannot ground this request.
    assert not grounded_model_signals(
        text, [DiscourseSignal.MEMORY_QUESTION], evidence_text="不相关的句子"
    )


@pytest.mark.parametrize(
    "text",
    [
        "我的新伞应该选什么颜色？",
        "我的伞选什么颜色好看？",
        "我的生日应该怎么过？",
        "我想买的那把伞适合下雨天吗？",
        "假如我的伞丢了，伞柄上应该系什么？",
        "如果有空，我那把伞是什么颜色？",
        "她问：我的伞是什么颜色？",
        "朋友说：“我那把伞是什么颜色？”",
        "把这句话翻译成英语：我的伞是什么颜色？",
        "我不想知道我的伞是哪里买的。",
        "请不要说我的伞是什么颜色。",
        "我的花什么颜色都有。",
        "我知道我的行李箱是什么颜色。",
        "我今天好累，怎么办？",
        "你想跟我怎么过周末？",
        "天空为什么是蓝色？",
        "回到我之前说的那本画册，它应该选什么颜色？",
        "朋友问：回到我最初说的那只水壶，它是什么颜色？",
        "回到我之前说的那本书。天空为什么是蓝色？",
    ],
)
def test_advice_quotations_and_statements_are_not_recall_requests(text: str) -> None:
    result = interpret_explicit_discourse(
        user_id="u", scope=MemoryScope(), turn_id="t", content=text, config=load_config()
    )
    assert not result.user_asked_memory_question
    assert not grounded_model_signals(text, [DiscourseSignal.MEMORY_QUESTION])


@pytest.mark.parametrize(
    "query,mode",
    [
        ("我的折叠伞是什么颜色，伞柄上有什么？", "explicit_recall"),
        ("我的折叠伞花了多少钱？", "soft_reference"),
    ],
)
def test_cross_session_fact_query_explicitly_uses_source_and_forgetting_still_wins(
    tmp_path: Path, query: str, mode: str
) -> None:
    model = RecordingLLM()
    host = host_for(tmp_path, model)
    source = "请记住，我的折叠伞是青绿色的，伞柄上系着一根米白色绳子。"
    learned = chat(host, source)
    chat(host, query, "recall", host.new_conversation()["id"])
    system, data = model.inputs[-1][:2]
    # Missing price evidence must retain uncertainty rather than force a confident recall.
    assert f'"mode":"{mode}"' in system.content, system.content.split("[MEMORY USE PLAN]")[-1]
    assert f'"use_mode":"{mode}"' in data.content
    assert source in data.content and learned["user"]["id"] in data.content
    assert "特意挑" not in data.content
    chat(host, "请忘记折叠伞的事", "forget")
    chat(host, query, "after-forget", host.new_conversation()["id"])
    assert "青绿色" not in model.inputs[-1][1].content


def test_custom_style_does_not_inherit_default_character_kernel_or_response_tone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from companion_agent import romance

    original = romance.load_persona

    def other_character():
        persona = original()
        persona.kernel.core_values = ["所有闲聊都讲解棋谱"]
        persona.kernel.dislikes = ["最讨厌散步"]
        for style in persona.response_styles.values():
            style.tone = ["说话必须咄咄逼人"]
            style.tendencies = ["每次都宣讲一遍个人原则"]
        return persona

    monkeypatch.setattr(romance, "load_persona", other_character)
    model = RecordingLLM()
    host = host_for(tmp_path, model, style="custom", custom_style="喜欢散步，讲话温暖随意。")
    chat(host, "晚上好")
    context = model.inputs[-1][0].content
    assert "喜欢散步，讲话温暖随意。" in context
    assert "所有闲聊都讲解棋谱" not in context and "最讨厌散步" not in context
    assert "说话必须咄咄逼人" not in context and "每次都宣讲一遍个人原则" not in context
    for rule in original().invariants:
        if rule.severity == "hard":
            assert rule.description in context
    assert "不能假装已有共同经历" in context


def test_compound_query_recalls_known_fields_without_inventing_unknown_fields(
    tmp_path: Path,
) -> None:
    model = RecordingLLM()
    host = host_for(tmp_path, model)
    source = "帮我记住：我的便携水壶是砖红色的，壶盖上画着一片枫叶。"
    learned = chat(host, source)
    chat(host, "帮我记住：我的折叠伞是青绿色的，伞柄上系着米白色绳子。", "distractor")
    # The fiction request must neither erase the real source nor turn into biography.
    chat(
        host,
        "一起想象短故事：砖红色水壶会说话，要跟我们冒险。",
        "fiction",
        host.new_conversation()["id"],
    )
    query = "回到我最初说的那只便携水壶，它是什么颜色，盖子上画着什么？我有说过为什么买它吗？"
    chat(host, query, "compound", host.new_conversation()["id"])
    system, data = model.inputs[-1][:2]
    assert source in data.content and learned["user"]["id"] in data.content
    source_memory = next(
        item for item in host.memory.store.list_memories("romance-user") if item.content == source
    )
    plan = json.loads(system.content.split("[MEMORY USE PLAN]\n")[-1])
    decision = next(
        item for item in plan["decisions"] if item["evidence"]["id"] == source_memory.id
    )
    assert decision["mode"] in {"explicit_recall", "soft_reference"}
    assert "水壶会说话" not in data.content
    # A different entity must not inherit the water-bottle attributes.
    chat(host, "我那顶遮阳帽是什么颜色？", "unrelated", host.new_conversation()["id"])
    assert "砖红色" not in model.inputs[-1][1].content
    chat(host, "忘记便携水壶的事", "forget-kettle")
    chat(host, query, "forgotten", host.new_conversation()["id"])
    assert "砖红色" not in model.inputs[-1][1].content
