"""Read contracts at the final model boundary using normal chat ingestion."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

from companion_agent import CompanionAgent, load_persona
from companion_agent.cognition import ApplicationMemory, CognitionSettings
from companion_agent.deepseek import DeepSeekConfig
from companion_agent.llm import ModelResponse
from companion_memoryos.schemas import (
    ConsentState,
    ExperienceEvidenceKind,
    MemoryReferenceFeedbackInput,
    MemoryReferenceMode,
    MemoryScope,
    ProcessTurnRequest,
    ReferenceFeedbackKind,
)


class Recorder:
    def __init__(self):
        self.messages = []

    def generate(self, messages):
        self.messages = messages
        return ModelResponse(text="收到。", model="offline-read-contract")


@pytest.fixture
def chat(service):
    memory = ApplicationMemory(service.store, service.config)
    memory.configure(
        CognitionSettings(extract_memory=False, embedding_backend="off"),
        offline=True,
        model=DeepSeekConfig(),
        key=None,
    )
    recorder = Recorder()
    agent = CompanionAgent(memory, load_persona(), recorder)
    try:
        yield agent, recorder
    finally:
        memory.close_indexer()


def turn(content, session, **changes):
    return ProcessTurnRequest.model_validate(
        dict(
            user_id="reader",
            scope=MemoryScope(
                companion_id="xiaohe", relationship_id="reading", conversation_id=session
            ),
            content=content,
            idempotency_key=str(uuid4()),
            consent=ConsentState.GRANTED,
            model_consent=ConsentState.GRANTED,
        )
        | changes
    )


CASES = [
    (
        "青岚工坊的备用钥匙放在靠窗的第二个抽屉，抽屉正面贴着银色圆点。",
        "青岚工坊的备用钥匙放在什么地方？",
        "靠窗的第二个抽屉",
    ),
    (
        "北辰观测站的替换镜头寄存在门口的绿柜，柜子上写着星图器材。",
        "北辰观测站的替换镜头寄存在哪里？",
        "门口的绿柜",
    ),
    (
        "山岚展厅的红色画筒交给了管理员许棠，取件时出示纸质登记单。",
        "山岚展厅的红色画筒交给了谁？",
        "管理员许棠",
    ),
    (
        "霁汀维修单缺的衬片编号是 LV-284，顾洵安排周三送达，当前仍未验收。",
        "霁汀维修单缺的是什么编号，哪天送来，验收了吗？",
        "LV-284",
    ),
    (
        "晚岚交付单注明：图册装入墨绿色纸盒，收件人为岑谕，运费到付。",
        "晚岚图册用什么包装，寄给谁，运费怎样支付？",
        "墨绿色纸盒",
    ),
]


@pytest.mark.parametrize("case", CASES, ids=["key", "lens", "drawing", "repair", "delivery"])
@pytest.mark.parametrize("position", ["short", "start", "middle", "end"])
def test_cross_session_fact_reaches_final_model_with_source_identity(chat, case, position):
    agent, recorder = chat
    fact, query, expected = case
    background = "清点记录：纸样按尺寸分组，灯具按序编号，走廊保持通畅。\n" * 55
    source = {
        "short": fact,
        "start": fact + "\n" + background * 2,
        "middle": background + fact + "\n" + background,
        "end": background * 2 + fact,
    }[position]
    first = agent.chat(turn(source, "archive"))
    response = agent.chat(turn(query, "new-session"))
    assert recorder.messages[-1].content == query
    assert any(expected in message.content for message in recorder.messages)
    assert not any(
        expected in message.content for message in recorder.messages if message.role == "system"
    )
    context_message = next(
        message.content
        for message in recorder.messages
        if message.content.startswith("[APPLICATION CONTEXT]")
    )
    payload = json.JSONDecoder().raw_decode(context_message.split("[RELEVANT MEMORY]\n", 1)[1])[0]
    evidence = [item for item in payload["evidence"] if item["id"] == first.turn.reply_to_turn_id]
    assert evidence and expected in evidence[0]["content"]
    if evidence[0].get("source_span"):
        start, end = evidence[0]["source_span"]
        assert evidence[0]["content"] == source[start:end]
    assert response.turn.reply_to_turn_id != first.turn.reply_to_turn_id


@pytest.mark.parametrize("case", [CASES[0], CASES[-1]], ids=["strong-match", "weak-match"])
@pytest.mark.parametrize(
    "restriction",
    [
        "forget",
        "different-user",
        "different-relationship",
        "do-not-reference",
        "wrong-match",
    ],
)
def test_restricted_source_does_not_reach_final_model(chat, restriction, case):
    agent, recorder = chat
    fact, query, expected = case
    saved = agent.chat(turn(fact, "archive"))
    request = turn(query, "new-session")
    if restriction == "forget":
        agent.memory.forget_turn(saved.turn.reply_to_turn_id, "reader")
    elif restriction == "different-user":
        request = request.model_copy(update={"user_id": "stranger", "actor_id": "stranger"})
    elif restriction == "different-relationship":
        request = request.model_copy(
            update={"scope": request.scope.model_copy(update={"relationship_id": "unrelated"})}
        )
    else:
        agent.memory.record_reference_feedback(
            MemoryReferenceFeedbackInput(
                user_id="reader",
                scope=request.scope.model_copy(update={"conversation_id": None}),
                evidence_kind=ExperienceEvidenceKind.TURN,
                evidence_id=saved.turn.reply_to_turn_id,
                kind=(
                    ReferenceFeedbackKind.DO_NOT_REFERENCE
                    if restriction == "do-not-reference"
                    else ReferenceFeedbackKind.WRONG_MATCH
                ),
            )
        )
    agent.chat(request)
    assert all(expected not in message.content for message in recorder.messages)


def test_candidate_reading_does_not_upgrade_confidence_or_force_a_callback(chat):
    agent, _ = chat
    fact, query, _ = CASES[-1]
    saved = agent.chat(turn(fact, "archive"))
    prepared = agent.prepare(turn(query, "new-session"))
    decisions = [
        d
        for d in prepared.plan.memory_use_plan.decisions
        if d.evidence.id == saved.turn.reply_to_turn_id
    ]
    assert len(decisions) == 1
    assert decisions[0].mode is MemoryReferenceMode.SOURCE_CONTEXT
    payload = json.JSONDecoder().raw_decode(
        next(
            m.content
            for m in prepared.context.messages
            if m.content.startswith("[APPLICATION CONTEXT]")
        ).split("[RELEVANT MEMORY]\n", 1)[1]
    )[0]
    item = next(e for e in payload["evidence"] if e["id"] == saved.turn.reply_to_turn_id)
    assert item["retrieval_confidence"] < agent.memory.config.retrieval.confidence_hedge_threshold
    assert item["content"] == fact
    assert not any(beat.kind.value == "memory_reference" for beat in prepared.plan.beats)
    assert not agent.memory.list_memories("reader")
