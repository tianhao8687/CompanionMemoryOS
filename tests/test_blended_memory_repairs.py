"""Failures found in the blended live conversation, with scope/deletion controls."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from companion_agent.app import LOCAL_USER
from companion_agent.cognition import CognitionSettings
from companion_agent.communication import communication_preferences
from companion_agent.memory_language import forget_target
from companion_memoryos.interpreter import INTERPRETER_SYSTEM_PROMPT, parse_interpretation
from companion_memoryos.schemas import (
    AnswerCardinality,
    AnswerSemantics,
    ConsentState,
    ConversationRole,
    ConversationTurnInput,
    EpisodeAttachRequest,
    EpisodeInput,
    InterpreterOutput,
    MemoryInput,
    MemoryKind,
    MemoryScope,
    MemoryStatus,
    OpenLoopInput,
    OpenLoopKind,
    OpenLoopStatus,
    RecallRequest,
    RetrievalOutcome,
    TurnDeletionState,
    TurnInterpretation,
)
from companion_memoryos.service import CompanionMemoryService
from tests.test_automatic_memory import visible_context
from tests.test_companion_functional import chat, host_for
from tests.test_romance_app import RecordingLLM


def test_invalid_proposals_do_not_discard_independent_grounded_fact() -> None:
    raw = {
        "memory_candidates": [
            {"kind": "fact", "content": "invalid"},
            {
                "kind": "shared_moment",
                "title": "水杯",
                "content": "我的杯子是紫色。",
                "confidence": 0.98,
            },
        ],
        "entities": [{"ref": "f", "name": "小岚", "confidence": 0.9}],
        "state_claims": [{"kind": "current_state", "content": "invalid"}],
        "open_loop_candidates": [{"kind": "event", "summary": "invalid"}],
    }
    output, issues = parse_interpretation(json.dumps(raw), 20)
    assert len(output.memory_candidates) == 1
    assert output.memory_candidates[0].content == "我的杯子是紫色。"
    assert len(issues) == 4
    assert not output.entities and not output.state_claims and not output.open_loop_candidates
    assert (
        "self_report" in INTERPRETER_SYSTEM_PROMPT
        and "user_commitment" in INTERPRETER_SYSTEM_PROMPT
    )


def test_partial_parse_remaps_valid_spans_and_drops_invalid_dependencies() -> None:
    valid = {"kind": "shared_moment", "title": "物品", "content": "原句", "confidence": 0.99}
    raw = {
        "speech_spans": [
            {"start_offset": 0, "end_offset": 999, "speech_act": "assertion"},
            {"start_offset": 0, "end_offset": 2, "speech_act": "assertion"},
        ],
        "memory_candidates": [
            {**valid, "evidence_span_indices": [0]},
            {**valid, "evidence_span_indices": [1]},
            {**valid, "evidence_span_indices": [8]},
        ],
    }
    output, issues = parse_interpretation(json.dumps(raw), 2)
    assert len(issues) == 3
    assert len(output.memory_candidates) == 1
    assert output.memory_candidates[0].evidence_span_indices == [0]
    assert output.memory_candidates[0].confidence == 0.99


@pytest.mark.parametrize(
    "raw", [{"delete": "all"}, {"topics": "not a list"}, {"topics": ["x"] * 65}]
)
def test_partial_parse_never_relaxes_envelope_or_collection_bounds(raw: dict) -> None:
    with pytest.raises(ValueError):
        parse_interpretation(json.dumps(raw), 10)


def test_complementary_facts_do_not_become_ambiguous_from_equal_scores(
    service: CompanionMemoryService,
) -> None:
    for predicate, content in [("gift_budget", "礼物预算八十元"), ("drink_price", "奶茶十八元")]:
        service.remember(
            MemoryInput(
                user_id="u",
                kind=MemoryKind.SHARED_MOMENT,
                title="礼物",
                content=content,
                subject_actor_id="u",
                predicate=predicate,
                consent=ConsentState.GRANTED,
                explicit_user_request=True,
                embedding=[1, 0],
                embedding_space="test",
            )
        )
    context = service.recall(
        RecallRequest(
            user_id="u",
            query="给朋友准备礼物",
            query_embedding=[1, 0],
            embedding_space="test",
            answer_cardinality=AnswerCardinality.OPEN,
        )
    )
    assert context.retrieval_outcome is RetrievalOutcome.MATCH
    assert len([item for section in context.sections.values() for item in section]) == 2


def test_open_collection_keeps_other_evidence_when_an_unrelated_slot_has_two_assertions(
    service: CompanionMemoryService,
) -> None:
    for index, content in enumerate(["想安静", "想靠着聊"]):
        service.remember(
            MemoryInput(
                user_id="u",
                kind=MemoryKind.PREFERENCE,
                title="相处心情",
                content=content,
                predicate="company_preference",
                subject_actor_id="u",
                stable_key=f"independent-{index}",
                consent=ConsentState.GRANTED,
                explicit_user_request=True,
                embedding=[1, 0],
                embedding_space="test",
            )
        )
    service.remember(
        MemoryInput(
            user_id="u",
            kind=MemoryKind.SHARED_MOMENT,
            title="谢礼",
            content="拼图五十八元，奶茶十六元",
            consent=ConsentState.GRANTED,
            explicit_user_request=True,
            embedding=[1, 0],
            embedding_space="test",
        )
    )
    context = service.recall(
        RecallRequest(
            user_id="u",
            query="礼物怎么搭配",
            query_embedding=[1, 0],
            embedding_space="test",
            answer_cardinality=AnswerCardinality.OPEN,
        )
    )
    assert context.retrieval_outcome is RetrievalOutcome.MATCH
    # Selecting a single explicit state retains the core conflict gate.
    state = service.recall(
        RecallRequest(
            user_id="u",
            query="相处偏好",
            state_predicate="company_preference",
            state_subject_actor_id="u",
            answer_semantics=AnswerSemantics.STATE_AT_VALID_TIME,
        )
    )
    assert state.retrieval_outcome is RetrievalOutcome.AMBIGUOUS


def test_forgetting_a_reply_source_does_not_reopen_an_answered_historical_request(
    tmp_path: Path,
) -> None:
    model = RecordingLLM()
    host = host_for(tmp_path, model)
    source = chat(host, "备用钥匙在门边的蓝罐里。", "location")
    prior_task = "帮我算一下三十加十五是多少。"
    calculated = chat(host, prior_task, "calculation")
    reply = host.memory.store.get_turn(calculated["assistant"]["id"], LOCAL_USER)
    assert source["user"]["id"] in reply.metadata["context_turn_ids"]
    host.memory.forget_turn(source["user"]["id"], LOCAL_USER)
    current = "换个话题，给窗边的小盆栽起个名字。"
    chat(host, current, "next-topic")
    messages = model.inputs[-1]
    assert messages[-1].content == current
    assert prior_task not in [message.content for message in messages[2:]]
    assert prior_task in messages[1].content
    attribution = json.loads(messages[1].content.split("[CONVERSATION ATTRIBUTION]\n")[1])
    historical = next(
        item for item in attribution["recent_turns"] if item.get("content") == prior_task
    )
    assert historical["reply_status"] == "prior_response_omitted"
    assert "蓝罐" not in "\n".join(message.content for message in messages)


def test_semantic_raw_evidence_survives_new_conversation_and_restart_without_extraction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Deliberately no lexical overlap: this check exercises actual vector lookup
    # and final prompt selection, not the quality of a substitute embedding model.
    source = "我买了个赭红保温桶，上面画着白鹭。"
    query = "替它设计同款包装吧。"
    monkeypatch.setattr(
        "companion_agent.cognition.Embeddings.encode", lambda self, text: [1.0, 0.0]
    )
    model = RecordingLLM()
    host = host_for(tmp_path, model)
    sent = chat(host, source)
    assert not host.memory.list_memories(LOCAL_USER)
    restarted = host_for(tmp_path, model)
    chat(restarted, query, "recall", restarted.new_conversation()["id"])
    assert source in model.inputs[-1][1].content
    assert sent["user"]["id"] in model.inputs[-1][1].content
    assert '"occurred_at"' in model.inputs[-1][1].content
    with restarted.memory.store.database.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM turn_embeddings").fetchone()[0] == 2


def test_relationship_turn_recall_never_crosses_group_owner_or_relationship(
    service: CompanionMemoryService,
) -> None:
    scope = MemoryScope(companion_id="c", relationship_id="r", conversation_id="old")
    for index, (owner, test_scope) in enumerate(
        [
            ("u", scope),
            ("v", scope),
            ("u", scope.model_copy(update={"relationship_id": "other"})),
            ("u", scope.model_copy(update={"group_id": "group"})),
        ]
    ):
        service.append_turn(
            ConversationTurnInput(
                user_id=owner,
                actor_id=owner,
                role=ConversationRole.USER,
                scope=test_scope,
                content=f"预算八十来源{index}",
                consent=ConsentState.GRANTED,
                idempotency_key=str(index),
                occurred_at=datetime.now(UTC),
                embedding=[1, 0],
                embedding_space="test",
            )
        )
    result = service.recall(
        RecallRequest(
            user_id="u",
            scope=scope.model_copy(update={"conversation_id": "new"}),
            query="预算",
            query_embedding=[1, 0],
            embedding_space="test",
            include_relationship_turns=True,
            include_turn_evidence=True,
            answer_cardinality=AnswerCardinality.OPEN,
        )
    )
    assert [item.turn.content for item in result.turn_fallback] == ["预算八十来源0"]
    with pytest.raises(ValueError, match="companion and relationship"):
        RecallRequest(user_id="u", include_relationship_turns=True)


def test_natural_location_forgetting_deletes_raw_sources_even_without_memory_card(
    tmp_path: Path,
) -> None:
    model = RecordingLLM()
    host = host_for(tmp_path, model)
    sent = chat(host, "备用门卡放在玄关藤篮最下层。")
    assert not host.memory.list_memories(LOCAL_USER)
    request = (
        "备用门卡已经挪了地方，之前跟你说的那个位置请忘掉，也别再用旧位置提醒我。新位置先不告诉你。"
    )
    assert forget_target(request) == "@location:备用门卡"
    chat(host, request, "forget", host.new_conversation()["id"])
    assert (
        host.memory.store.get_turn(sent["user"]["id"], LOCAL_USER).deletion_state
        is TurnDeletionState.FORGOTTEN
    )
    assert (
        host.memory.store.get_turn(sent["assistant"]["id"], LOCAL_USER).deletion_state
        is TurnDeletionState.FORGOTTEN
    )
    restarted = host_for(tmp_path, model)
    chat(restarted, "备用门卡放哪里了？", "recall", restarted.new_conversation()["id"])
    assert "藤篮" not in visible_context(model)
    with restarted.memory.store.database.connection() as db:
        assert (
            db.execute(
                "SELECT COUNT(*) FROM turn_embeddings WHERE turn_id=?", (sent["user"]["id"],)
            ).fetchone()[0]
            == 0
        )


@pytest.mark.parametrize(
    "text",
    [
        "如果备用门卡挪了地方，之前跟你说的那个位置请忘掉。",
        "她说：备用门卡挪了地方，之前跟你说的那个位置请忘掉。",
        "备用门卡已经挪了地方，之前跟你说的那个位置不要忘掉。",
    ],
)
def test_forget_parser_preserves_conditions_quotes_and_negation(text: str) -> None:
    assert forget_target(text) is None


def test_explicit_cancel_updates_old_relationship_thread_across_conversations(
    tmp_path: Path,
) -> None:
    model = RecordingLLM()
    host = host_for(tmp_path, model, cognition=CognitionSettings(embedding_backend="off"))
    sent = chat(host, "周六上午十点有陶艺课。")
    scope = host.scope(host.conversations()[0]["id"])
    loop = host.memory.create_open_loop(
        OpenLoopInput(
            user_id=LOCAL_USER,
            scope=scope,
            kind=OpenLoopKind.EVENT_OUTCOME,
            summary="周六上午十点的陶艺课",
            topic_keys=["陶艺课"],
            source_turn_id=sent["user"]["id"],
            consent=ConsentState.GRANTED,
        )
    ).open_loop
    assert loop
    conversation = host.new_conversation()["id"]
    chat(host, "如果陶艺课取消了我们再出门。", "conditional", conversation)
    assert host.memory.list_open_loops(LOCAL_USER)[0].status is OpenLoopStatus.OPEN
    chat(host, "工坊通知陶艺课取消了，散步照旧。", "cancel", conversation)
    updated = host.memory.list_open_loops(LOCAL_USER)[0]
    assert updated.status is OpenLoopStatus.CANCELLED
    assert "取消" in (updated.resolution_summary or "")
    assert updated.revision == 2


def test_brief_pause_is_not_a_durable_question_preference() -> None:
    settings = communication_preferences("我想安静几分钟，别追问。")
    assert len(settings) == 1 and settings[0].lifetime == "turn"
    assert communication_preferences("以后少追问。")[0].lifetime == "durable"


def test_forgetting_receipt_filters_a_new_model_thread_before_generating(tmp_path: Path) -> None:
    model = RecordingLLM()
    host = host_for(tmp_path, model)
    chat(host, "备用钥匙放在门边的蓝罐里。", "source")

    class Interpreter:
        def interpret(self, context):
            return InterpreterOutput(
                model_fingerprint="fixture",
                interpretation=TurnInterpretation.model_validate(
                    {
                        "open_loop_candidates": [
                            {
                                "kind": "event_outcome",
                                "summary": "备用钥匙新位置尚未告知，未来可能告知",
                                "topic_keys": ["备用钥匙", "新位置"],
                            }
                        ]
                    }
                ),
            )

    host.memory.turn_interpreter = Interpreter()
    result = chat(
        host,
        "备用钥匙已经换了地方，之前跟你说的那个位置请忘掉。新位置我先不告诉你。",
        "forget-with-model-thread",
    )
    assert result["assistant"]["content"]
    background = model.inputs[-1][1].content
    assert "未来可能告知" not in background
    assert "蓝罐" not in background


def test_low_relevance_raw_hit_does_not_invalidate_independent_preference_source(
    tmp_path: Path,
) -> None:
    host = host_for(tmp_path)
    messages = [
        "今天工作压力很大，先听我讲完。",
        "我不喜欢被分析，你能像朋友一样聊天吗？",
        "我今天拿到奖金啦，现在特别开心！",
        "以后不要总是反问我。",
        "刚吃了个烤红薯，特别甜。",
        "不要主动给建议。",
    ]
    for index, content in enumerate(messages):
        assert chat(host, content, str(index))["assistant"]["content"]


def test_temporary_model_copy_cannot_become_lasting_support_strategy(tmp_path: Path) -> None:
    source = "我现在想安静几分钟，别追问，坐在旁边就挺好。"

    class Interpreter:
        def interpret(self, context):
            return InterpreterOutput(
                model_fingerprint="fixture",
                interpretation=TurnInterpretation.model_validate(
                    {
                        "memory_candidates": [
                            {
                                "kind": "support_strategy",
                                "title": "短暂停顿",
                                "content": source,
                                "confidence": 0.99,
                            }
                        ]
                    }
                ),
            )

    host = host_for(tmp_path, RecordingLLM())
    host.memory.turn_interpreter = Interpreter()
    chat(host, source)
    active = host.memory.list_memories(LOCAL_USER, {MemoryStatus.ACTIVE})
    assert len(active) == 1 and active[0].content == "别追问"
    assert active[0].scope.conversation_id is not None
    assert active[0].valid_time_end is not None
    assert any(
        r.content == source for r in host.memory.list_memories(LOCAL_USER, {MemoryStatus.CANDIDATE})
    )


def test_overview_retrieves_dated_plans_among_stronger_mood_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = RecordingLLM()
    # Strong moods and weaker but usable event vectors reproduce the live ranking.
    monkeypatch.setattr(
        "companion_agent.cognition.Embeddings.encode",
        lambda self, text: [0.4, 0.9] if "周日" in text else [1.0, 0.0],
    )
    host = host_for(tmp_path, model)
    source = "手工课改到周日下午两点了，周六下午约小岚逛书店。"
    chat(host, source)
    for index in range(8):
        chat(host, f"最近想到第{index}件有趣的事，想靠着你发会儿呆。", str(index))
    chat(
        host, "周末不想赶，帮我把已经说好的几件事顺顺。", "overview", host.new_conversation()["id"]
    )
    assert source in model.inputs[-1][1].content


def test_event_date_does_not_filter_out_earlier_announcement(
    service: CompanionMemoryService,
) -> None:
    now = datetime.now(UTC)
    scope = MemoryScope(companion_id="c", relationship_id="r", conversation_id="old")
    source = service.append_turn(
        ConversationTurnInput(
            user_id="u",
            actor_id="u",
            role=ConversationRole.USER,
            scope=scope,
            content="明天上午有木工课",
            occurred_at=now - timedelta(minutes=1),
            consent=ConsentState.GRANTED,
            idempotency_key="plan",
            embedding=[1, 0],
            embedding_space="test",
        )
    ).turn
    assert source
    request = RecallRequest(
        user_id="u",
        scope=scope.model_copy(update={"conversation_id": "new"}),
        query="明天有什么安排",
        as_of=now,
        include_turn_evidence=True,
        include_relationship_turns=True,
        query_embedding=[1, 0],
        embedding_space="test",
        answer_cardinality=AnswerCardinality.OPEN,
    )
    result = service.recall(request)
    assert source.id in [item.turn.id for item in result.turn_fallback]
    explicitly_bounded = service.recall(request.model_copy(update={"event_after": now}))
    assert not explicitly_bounded.turn_fallback


def test_blended_evidence_keeps_updates_inside_the_same_episode(
    service: CompanionMemoryService,
) -> None:
    scope = MemoryScope(companion_id="c", relationship_id="r", conversation_id="old")
    episode = service.create_episode(EpisodeInput(user_id="u", scope=scope, title="周末安排"))
    source_ids = set()
    for content in ["周六上午有木工课。", "木工课改到周日下午两点，周六书店照旧。"]:
        turn = service.append_turn(
            ConversationTurnInput(
                user_id="u",
                scope=scope,
                actor_id="u",
                role=ConversationRole.USER,
                content=content,
                consent=ConsentState.GRANTED,
                embedding=[1, 0],
                embedding_space="test",
            )
        ).turn
        assert turn
        source_ids.add(turn.id)
        service.attach_episode_turn(
            episode.id, EpisodeAttachRequest(user_id="u", scope=scope, turn_id=turn.id)
        )
    request = RecallRequest(
        user_id="u",
        scope=scope,
        query="帮我顺一下安排",
        query_embedding=[1, 0],
        embedding_space="test",
        include_turn_evidence=True,
        answer_cardinality=AnswerCardinality.OPEN,
    )
    assert {item.turn.id for item in service.recall(request).turn_fallback} == source_ids
    # The default event-recall API continues to diversify episodes.
    ordinary = service.recall(request.model_copy(update={"include_turn_evidence": False}))
    assert len(ordinary.turn_fallback) == 1
