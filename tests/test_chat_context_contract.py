"""Chinese chat contracts through real ingestion, planning and model input.

Only generation is replaced. Expectations and budgets do not come from runtime
decisions. These are development regressions, not an unseen language-quality set.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
import tiktoken

from companion_agent import CompanionAgent, load_persona
from companion_agent.cognition import ApplicationMemory, CognitionSettings
from companion_agent.context import ChatMessage
from companion_agent.deepseek import DeepSeekConfig
from companion_agent.experience import ExperienceType
from companion_agent.llm import ModelResponse
from companion_agent.relationship import RelationshipKey
from companion_memoryos.schemas import (
    ConsentState,
    ExperienceEvidenceKind,
    MemoryReferenceFeedbackInput,
    MemoryScope,
    MemoryStatus,
    ProcessTurnRequest,
    RecallIntent,
    RecallRequest,
    ReferenceFeedbackKind,
    ResponseGoal,
)
from companion_memoryos.service import CompanionMemoryService

SCOPE = MemoryScope(
    companion_id="xiaohe", relationship_id="context-contract", conversation_id="now"
)
KEY = RelationshipKey(user_id="user", companion_id="xiaohe", relationship_id="context-contract")


class RecordingModel:
    def __init__(self) -> None:
        self.inputs: list[list[ChatMessage]] = []
        self.reply = "嗯，我在听。"

    def generate(self, messages: list[ChatMessage]) -> ModelResponse:
        self.inputs.append([message.model_copy(deep=True) for message in messages])
        return ModelResponse(text=self.reply, model="offline-context-recorder")


@pytest.fixture
def memory(service: CompanionMemoryService) -> ApplicationMemory:
    result = ApplicationMemory(service.store, service.config)
    result.configure(
        CognitionSettings(embedding_backend="off"), offline=True, model=DeepSeekConfig(), key=None
    )
    return result


def request(text: str, key: str, conversation: str = "now") -> ProcessTurnRequest:
    return ProcessTurnRequest(
        user_id="user",
        scope=SCOPE.model_copy(update={"conversation_id": conversation}),
        content=text,
        idempotency_key=key,
        consent=ConsentState.GRANTED,
        model_consent=ConsentState.GRANTED,
    )


def model_evidence(messages: list[ChatMessage]) -> dict[str, Any]:
    for message in messages:
        if message.role == "user" and message.content.startswith("[APPLICATION CONTEXT]"):
            _, marker, body = message.content.partition("[RELEVANT MEMORY]\n")
            assert marker, "model input is missing its evidence payload"
            return json.JSONDecoder().raw_decode(body)[0]
    raise AssertionError("model did not receive application context")


@pytest.mark.parametrize(
    ("goal", "intent"),
    [
        (ResponseGoal.DIRECT_ANSWER, RecallIntent.GENERAL),
        (ResponseGoal.LISTEN, RecallIntent.GENERAL),
        (ResponseGoal.COMFORT, RecallIntent.COMFORT),
        (ResponseGoal.CELEBRATE, RecallIntent.CELEBRATE),
        (ResponseGoal.REFLECT, RecallIntent.REFLECT),
        (ResponseGoal.PROBLEM_SOLVE, RecallIntent.PLAN),
        (ResponseGoal.CHECK_IN, RecallIntent.CHECK_IN),
    ],
)
def test_host_goal_selects_independently_specified_recall_intent(
    memory: ApplicationMemory,
    monkeypatch: pytest.MonkeyPatch,
    goal: ResponseGoal,
    intent: RecallIntent,
) -> None:
    model = RecordingModel()
    agent = CompanionAgent(memory, load_persona(), model)
    calls: list[RecallRequest] = []
    real_recall = memory.recall

    def observe(item: RecallRequest):
        calls.append(item)
        return real_recall(item)

    monkeypatch.setattr(memory, "recall", observe)
    item = request("窗外正在下雨，想和你聊聊。", "goal")
    response = agent.chat(item, response_goal=goal)
    assert response.turn.metadata["response_goal"] == goal.value
    assert [call.intent for call in calls] == [intent]
    assert model.inputs[-1][-1].content == item.content


@pytest.mark.parametrize(
    "text",
    [
        "帮我给同事写条感谢消息，昨天他替我顶了班。",
        "昨天同事替我顶班，我想道个谢，这条消息怎么写？",
        "我准备谢谢昨天替班的同事，你给我拟一条能发出去的消息吧。",
    ],
    ids=["request-first", "reason-first", "statement-first"],
)
def test_writing_request_is_not_routed_as_emotional_reminiscence(
    memory: ApplicationMemory, monkeypatch: pytest.MonkeyPatch, text: str
) -> None:
    model = RecordingModel()
    agent = CompanionAgent(memory, load_persona(), model)
    intents: list[RecallIntent] = []
    real_recall = memory.recall

    def observe(item: RecallRequest):
        intents.append(item.intent)
        return real_recall(item)

    monkeypatch.setattr(memory, "recall", observe)
    response = agent.chat(request(text, "writing"))
    assert response.turn.metadata["response_goal"] in {"direct_answer", "problem_solve"}
    assert intents and set(intents) <= {RecallIntent.GENERAL, RecallIntent.PLAN}
    assert model.inputs[-1][-1].content == text


BACKGROUND = (
    "请记住我以前沿河堤去旧码头、公园和书店的散步路线。"
    "从南边的石桥下来先走靠水的一侧，那里能看见两排白色栏杆和一座报时钟。"
    "旧码头铁门右侧的墙上嵌着一块蓝色瓷砖，那是我辨认入口的地方。"
    "经过铁门以后要绕过旧仓库，仓库外墙有几张已经褪色的航运海报，门口常停着送货车。"
    "公园在仓库后面，东边的小门平时开着，西门离停车场更近，但是进出的人也多。"
    "穿过公园时我会沿花坛外侧走，不走中间的台阶，雨后石板上会积水。"
    "走出公园再沿河堤往北，先经过修鞋摊，然后才是那家临街的书店。"
    "书店门口的长椅朝着河面，旁边有一棵树，傍晚刚好能遮住斜照进来的太阳。"
    "回去时我会从书店后面的巷子绕回来，巷子比大路安静，也少两个红绿灯。"
    "整条散步路线不赶时间，大约要走一个小时，中途通常会在公园的饮水处停一会儿。"
)
RECENT = (
    "今天路过河堤书店，我在门口站了好一会儿。窗边摆着一本城市老照片集，"
    "封面是已经拆掉的车站，我以前每天上学都从那里经过。隔着玻璃看不清出版年份，"
    "但那张站前广场的照片让我一下想起小时候坐公交的样子。"
    "旁边还有两本旅行随笔，书脊已经晒得有点褪色，店员正在重新整理靠窗的书架。"
    "我没急着进去，在门口把橱窗从左到右看了一遍，又到旁边长椅上坐了一会儿。"
    "风从河面吹过来，能听见对岸有人说话。散步时这样停一下，跟一路走到底很不一样。"
)
REPLY = "那本老照片集把你留住了。隔着玻璃认出从前每天经过的车站，确实会想多看一会儿。"


@pytest.mark.parametrize("budget", [5000, 16000], ids=["fixed-pressure", "roomy-control"])
def test_normal_chat_budget_preserves_latest_exchange_before_old_background(
    memory: ApplicationMemory, budget: int
) -> None:
    model = RecordingModel()
    agent = CompanionAgent(memory, load_persona(), model)
    agent.chat(request(BACKGROUND, "route", "archive"))
    stored = [record for record in memory.list_memories("user") if record.content == BACKGROUND]
    assert len(stored) == 1
    background = stored[0]
    model.reply = REPLY
    previous = agent.chat(request(RECENT, "bookshop"))
    agent.max_context_tokens = budget
    current = "聊到河堤、旧码头、公园和书店这条散步路线，我就觉得书店那一段很有意思。"
    response = agent.chat(request(current, "continue"))
    messages = model.inputs[-1]
    native = [(message.role, message.content) for message in messages]
    assert native[-3:] == [("user", RECENT), ("assistant", REPLY), ("user", current)]
    assert response.turn.reply_to_turn_id != previous.turn.reply_to_turn_id
    assert not any(
        BACKGROUND in message.content for message in messages if message.role == "system"
    )
    serialized = json.dumps([message.wire() for message in messages], ensure_ascii=False)
    # Independent accounting at the actual model boundary, not the runtime's counter.
    assert len(tiktoken.get_encoding("cl100k_base").encode(serialized)) <= budget
    evidence = model_evidence(messages)["evidence"]
    selected_ids = {item["id"] for item in evidence if item["kind"] == "memory"}
    assert (background.id in selected_ids) is (budget == 16000)
    plan = next(
        plan
        for plan in memory.store.list_response_plans("user")
        if plan.trigger_turn_id == response.turn.reply_to_turn_id
    )
    assert (background.id in {d.evidence.id for d in plan.memory_use_plan.decisions}) is (
        budget == 16000
    )
    if budget == 5000:
        assert not any(
            use.memory_id == background.id and use.response_group_id == plan.id
            for use in memory.store.list_memory_uses("user")
        )
    assert memory.store.get(background.id, "user").status is MemoryStatus.ACTIVE


def test_chat_deduplicates_recalled_native_history_without_losing_attribution(
    memory: ApplicationMemory,
) -> None:
    model = RecordingModel()
    agent = CompanionAgent(memory, load_persona(), model)
    text = "我刚才在河堤书店的橱窗里看见了老车站的照片。"
    earlier = agent.chat(request(text, "photo"))
    question = "我刚才是在哪儿看见老车站照片的？"
    agent.chat(request(question, "photo-question"))
    messages = model.inputs[-1]
    assert sum(message.content.count(text) for message in messages) == 1
    assert any(
        message.role == "user"
        and message.content == text
        and message.source_turn_id == earlier.turn.reply_to_turn_id
        for message in messages
    )
    references = model_evidence(messages)["evidence"]
    assert any(
        item.get("id") == earlier.turn.reply_to_turn_id
        and item.get("content_in_recent_conversation") is True
        for item in references
    )


DETAIL = "没去青禾公司是因为通勤要换三次地铁，往返四小时，所以这次换工作先搁置。"


def seed_work_story(agent: CompanionAgent) -> str:
    story = (
        "最近我在考虑辞职，想换份工作。",
        DETAIL,
        "老板又找我谈了，我把手头的项目安排说清楚了。",
        "我决定再待一个月，先把交接文档整理好。",
    )
    source_id = None
    for index, text in enumerate(story):
        response = agent.chat(request(text, f"work-{index}", "archive"))
        if text == DETAIL:
            source_id = response.turn.reply_to_turn_id
    assert source_id
    return source_id


@pytest.mark.parametrize(
    "question",
    [
        "我当时没去青禾公司是什么原因？",
        "还记得青禾公司那件事吗，我后来为什么没去？",
    ],
    ids=["reason", "recollection"],
)
def test_chat_retains_source_details_beyond_a_real_experience_summary(
    memory: ApplicationMemory, question: str
) -> None:
    model = RecordingModel()
    agent = CompanionAgent(memory, load_persona(), model)
    seed_work_story(agent)
    experiences = agent.experiences.list_experiences(KEY)
    shared = [record for record in experiences if record.type is ExperienceType.SHARED]
    assert shared and any(fact.text == DETAIL for record in shared for fact in record.facts)
    assert all("三次地铁" not in record.summary for record in shared)
    agent.chat(request(question, "work-question"))
    messages = model.inputs[-1]
    payload = model_evidence(messages)
    assert payload["relevant_experiences"], "scenario must exercise the real summary path"
    assert any(item.get("content") == DETAIL for item in payload["evidence"])
    assert any(
        record.experience_id == item["experience_id"]
        for record in shared
        for item in payload["relevant_experiences"]
    )
    assert messages[-1].content == question
    assert not any(DETAIL in message.content for message in messages if message.role == "system")


def test_writing_request_receives_the_reason_from_history(memory: ApplicationMemory) -> None:
    model = RecordingModel()
    agent = CompanionAgent(memory, load_persona(), model)
    source_id = seed_work_story(agent)
    assert memory.store.get_turn(source_id, "user").content == DETAIL
    question = "帮我把没去青禾公司的原因写成一句给朋友的解释。"
    response = agent.chat(request(question, "work-question"))
    assert response.turn.reply_to_turn_id
    assert model.inputs[-1][-1].content == question
    evidence = model_evidence(model.inputs[-1])["evidence"]
    assert any(item.get("content") == DETAIL for item in evidence)


@pytest.mark.parametrize(
    "question",
    [
        "我当时没去青禾公司是什么原因？",
        "帮我把没去青禾公司的原因写成一句给朋友的解释。",
    ],
    ids=["recall", "writing"],
)
@pytest.mark.parametrize("restriction", ["forgotten", "do_not_reference", "other_relationship"])
def test_source_linked_experiences_do_not_restore_restricted_detail(
    memory: ApplicationMemory, restriction: str, question: str
) -> None:
    model = RecordingModel()
    agent = CompanionAgent(memory, load_persona(), model)
    source_id = seed_work_story(agent)
    item = request(question, "restricted-question")
    if restriction == "forgotten":
        memory.forget_turn(source_id, "user")
    elif restriction == "do_not_reference":
        memory.record_reference_feedback(
            MemoryReferenceFeedbackInput(
                user_id="user",
                scope=SCOPE.model_copy(update={"conversation_id": None}),
                evidence_kind=ExperienceEvidenceKind.TURN,
                evidence_id=source_id,
                kind=ReferenceFeedbackKind.DO_NOT_REFERENCE,
            )
        )
    else:
        item = item.model_copy(
            update={"scope": SCOPE.model_copy(update={"relationship_id": "another-relationship"})}
        )
    agent.chat(item)
    messages = model.inputs[-1]
    assert not any("三次地铁" in message.content for message in messages)
    assert model_evidence(messages)["relevant_experiences"] == []


@pytest.mark.parametrize(
    ("source", "question"),
    [
        (
            "没去青禾公司是因为通勤要换三次地铁，往返四小时。",
            "替我把没去青禾公司的原因讲给朋友听。",
        ),
        (
            "错过云桥读书会，是因为临时要接妈妈出院。",
            "给我把错过云桥读书会的原因写成一条发给组织者的消息。",
        ),
        (
            "没买松影相机，是因为机身太重，带着走长路不方便。",
            "帮我把没买松影相机的理由解释给朋友听。",
        ),
    ],
    ids=["retell", "message", "explanation"],
)
def test_task_format_does_not_hide_its_historical_subject(
    memory: ApplicationMemory, source: str, question: str
) -> None:
    model = RecordingModel()
    agent = CompanionAgent(memory, load_persona(), model)
    agent.chat(request(source, "source", "archive"))
    agent.chat(request(question, "task"))
    messages = model.inputs[-1]
    assert messages[-1].content == question
    assert any(item.get("content") == source for item in model_evidence(messages)["evidence"])
    assert not any(source in message.content for message in messages if message.role == "system")


def test_shared_writing_format_does_not_supply_unrelated_history(memory: ApplicationMemory) -> None:
    model = RecordingModel()
    agent = CompanionAgent(memory, load_persona(), model)
    unrelated = "帮我写一句给朋友的解释，告诉他展览取消了，我周末要留在家里。"
    agent.chat(request(unrelated, "other-task", "archive"))
    question = "帮我把没去青禾公司的原因写成一句给朋友的解释。"
    agent.chat(request(question, "task"))
    assert not any(unrelated in message.content for message in model.inputs[-1])
    assert not model_evidence(model.inputs[-1])["evidence"]
