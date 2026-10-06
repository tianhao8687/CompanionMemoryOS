"""Source, clock, preference and creation regressions; not a naturalness score."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from companion_agent.cognition import CognitionSettings
from companion_agent.communication import communication_preferences
from companion_agent.llm import wire_input_tokens
from companion_agent.relationship.models import RelationshipChangeType, RelationshipThread
from companion_memoryos.discourse import fact_recall_clauses
from companion_memoryos.schemas import InterpreterOutput, TurnInterpretation
from tests.test_chat_features import seed
from tests.test_companion_functional import chat, host_for
from tests.test_memory_nook import create, setup
from tests.test_romance_app import RecordingLLM


def test_model_guessed_concern_does_not_become_a_relationship_problem(tmp_path: Path) -> None:
    model = RecordingLLM()
    host = host_for(tmp_path, model)

    class Interpreter:
        def interpret(self, context):
            return InterpreterOutput(
                model_fingerprint="untrusted-test-extractor",
                interpretation=TurnInterpretation.model_validate(
                    {
                        "open_loop_candidates": [
                            {
                                "kind": "ongoing_concern",
                                "summary": "用户担忧这段关系中的金钱索取",
                                "topic_keys": ["金钱", "关系"],
                            }
                        ]
                    }
                ),
            )

    host.memory.turn_interpreter = Interpreter()
    try:
        chat(host, "房东合法收租，你想从我这儿拿什么？我钱也不多哈哈。", "tease")
        loops = host.memory.list_open_loops("romance-user")
        assert len(loops) == 1 and loops[0].metadata["candidate_only"]
        assert "用户担忧这段关系中的金钱索取" not in model.inputs[-1][1].content
        assert not host.agent.relationships.get_relationship(host.key).unresolved_threads
        assert not host.agent.relationships.evidence_valid(
            host.key, f"open_loop:{loops[0].id}", loops[0].opened_at
        )
        assert "房东合法收租" in model.inputs[-1][-1].content
        # Simulate a projection persisted before candidate authority was checked.
        relationships = host.agent.relationships
        prior = relationships.get_relationship(host.key)
        legacy = prior.model_copy(deep=True)
        legacy.unresolved_threads.append(
            RelationshipThread(
                id="legacy-candidate",
                topic="关系",
                summary=loops[0].summary,
                opened_at=loops[0].opened_at,
                last_updated_at=loops[0].opened_at,
                evidence_ids=[f"open_loop:{loops[0].id}"],
                open_loop_id=loops[0].id,
            )
        )
        relationships.store.save(
            prior,
            legacy,
            RelationshipChangeType.THREAD_OPENED,
            "legacy fixture",
            [f"open_loop:{loops[0].id}"],
            loops[0].opened_at,
        )
        assert relationships.store.get(host.key).unresolved_threads
        assert not relationships.get_relationship(host.key).unresolved_threads
        assert host.memory.list_open_loops("romance-user")[0].summary == loops[0].summary
    finally:
        host.memory.close_indexer()


@pytest.mark.parametrize(
    "text",
    [
        "刚才聊得有点散，帮我捋捋周末的事：我跟朋友那边怎么排，我带什么？",
        "把我们之前商量的几件事整理一下。",
        "咱们明天早餐几点在哪儿，周六干什么？我怕记串了。",
        "我们下周几点在哪碰头？",
    ],
)
def test_recap_imperatives_authorize_reusing_prior_evidence(text: str) -> None:
    assert fact_recall_clauses(text)


@pytest.mark.parametrize(
    "text",
    [
        "别总结刚才说过的事。",
        "如果我说把之前的安排整理一下，你再整理。",
        "她说：把我们之前商量的几件事整理一下。",
        "帮我整理桌面，刚才水洒了。",
        "如果咱们明天几点在哪儿见，你到时再回答。",
        "她说：咱们明天几点在哪儿见？",
        "我们明天几点见比较合适？",
        "我们明天应该怎么安排？",
    ],
)
def test_recap_classifier_excludes_other_tasks_and_non_requests(text: str) -> None:
    assert not fact_recall_clauses(text)


def test_sleep_preference_persists_but_can_change_and_be_forgotten(tmp_path: Path) -> None:
    model = RecordingLLM()
    host = host_for(tmp_path, model)
    first = chat(host, "以后别催我睡觉，别提前说晚安。", "preference")
    try:
        host = host_for(tmp_path, model)
        chat(host, "我还想给你看今天拍的树。", "tree")
        assert "用户不希望被催睡" in model.inputs[-1][0].content
        assert first["user"]["id"] in model.inputs[-1][1].content
        updated = chat(host, "以后可以提醒我睡觉。", "changed")
        assert "用户允许提醒休息" in model.inputs[-1][0].content
        assert "用户不希望被催睡" not in model.inputs[-1][0].content
        host.memory.forget_turn(updated["user"]["id"], "romance-user")
        host.memory.forget_turn(first["user"]["id"], "romance-user")
        chat(host, "这棵树的叶子开始黄了。", "later")
        assert "用户允许提醒休息" not in model.inputs[-1][0].content
        assert "用户不希望被催睡" not in model.inputs[-1][0].content
        assert not communication_preferences("她说别催我睡觉。")
    finally:
        host.memory.close_indexer()


def test_multi_topic_recap_keeps_distinct_plans_and_latest_change(tmp_path: Path) -> None:
    model = RecordingLLM()
    host = host_for(tmp_path, model, cognition=CognitionSettings(embedding_backend="off"))
    try:
        facts = [
            "周六上午我自己去花市。",
            "周六下午约了小宁去陶艺展。",
            "周日下午三点到你家，一起修唱片机。",
            "周日我带豆沙饼，喝的我带茉莉茶。",
            "修唱片机预算二百，面板用深蓝色。",
            "唱片机预算改成一百六，面板颜色不变。",
        ]
        for n, fact in enumerate(facts):
            chat(host, fact, f"fact-{n}")
        for n in range(14):
            chat(host, f"今天路过第{n}条街，看到一只小鸟。", f"filler-{n}")
        chat(
            host,
            "刚才东一句西一句说得有点散。帮我捋捋周末：朋友那边怎么排，"
            "咱俩什么时候见，我带什么，唱片机最后商量成什么样。",
            "recap",
        )
        evidence = model.inputs[-1][1].content
        for expected in ("花市", "小宁", "陶艺展", "三点", "豆沙饼", "茉莉茶", "一百六"):
            assert expected in evidence, expected
        system = model.inputs[-1][0].content
        plan = json.JSONDecoder().raw_decode(system.split("[MEMORY USE PLAN]\n", 1)[1])[0]
        assert any(d["mode"] == "explicit_recall" for d in plan["decisions"])
        assert not any(
            "already_referenced_in_conversation" in d["reasons"] for d in plan["decisions"]
        )
        clock = json.JSONDecoder().raw_decode(evidence.split("[APPLICATION CLOCK]\n", 1)[1])[0]
        local = datetime.fromisoformat(clock["message_received_at"])
        assert clock["timezone"] == "Asia/Shanghai"
        assert local.utcoffset() is not None and local.utcoffset().total_seconds() == 28800
        assert clock["weekday"] == "星期" + "一二三四五六日"[local.weekday()]
    finally:
        host.memory.close_indexer()


def test_bare_time_agreement_survives_multi_topic_shared_plan_recall(tmp_path: Path) -> None:
    model = RecordingLLM()
    host = host_for(tmp_path, model, cognition=CognitionSettings(embedding_backend="off"))
    try:
        chat(host, "明天九点一刻，楼下花店。", "time-place")
        chat(host, "周六一起去河边散步。", "second-plan")
        for n in range(16):
            chat(host, f"今天第{n}次看见邻居的猫打哈欠。", f"cat-{n}")
        chat(host, "对了，咱们明天几点在哪儿，周六干什么？我怕记串了。", "recap")
        wire = "\n".join(m.content for m in model.inputs[-1])
        assert "九点一刻" in wire and "楼下花店" in wire
        assert "河边散步" in wire
        assert "explicit_recall" in model.inputs[-1][0].content
    finally:
        host.memory.close_indexer()


def test_chinese_nook_context_is_packed_without_escaping_inflation(tmp_path: Path) -> None:
    client, model, host = setup(tmp_path)
    try:
        for i in range(12):
            seed(host, f"第{i}个小物件：" + "喜欢奶油陶瓷杯，杯子边缘有一颗手画的小星星。" * 40)
        room = create(client)
        assert room["status"] == "created", room
        assert room["error_code"] is None
        messages = model.drafts[0]
        payload = json.loads(messages[-1].content)
        assert payload["sources"] and len(payload["sources"]) < 12
        assert wire_input_tokens([m.wire() for m in messages], host.memory.token_counter) <= 7500
        for source in payload["sources"]:
            assert host.nook.source(source["ref"]) == source
    finally:
        host.nook.close()
        host.memory.close_indexer()


def test_nook_failure_stage_is_safe_and_persistent(tmp_path: Path) -> None:
    client, model, host = setup(tmp_path)
    try:
        seed(host, "买了一只奶油色杯子。")
        model.invalid = True
        room = create(client)
        assert room["status"] == "failed"
        assert room["error_code"] == "selection_validation"
        with host.database.connection() as db:
            saved = db.execute(
                "SELECT error_code FROM nook_runs ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
        assert saved[0] == room["error_code"]
        assert len(model.drafts) == 1 and not model.paintings
    finally:
        host.nook.close()
        host.memory.close_indexer()


def test_story_request_can_reuse_known_characters_without_claiming_real_events(
    tmp_path: Path,
) -> None:
    model = RecordingLLM()
    host = host_for(tmp_path, model, cognition=CognitionSettings(embedding_backend="off"))
    try:
        chat(host, "楼下那只橘猫叫店长。", "cat")
        chat(host, "我在纸上画了只蓝猫，叫小蓝。", "drawing")
        chat(host, "店长和小蓝叫什么，你还记得吗？", "recall")
        chat(host, "帮我写个店长和小蓝在花店过夜的小故事。", "story")
        prompt = "\n".join(m.content for m in model.inputs[-1])
        assert "楼下那只橘猫叫店长" in prompt
        assert "我在纸上画了只蓝猫" in prompt
        plan = json.JSONDecoder().raw_decode(prompt.split("[MEMORY USE PLAN]\n", 1)[1])[0]
        assert not any(
            "already_referenced_in_conversation" in d["reasons"] for d in plan["decisions"]
        )
    finally:
        host.memory.close_indexer()
