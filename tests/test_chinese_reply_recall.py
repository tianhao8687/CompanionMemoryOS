"""Historical assistant speech is retrievable, without becoming a user fact."""

from datetime import UTC, datetime, timedelta

import pytest

from companion_agent.cognition import ApplicationMemory
from companion_memoryos.schemas import (
    AnswerCardinality,
    ConsentState,
    ConversationRole,
    ConversationTurnInput,
    ExperienceEvidenceKind,
    MemoryReferenceFeedbackInput,
    MemoryScope,
    RecallRequest,
    ReferenceFeedbackKind,
    Sensitivity,
)

SCOPE = MemoryScope(companion_id="assistant", relationship_id="r", conversation_id="old")
NOW = datetime(2026, 9, 29, tzinfo=UTC)


@pytest.fixture
def memory(service):
    return ApplicationMemory(service.store, service.config)


def exchange(
    memory, question="我想找本天文学入门书。", answer="天文学可以先读《夜观星空》。", **changes
):
    source = memory.append_turn(
        ConversationTurnInput(
            user_id="u",
            scope=SCOPE,
            actor_id="u",
            role=ConversationRole.USER,
            content=question,
            consent=ConsentState.GRANTED,
            occurred_at=NOW - timedelta(days=2),
        )
    ).turn
    assert source
    fields = dict(
        user_id="u",
        scope=SCOPE,
        actor_id="assistant",
        role=ConversationRole.ASSISTANT,
        content=answer,
        consent=ConsentState.GRANTED,
        occurred_at=NOW - timedelta(days=1),
        reply_to_turn_id=source.id,
    )
    fields.update(changes)
    reply = memory.append_turn(ConversationTurnInput(**fields)).turn
    assert reply
    return source, reply


def recall(memory, query="你曾经给我推荐过什么天文学读物？", **changes):
    fields = dict(
        user_id="u",
        scope=SCOPE.model_copy(update={"conversation_id": "new"}),
        query=query,
        as_of=NOW,
        include_turn_evidence=True,
        include_relationship_turns=True,
        answer_cardinality=AnswerCardinality.OPEN,
        turn_limit=6,
        max_tokens=2500,
        max_characters=12000,
    )
    fields.update(changes)
    return memory.recall(RecallRequest(**fields)).turn_fallback


@pytest.mark.parametrize(
    "query",
    [
        "你曾经给我推荐过什么天文学读物？",
        "你告诉过我哪本天文学入门书？",
        "你上回推荐的天文学书叫什么？",
        "你之前给出的天文学书单是什么？",
        "你曾经和我推荐了哪些天文学书籍？",
        "你曾经与我分享过哪些天文学书？",
        "你教过我怎么入门天文学，还记得那本书吗？",
    ],
)
def test_chinese_past_reply_is_first_and_keeps_role(memory, query):
    _, reply = exchange(memory)
    items = recall(memory, query, turn_limit=1)
    assert len(items) == 1 and items[0].turn.id == reply.id
    assert items[0].turn.role is ConversationRole.ASSISTANT
    assert "non_user_turn_not_user_fact" in items[0].reasons


def test_reply_can_match_when_source_question_is_vague(memory):
    _, reply = exchange(memory, "那你觉得呢？")
    assert reply.id in {item.turn.id for item in recall(memory)}


def test_more_than_two_past_answers_are_available(memory):
    replies = [
        exchange(memory, f"第 {i} 本天文学入门书是什么？", f"天文学书单第 {i} 本。")[1].id
        for i in range(3)
    ]
    assert set(replies) <= {item.turn.id for item in recall(memory)}


@pytest.mark.parametrize(
    "query",
    [
        "我喜欢什么天文学读物？",
        "给我推荐一本天文学书。",
        "我以前向你推荐过哪本天文学书？",
        "我曾经和你分享过什么天文学读物？",
        "我之前跟你提到的天文学入门书叫什么？",
        "你记得我推荐过的天文学书吗？",
        "我曾经教过你怎么找天文学读物，对吗？",
        "我以前和你推荐过哪本天文学书？",
    ],
)
def test_normal_user_fact_or_new_request_does_not_promote_assistant(memory, query):
    _, reply = exchange(memory)
    assert reply.id not in {item.turn.id for item in recall(memory, query)}


@pytest.mark.parametrize("blocked", ["source", "reply"])
@pytest.mark.parametrize("restriction", ["forget", "feedback", "exclude"])
def test_recalled_reply_respects_source_restrictions(memory, blocked, restriction):
    source, reply = exchange(memory)
    target = source if blocked == "source" else reply
    changes = {}
    if restriction == "forget":
        memory.forget_turn(target.id, "u")
    elif restriction == "feedback":
        memory.record_reference_feedback(
            MemoryReferenceFeedbackInput(
                user_id="u",
                scope=SCOPE,
                evidence_kind=ExperienceEvidenceKind.TURN,
                evidence_id=target.id,
                kind=ReferenceFeedbackKind.DO_NOT_REFERENCE,
                recorded_at=NOW,
            )
        )
    else:
        changes["exclude_turn_ids"] = [target.id]
    assert reply.id not in {item.turn.id for item in recall(memory, **changes)}


@pytest.mark.parametrize("blocked", ["source", "reply"])
def test_future_reference_feedback_applies_at_recorded_time(memory, blocked):
    source, reply = exchange(memory)
    target = source if blocked == "source" else reply
    recorded_at = NOW + timedelta(hours=1)
    memory.record_reference_feedback(
        MemoryReferenceFeedbackInput(
            user_id="u",
            scope=SCOPE,
            evidence_kind=ExperienceEvidenceKind.TURN,
            evidence_id=target.id,
            kind=ReferenceFeedbackKind.DO_NOT_REFERENCE,
            recorded_at=recorded_at,
        )
    )
    assert reply.id in {item.turn.id for item in recall(memory)}
    assert reply.id not in {item.turn.id for item in recall(memory, as_of=recorded_at)}


@pytest.mark.parametrize(
    "changes",
    [
        {"include_relationship_turns": False},
        {"scope": SCOPE.model_copy(update={"group_id": "elsewhere"})},
        {"scope": SCOPE.model_copy(update={"relationship_id": "other"})},
        {"event_before": NOW - timedelta(days=1, hours=1)},
        {"as_of": NOW - timedelta(days=1, hours=1)},
    ],
)
def test_reply_stays_within_request_filters(memory, changes):
    _, reply = exchange(memory)
    assert reply.id not in {item.turn.id for item in recall(memory, **changes)}


def test_sensitive_reply_is_not_added_from_public_request(memory):
    _, reply = exchange(memory, sensitivity=Sensitivity.SENSITIVE)
    assert reply.id not in {item.turn.id for item in recall(memory)}


def test_old_recommendation_reaches_real_chat_context_with_attribution(tmp_path):
    from companion_agent.cognition import CognitionSettings
    from companion_agent.llm import ModelResponse
    from tests.test_companion_functional import chat, host_for
    from tests.test_romance_app import RecordingLLM

    class BookModel(RecordingLLM):
        def generate(self, messages):
            self.inputs.append(messages)
            return ModelResponse(text="天文学可以先读《夜观星空》。", model="fixture")

    model = BookModel()
    host = host_for(tmp_path, model, cognition=CognitionSettings(embedding_backend="local"))
    result = chat(host, "我想找本天文学入门书。", "ask")
    chat(host, "你之前给我推荐过哪本天文学书？", "recall", host.new_conversation()["id"])
    context = "\n".join(message.content for message in model.inputs[-1][:-1])
    assert result["assistant"]["id"] in context
    assert "夜观星空" in context
    assert '"role": "assistant"' in context or '"role":"assistant"' in context
