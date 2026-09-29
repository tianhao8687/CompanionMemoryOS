"""Chat-first orchestration at the real context boundary, without model quality claims."""

from __future__ import annotations

import pytest

from companion_agent import CompanionAgent, RelationshipStage, compile_persona_context, load_persona
from companion_agent.cognition import ApplicationMemory, CognitionSettings
from companion_agent.context import compose_context
from companion_agent.context.budget import prune_background_evidence, trim_oldest_exchange
from companion_agent.deepseek import DeepSeekConfig
from companion_agent.experience.models import CompiledExperienceContext
from companion_memoryos.schemas import (
    AnswerCardinality,
    ConsentState,
    ConversationRole,
    ConversationTurnInput,
    ConversationTurnRecord,
    ExperienceEvidenceKind,
    ExperienceEvidenceRef,
    MemoryInput,
    MemoryKind,
    MemoryReferenceMode,
    MemoryScope,
    MemoryStatus,
    MemoryUseDecision,
    MemoryUsePlan,
    ProcessTurnRequest,
    RecallIntent,
    RecallRequest,
    ResponseGoal,
    ResponsePlanRequest,
)
from companion_memoryos.service import CompanionMemoryService

SCOPE = MemoryScope(companion_id="xiaohe", relationship_id="chat-first", conversation_id="chat")


def request(text: str, key: str = "current", **extra: object) -> ProcessTurnRequest:
    return ProcessTurnRequest.model_validate(
        {
            "user_id": "user",
            "scope": SCOPE,
            "content": text,
            "idempotency_key": key,
            "consent": "granted",
            "model_consent": "granted",
            **extra,
        }
    )


@pytest.fixture
def memory(service: CompanionMemoryService) -> ApplicationMemory:
    result = ApplicationMemory(service.store, service.config)
    result.configure(
        CognitionSettings(embedding_backend="off"), offline=True, model=DeepSeekConfig(), key=None
    )
    return result


def append(
    memory: CompanionMemoryService,
    text: str,
    role: ConversationRole = ConversationRole.USER,
    reply_to: str | None = None,
) -> ConversationTurnRecord:
    turn = memory.append_turn(
        ConversationTurnInput(
            user_id="user",
            scope=SCOPE,
            actor_id="user" if role is ConversationRole.USER else "xiaohe",
            content=text,
            role=role,
            consent=ConsentState.GRANTED,
            reply_to_turn_id=reply_to,
        )
    ).turn
    assert turn
    return turn


def test_one_recall_after_same_turn_correction(
    memory: ApplicationMemory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    memory.process_turn(request("我喜欢喝咖啡", "first"))
    calls: list[RecallRequest] = []
    original = memory.recall

    def recall(item: RecallRequest):
        calls.append(item)
        active = memory.list_memories("user", {MemoryStatus.ACTIVE})
        assert any("现在不喜欢咖啡" in record.content for record in active)
        assert not any(record.content == "我喜欢喝咖啡" for record in active)
        return original(item)

    monkeypatch.setattr(memory, "recall", recall)
    result = memory.process_turn(request("不对，我现在不喜欢咖啡了", "correction"))
    assert len(calls) == 1
    assert result.response_context
    assert any(line.startswith("application_memory:") for line in result.response_context.guidance)


@pytest.mark.parametrize("caller_intent", [False, True])
def test_current_understanding_precedes_recall(
    memory: ApplicationMemory,
    monkeypatch: pytest.MonkeyPatch,
    caller_intent: bool,
) -> None:
    agent = CompanionAgent(memory, load_persona())
    assert agent.current_states
    events: list[str] = []
    seen: list[RecallIntent] = []
    original_process = agent.current_states.process
    original_recall = memory.recall

    def process(*args, **kwargs):
        events.append("understand")
        return original_process(*args, **kwargs)

    def recall(item: RecallRequest):
        events.append("recall")
        seen.append(item.intent)
        return original_recall(item)

    monkeypatch.setattr(agent.current_states, "process", process)
    monkeypatch.setattr(memory, "recall", recall)
    traces = {}
    monkeypatch.setattr(
        "companion_agent.runtime.record", lambda name, value: traces.update({name: value})
    )
    prepared = agent.prepare(
        request(
            "帮我写一条发给同事的感谢消息。",
            recall_request=RecallRequest(user_id="user", scope=SCOPE, intent=RecallIntent.CHECK_IN)
            if caller_intent
            else None,
        )
    )
    assert events == ["understand", "recall"]
    assert prepared.context.persona.response_goal is ResponseGoal.DIRECT_ANSWER
    assert seen == [RecallIntent.CHECK_IN if caller_intent else RecallIntent.GENERAL]
    assert traces["recall_focus"]["intent"] == seen[0].value
    assert traces["recall_focus"]["intent_source"] == (
        "caller" if caller_intent else "current_goal"
    )
    assert prepared.context.messages[-1].content == "帮我写一条发给同事的感谢消息。"


@pytest.mark.parametrize("disabled", [False, True])
def test_deferred_recall_preserves_attention_and_opt_out(
    memory: ApplicationMemory,
    monkeypatch: pytest.MonkeyPatch,
    disabled: bool,
) -> None:
    item = request("先听我说" if not disabled else "今天想聊散步", enable_recall=not disabled)
    result = memory.process_turn(item, defer_recall=True)

    def forbidden(*args, **kwargs):
        raise AssertionError("recall must remain disabled")

    monkeypatch.setattr(memory, "recall", forbidden)
    assert memory.recall_processed_turn(item, result).response_context is None


@pytest.mark.parametrize("invalidate", ["new_turn", "forget", "purge"])
def test_deferred_completion_rechecks_source(
    memory: ApplicationMemory,
    invalidate: str,
) -> None:
    item = request("聊聊明天的安排。")
    result = memory.process_turn(item, defer_recall=True)
    assert result.storage.turn
    if invalidate == "new_turn":
        memory.process_turn(request("先换个话题。", "newer"), defer_recall=True)
    elif invalidate == "forget":
        memory.forget_turn(result.storage.turn.id, "user")
    else:
        memory.purge_turn(result.storage.turn.id, "user")
    finished = memory.recall_processed_turn(item, result)
    assert finished.response_context is None
    assert finished.response_stale or finished.storage.turn is None


def test_deferred_result_cannot_be_reused_for_other_owner(memory: ApplicationMemory) -> None:
    item = request("今天聊聊散步。")
    result = memory.process_turn(item, defer_recall=True)
    other = item.model_copy(update={"user_id": "someone-else"})
    with pytest.raises(ValueError, match="does not match"):
        memory.recall_processed_turn(other, result)


def test_source_deleted_during_recall_cannot_be_returned(
    memory: ApplicationMemory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = request("今天聊聊散步。")
    result = memory.process_turn(item, defer_recall=True)
    assert result.storage.turn
    source_id = result.storage.turn.id
    original = memory.recall

    def recall(query: RecallRequest):
        context = original(query)
        memory.forget_turn(source_id, "user")
        return context

    monkeypatch.setattr(memory, "recall", recall)
    finished = memory.recall_processed_turn(item, result)
    assert finished.response_context is None
    assert finished.storage.turn is None


def test_preview_is_not_persisted_and_commit_rechecks_newer_turn(
    memory: ApplicationMemory,
) -> None:
    result = memory.process_turn(request("今天聊聊散步。"), defer_recall=True)
    assert result.storage.turn
    preview = memory.preview_response(
        ResponsePlanRequest(
            user_id="user",
            scope=SCOPE,
            trigger_turn_id=result.storage.turn.id,
            goal=ResponseGoal.DIRECT_ANSWER,
        )
    )
    assert memory.store.list_response_plans("user") == []
    memory.process_turn(request("现在换个话题。", "newer"), defer_recall=True)
    with pytest.raises(ValueError, match="newer user turn"):
        memory.store.create_response_plan(preview)


def recalled(memory: CompanionMemoryService, text: str):
    return memory.recall(
        RecallRequest(
            user_id="user",
            scope=SCOPE,
            query=text,
            include_turn_evidence=True,
            answer_cardinality=AnswerCardinality.OPEN,
            turn_limit=6,
            max_tokens=4000,
        )
    )


def use_plan(identifier: str, mode: MemoryReferenceMode) -> MemoryUsePlan:
    return MemoryUsePlan(
        decisions=[
            MemoryUseDecision(
                evidence=ExperienceEvidenceRef(kind=ExperienceEvidenceKind.TURN, id=identifier),
                mode=mode,
            )
        ]
    )


def test_duplicate_history_keeps_one_body_and_attribution(memory: ApplicationMemory) -> None:
    source = append(memory, "我刚才在河堤散步，看见新开的书店。")
    context = recalled(memory, "河堤散步书店")
    assert any(item.turn.id == source.id for item in context.turn_fallback)
    composed = compose_context(
        persona=compile_persona_context(
            load_persona(), ResponseGoal.REFLECT, RelationshipStage.NEW
        ),
        user_id="user",
        scope=SCOPE,
        current_user_turn="那家店怎么样？",
        memory_context=context,
        memory_use_plan=use_plan(source.id, MemoryReferenceMode.SILENT_INFLUENCE),
        recent_conversation=[source],
    )
    assert composed.text.count(source.content) == 1
    assert composed.deduplicated_turn_ids == [source.id]
    assert source.content not in composed.messages[0].content
    assert "content_in_recent_conversation" in composed.messages[1].content
    assert composed.messages[-2].source_turn_id == source.id


def test_composer_preserves_exact_evidence_with_supplied_summary(memory: ApplicationMemory) -> None:
    source = append(memory, "我没去那家公司，是因为工作地点临时改到了郊区。")
    context = recalled(memory, "公司工作地点")
    summary = CompiledExperienceContext(
        user_id="user",
        companion_id="xiaohe",
        relationship_id=SCOPE.relationship_id,
        text='[{"summary":"聊过求职的经历"}]',
        estimated_tokens=20,
        covered_evidence_ids=[f"turn:{source.id}"],
    )
    composed = compose_context(
        persona=compile_persona_context(
            load_persona(), ResponseGoal.REFLECT, RelationshipStage.NEW
        ),
        user_id="user",
        scope=SCOPE,
        current_user_turn="我后来为什么没去那家公司？",
        memory_context=context,
        experience_context=summary,
        memory_use_plan=use_plan(source.id, MemoryReferenceMode.EXPLICIT_RECALL),
    )
    assert source.content in composed.text


def test_different_content_with_same_id_does_not_hide_evidence(memory: ApplicationMemory) -> None:
    source = append(memory, "在河堤散步时看见了新开的书店。")
    context = recalled(memory, "河堤散步书店")
    composed = compose_context(
        persona=compile_persona_context(
            load_persona(), ResponseGoal.REFLECT, RelationshipStage.NEW
        ),
        user_id="user",
        scope=SCOPE,
        current_user_turn="聊聊书店。",
        memory_context=context,
        memory_use_plan=use_plan(source.id, MemoryReferenceMode.SILENT_INFLUENCE),
        recent_conversation=[source.model_copy(update={"content": "这是不同的内容。"})],
    )
    assert composed.deduplicated_turn_ids == []
    assert source.content in composed.text


def test_background_pruning_respects_sources_and_explicit_recall(memory: ApplicationMemory) -> None:
    source = append(memory, "上周在河堤散步，看见新开的书店。")
    context = recalled(memory, "河堤散步书店")
    plan = use_plan(source.id, MemoryReferenceMode.EXPLICIT_RECALL)
    assert prune_background_evidence(context, plan, set(), memory.token_counter) is None
    plan = use_plan(source.id, MemoryReferenceMode.SILENT_INFLUENCE)
    assert prune_background_evidence(context, plan, {source.id}, memory.token_counter) is None
    trimmed = prune_background_evidence(context, plan, set(), memory.token_counter)
    assert trimmed
    selected, identifier = trimmed
    assert identifier == f"turn:{source.id}"
    assert source.content not in selected.prompt_text
    assert source.content in context.prompt_text
    assert selected.budget_omitted_count == context.budget_omitted_count + 1
    assert selected.rendered_tokens == memory.token_counter.count(selected.prompt_text)
    assert memory.store.get_turn(source.id, "user").content == source.content


def test_dialogue_is_trimmed_in_complete_exchanges(memory: ApplicationMemory) -> None:
    first = append(memory, "先聊聊散步。")
    reply = append(memory, "你一般走哪条路？", ConversationRole.ASSISTANT, first.id)
    latest = append(memory, "河堤那条，有家新书店。")
    last_reply = append(memory, "那家店有些什么？", ConversationRole.ASSISTANT, latest.id)
    recent = [first, reply, latest, last_reply]
    assert trim_oldest_exchange(recent, {first.id}) == []
    assert trim_oldest_exchange(recent, set()) == [first.id, reply.id]
    assert recent == [latest, last_reply]
    assert trim_oldest_exchange(recent, set()) == []


def test_boundary_cannot_be_pruned_as_background(memory: ApplicationMemory) -> None:
    boundary = memory.remember(
        MemoryInput(
            user_id="user",
            scope=SCOPE,
            kind=MemoryKind.BOUNDARY,
            title="称呼边界",
            content="不要叫我老板。",
            consent=ConsentState.GRANTED,
            explicit_user_request=True,
        )
    ).memory
    assert boundary
    context = recalled(memory, "聊聊今天的事")
    assert any(item.pinned for items in context.sections.values() for item in items)
    plan = MemoryUsePlan(
        decisions=[
            MemoryUseDecision(
                evidence=ExperienceEvidenceRef(kind=ExperienceEvidenceKind.MEMORY, id=boundary.id),
                mode=MemoryReferenceMode.SILENT_INFLUENCE,
            )
        ]
    )
    assert prune_background_evidence(context, plan, set(), memory.token_counter) is None


def test_too_small_budget_does_not_persist_partial_plan(memory: ApplicationMemory) -> None:
    agent = CompanionAgent(memory, load_persona(), max_context_tokens=1)
    with pytest.raises(ValueError, match="main context exceeds budget"):
        agent.prepare(request("我还想把这件事说完。"))
    assert memory.store.list_response_plans("user") == []
