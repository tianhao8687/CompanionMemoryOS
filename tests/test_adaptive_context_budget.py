"""Actual chat composition, including the fixed-budget control and constrained requests."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from companion_agent import CompanionAgent, load_persona
from companion_agent.cognition import ApplicationMemory, CognitionSettings
from companion_agent.deepseek import DeepSeekConfig
from companion_memoryos.context_budget import fit_context_budget
from companion_memoryos.schemas import (
    AnswerSemantics,
    ConsentState,
    ConversationRole,
    ConversationTurnInput,
    ExperienceEvidenceKind,
    MemoryInput,
    MemoryKind,
    MemoryScope,
    ProcessTurnRequest,
    RecallRequest,
    RetrievalAction,
)
from companion_memoryos.service import CompanionMemoryService

QUERY = "帮我回忆并整理档案 AB01、AB02、AB03、AB04、AB05、AB06 各自的封套保管位置。"


@pytest.fixture
def memory(service: CompanionMemoryService):
    memory = ApplicationMemory(service.store, service.config)
    memory.configure(
        CognitionSettings(extract_memory=False, embedding_backend="off"),
        offline=True,
        model=DeepSeekConfig(),
        key=None,
    )
    yield memory
    memory.close_indexer()


def scope(conversation: str) -> MemoryScope:
    return MemoryScope(
        companion_id="companion", relationship_id="adaptive", conversation_id=conversation
    )


def append(
    memory: ApplicationMemory,
    content: str,
    conversation: str = "archive",
    *,
    assistant: bool = False,
):
    result = memory.append_turn(
        ConversationTurnInput(
            user_id="user",
            scope=scope(conversation),
            actor_id="companion" if assistant else "user",
            role=ConversationRole.ASSISTANT if assistant else ConversationRole.USER,
            content=content,
            consent=ConsentState.GRANTED,
        )
    )
    assert result.turn
    return result.turn


def seed(memory: ApplicationMemory) -> list[str]:
    return [
        append(
            memory,
            f"档案 AB{index:02} 的封套保管位置是 K{index:02} 柜。"
            + "本次现场交接同时核对了封面、页码、登记信息和签名。" * 35,
        ).id
        for index in range(1, 7)
    ]


def request(conversation: str, **extra: object) -> ProcessTurnRequest:
    return ProcessTurnRequest.model_validate(
        {
            "user_id": "user",
            "scope": scope(conversation),
            "content": QUERY,
            "idempotency_key": conversation,
            "consent": "granted",
            "model_consent": "granted",
            **extra,
        }
    )


def evidence_ids(context) -> set[str]:
    for message in context.messages:
        marker = "[RELEVANT MEMORY]\n"
        if message.role == "user" and marker in message.content:
            data = json.JSONDecoder().raw_decode(message.content.split(marker, 1)[1])[0]
            return {item["id"] for item in data["evidence"]}
    return set()


def test_spare_context_recovers_evidence_with_one_search(memory, monkeypatch):
    sources = set(seed(memory))
    calls = []
    original = memory.recall

    def recall(item):
        calls.append(item)
        return original(item)

    monkeypatch.setattr(memory, "recall", recall)
    fixed = CompanionAgent(memory, load_persona(), adaptive_memory_budget=False)
    baseline = fixed.prepare(request("comparison"))
    adaptive = CompanionAgent(memory, load_persona())
    result = adaptive.prepare(request("comparison"))
    assert len(calls) == 2  # One per turn; no rerun of retrieval or extraction to expand.
    assert calls[0].max_tokens == 2500
    assert calls[1].max_tokens == 8000
    assert len(sources & evidence_ids(baseline.context)) < 6
    assert sources <= evidence_ids(result.context)
    serialized = json.dumps([m.model_dump() for m in result.context.messages], ensure_ascii=False)
    assert memory.token_counter.count(serialized) <= 16000
    assert all(
        "本次现场交接" not in m.content for m in result.context.messages if m.role == "system"
    )


def test_allocation_shrinks_around_required_recent_dialogue(memory, monkeypatch):
    sources = set(seed(memory))
    recent = append(memory, "请保留这轮文字。" + "银杏在风里缓慢摇摆。" * 550, "crowded")
    reply = append(memory, "收到这轮文字。", "crowded", assistant=True)
    events = {}
    monkeypatch.setattr(
        "companion_agent.runtime.record", lambda name, value: events.update({name: value})
    )
    agent = CompanionAgent(memory, load_persona())
    prepared = agent.prepare(request("crowded"))
    assert recent.id in prepared.context_turn_ids and reply.id in prepared.context_turn_ids
    allocation = events["memory_allocation"]
    assert allocation["allocated_token_budget"] < 8000
    assert allocation["context_tokens"] <= 16000
    assert allocation["allocation_attempts"] > 0
    admitted = sources & evidence_ids(prepared.context)
    assert 0 < len(admitted) < 6
    planned = {
        d.evidence.id
        for d in prepared.plan.memory_use_plan.decisions
        if d.evidence.kind is ExperienceEvidenceKind.TURN
    }
    assert planned & sources == admitted
    assert all(memory.store.get_turn(identifier, "user").content for identifier in sources)


def test_reallocates_candidates_after_history_is_trimmed(memory, monkeypatch):
    sources = set(seed(memory))
    old = append(memory, "既往闲聊。" + "银杏在风里缓慢摇摆。" * 1200, "trim")
    append(memory, "那是旧话题。", "trim", assistant=True)
    latest = append(memory, "今天聊新的事情。", "trim")
    append(memory, "我在。", "trim", assistant=True)
    events = {}
    monkeypatch.setattr(
        "companion_agent.runtime.record", lambda name, value: events.update({name: value})
    )
    prepared = CompanionAgent(memory, load_persona()).prepare(request("trim"))
    assert old.id not in prepared.context_turn_ids and latest.id in prepared.context_turn_ids
    assert sources <= evidence_ids(prepared.context)
    assert events["memory_allocation"]["context_tokens"] <= 16000


def test_caller_budget_is_not_expanded(memory, monkeypatch):
    seed(memory)
    calls = []
    original = memory.recall

    def recall(item):
        calls.append(item)
        return original(item)

    monkeypatch.setattr(memory, "recall", recall)
    agent = CompanionAgent(memory, load_persona())
    explicit = RecallRequest(
        user_id="user",
        scope=scope("explicit"),
        query=QUERY,
        include_turn_evidence=True,
        include_relationship_turns=True,
        max_tokens=600,
        max_characters=2000,
        turn_limit=2,
    )
    agent.prepare(request("explicit", recall_request=explicit))
    assert len(calls) == 1
    assert (calls[0].max_tokens, calls[0].max_characters, calls[0].turn_limit) == (600, 2000, 2)


def test_repeated_task_does_not_displace_answer_sources(memory):
    sources = set(seed(memory))
    earlier = append(memory, QUERY, "old-question")
    prepared = CompanionAgent(memory, load_persona()).prepare(request("repeat"))
    assert sources <= evidence_ids(prepared.context)
    assert earlier.id not in evidence_ids(prepared.context)
    historical = memory.recall(
        RecallRequest(
            user_id="user",
            scope=scope("old-question"),
            query=QUERY,
            include_turn_evidence=True,
            answer_semantics=AnswerSemantics.UTTERANCE_HISTORY,
            utterance_actor_id="user",
            turn_limit=1,
            max_tokens=8000,
        )
    )
    assert historical.turn_fallback[0].turn.id == earlier.id


def test_repacking_preserves_boundaries_and_does_not_mutate_sources(memory):
    seed(memory)
    memory.remember(
        MemoryInput(
            user_id="user",
            scope=scope("archive"),
            kind=MemoryKind.BOUNDARY,
            title="称呼",
            content="不要叫我宝贝。",
            consent=ConsentState.GRANTED,
            explicit_user_request=True,
        )
    )
    context = memory.recall(
        RecallRequest(
            user_id="user",
            scope=scope("archive"),
            query=QUERY,
            include_turn_evidence=True,
            max_tokens=8000,
            max_characters=20000,
            turn_limit=6,
            answer_cardinality="open",
        )
    )
    original = context.model_dump_json()
    small = fit_context_budget(context, memory.token_counter, max_tokens=1)
    assert small.sections["boundaries"][0].pinned
    assert small.safety_budget_exceeded and small.budget_exhausted
    assert not small.turn_fallback
    assert small.retrieval_action is RetrievalAction.ABSTAIN
    assert context.model_dump_json() == original
    assert small.rendered_tokens == memory.token_counter.count(small.prompt_text)
    for invalid in (0, -1):
        with pytest.raises(ValueError, match="positive"):
            fit_context_budget(context, memory.token_counter, max_tokens=invalid)


def test_ordinary_chat_has_a_smaller_ceiling(memory, monkeypatch):
    events = {}
    monkeypatch.setattr(
        "companion_agent.runtime.record", lambda name, value: events.update({name: value})
    )
    CompanionAgent(memory, load_persona()).prepare(request("ordinary", content="今天阳光真好。"))
    assert events["memory_allocation"]["candidate_token_ceiling"] == 4000
    assert not events["memory_allocation"]["facts_required"]


def test_partial_state_history_cannot_be_presented_as_a_complete_answer(memory):
    valid_at = datetime(2026, 6, 1, tzinfo=UTC)
    for content in ("六月时我说我喜欢你。", "六月那句是在演戏。"):
        memory.remember(
            MemoryInput(
                user_id="user",
                scope=scope("state"),
                kind=MemoryKind.RELATIONSHIP,
                title="关系自述",
                content=content,
                stable_key="relationship:affection",
                predicate="self_reported_affection",
                consent=ConsentState.GRANTED,
                explicit_user_request=True,
                event_at=valid_at,
                valid_time_start=valid_at,
            )
        )
    context = memory.recall(
        RecallRequest(
            user_id="user",
            scope=scope("state"),
            query="六月时的关系自述有哪些变化？",
            state_predicate="self_reported_affection",
            valid_at=valid_at,
            answer_semantics=AnswerSemantics.CHANGE_TRAJECTORY,
            max_tokens=8000,
            max_characters=20000,
        )
    )
    assert context.state_result and len(context.state_result.memories) == 2
    empty = fit_context_budget(context, memory.token_counter, max_tokens=1)
    partial = fit_context_budget(
        context,
        memory.token_counter,
        max_tokens=(context.rendered_tokens + empty.rendered_tokens) // 2 + 5,
    )
    assert partial.state_result and len(partial.state_result.memories) == 1
    assert partial.state_evidence_omitted_count == 1
    assert partial.retrieval_action is RetrievalAction.ABSTAIN
    assert len(context.state_result.memories) == 2


def test_consecutive_long_messages_fit_without_changing_either_source(memory, monkeypatch):
    padding = ("窗外的银杏在风中摇摆，走廊尽头的灯亮着。" * 400)[:5680]
    first_text = "上半篇材料。" + padding + "档案 LH31 的封套在青鹭柜。"
    second_text = "下半篇材料。" + padding + "档案 LH32 的封套在白鲸柜。"
    first = append(memory, first_text, "long")
    reply = append(memory, "收到上半篇材料。", "long", assistant=True)
    events = {}
    monkeypatch.setattr(
        "companion_agent.runtime.record", lambda name, value: events.update({name: value})
    )
    agent = CompanionAgent(memory, load_persona())
    prepared = agent.prepare(request("long", content=second_text))
    assert prepared.context.messages[-1].content == second_text
    assert events["prepared"]["context_tokens"] <= 16000
    assert {first.id, reply.id} <= set(events["prepared"]["history_trimmed_ids"])
    assert {first.id, reply.id}.isdisjoint(prepared.context_turn_ids)
    assert "budget_omitted_turn_ids" in prepared.context.text
    assert memory.store.get_turn(first.id, "user").content == first_text
    assert memory.store.get_turn(prepared.user_turn.id, "user").content == second_text
    recalled = agent.prepare(request("later", content="帮我回忆档案 LH31 的封套保管位置。"))
    assert first.id in evidence_ids(recalled.context)
    assert "青鹭柜" in recalled.context.text


def test_long_explicit_quote_is_never_silently_evicted(memory):
    padding = ("窗外的银杏在风中摇摆，走廊尽头的灯亮着。" * 400)[:5680]
    first = append(memory, padding + "这是必须引用的原文。", "quote-long")
    append(memory, "收到原文。", "quote-long", assistant=True)
    with pytest.raises(ValueError, match="main context exceeds budget"):
        CompanionAgent(memory, load_persona()).prepare(
            request("quote-long", content=padding, reply_to_turn_id=first.id)
        )
    assert memory.store.list_response_plans("user") == []


def test_repeated_recall_requests_cannot_crowd_out_earlier_answer(memory):
    original = append(memory, "档案 GD473 的封套保存在青鹭柜。", "old")
    question_ids = set()
    for index in range(24):
        question_ids.add(
            append(
                memory, f"帮我回忆档案 GD{473 + index % 4} 的封套保管位置。", f"query-{index}"
            ).id
        )
    mixed = append(memory, "档案 GD474 的封套在白鲸柜。请帮我回忆之前的安排。", "mixed")
    prepared = CompanionAgent(memory, load_persona()).prepare(
        request("fresh", content="帮我回忆档案 GD473 的封套保管位置。")
    )
    assert original.id in evidence_ids(prepared.context)
    assert "青鹭柜" in prepared.context.text
    # An independent assertion in a mixed statement must not be classified as a pure request.
    assert mixed.id in evidence_ids(prepared.context)
    assert len(evidence_ids(prepared.context) & question_ids) < 6
