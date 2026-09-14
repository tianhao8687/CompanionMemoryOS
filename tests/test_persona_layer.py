"""Functional checks only: no live model or persona quality evaluation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from companion_agent import (
    CompanionAgent,
    RelationshipStage,
    compile_persona_context,
    compose_context,
    load_persona,
)
from companion_agent.character_memory import CharacterMemoryStore
from companion_agent.context import ChatMessage
from companion_agent.llm import MainLLMError, ModelResponse, OpenAICompatibleMainLLM
from companion_agent.persona.loader import loads_persona
from companion_agent.persona.models import CharacterMemorySeed, PersonaDefinition
from companion_agent.persona.tokens import PersonaBudgetError
from companion_memoryos.config import InterpreterConfig
from companion_memoryos.schemas import (
    ConsentState,
    ConversationRole,
    ConversationTurnInput,
    ExperienceEvidenceKind,
    ExperienceEvidenceRef,
    MemoryInput,
    MemoryKind,
    MemoryReferenceMode,
    MemoryScope,
    MemoryUseDecision,
    MemoryUsePlan,
    ProcessTurnRequest,
    RecallRequest,
    ResponseGoal,
    ResponsePlanStatus,
)
from companion_memoryos.service import CompanionMemoryService

SCOPE = MemoryScope(companion_id="xiaohe", relationship_id="r", conversation_id="c")


def request(text: str, key: str = "turn-1") -> ProcessTurnRequest:
    return ProcessTurnRequest(
        user_id="u",
        scope=SCOPE,
        content=text,
        idempotency_key=key,
        consent=ConsentState.GRANTED,
        model_consent=ConsentState.GRANTED,
    )


class StubLLM:
    def __init__(self) -> None:
        self.inputs: list[list[ChatMessage]] = []

    def generate(self, messages: list[ChatMessage]) -> ModelResponse:
        self.inputs.append(messages)
        return ModelResponse(text=f"本地传输测试回复 {len(self.inputs)}", model="test-model")


@pytest.mark.parametrize("goal", list(ResponseGoal))
@pytest.mark.parametrize("stage", list(RelationshipStage))
def test_all_goal_stage_combinations_fit_without_losing_rules(
    goal: ResponseGoal,
    stage: RelationshipStage,
    service: CompanionMemoryService,
) -> None:
    persona = load_persona()
    compiled = compile_persona_context(persona, goal, stage, token_counter=service.token_counter)
    assert compiled.estimated_tokens == service.token_counter.count(compiled.text)
    assert compiled.estimated_tokens <= 1200
    assert f"Response Goal: {goal.value}" in compiled.text
    assert f"Familiarity Stage: {stage.value}" in compiled.text
    for invariant in persona.invariants:
        assert invariant.description in compiled.text
    assert "阿灰" not in compiled.text
    assert compiled == compile_persona_context(
        persona, goal, stage, token_counter=service.token_counter
    )


def test_loader_rejects_missing_unknown_duplicate_and_unsafe_yaml() -> None:
    data = load_persona().model_dump(mode="json")
    del data["response_styles"]["listen"]
    with pytest.raises(ValidationError, match="seven"):
        loads_persona(yaml.safe_dump(data))
    with pytest.raises(ValueError, match="duplicate YAML"):
        loads_persona("persona_id: one\npersona_id: two")
    with pytest.raises(ValueError, match="aliases"):
        loads_persona("x: &x [*x]")
    with pytest.raises(yaml.constructor.ConstructorError):
        loads_persona("!!python/object/apply:os.system ['echo forbidden']")
    data = load_persona().model_dump(mode="json")
    data["response_styles"]["LISTEN"] = data["response_styles"]["listen"]
    with pytest.raises(ValidationError, match="duplicate style"):
        PersonaDefinition.model_validate(data)
    data = load_persona().model_dump(mode="json")
    data["invented"] = "no"
    with pytest.raises(ValidationError, match="Extra inputs"):
        PersonaDefinition.model_validate(data)


def test_budget_drops_examples_before_core_and_rejects_impossible_budget(
    service: CompanionMemoryService,
) -> None:
    persona = load_persona()
    original = persona.model_dump_json()
    core = compile_persona_context(
        persona,
        ResponseGoal.LISTEN,
        RelationshipStage.NEW,
        max_examples=0,
        token_counter=service.token_counter,
    )
    compressed = compile_persona_context(
        persona,
        ResponseGoal.LISTEN,
        RelationshipStage.NEW,
        max_persona_tokens=core.estimated_tokens,
        token_counter=service.token_counter,
    )
    assert not compressed.selected_example_indices
    assert "examples.0" in compressed.omitted_items
    with pytest.raises(PersonaBudgetError):
        compile_persona_context(
            persona,
            ResponseGoal.LISTEN,
            RelationshipStage.NEW,
            max_persona_tokens=10,
            token_counter=service.token_counter,
        )
    assert persona.model_dump_json() == original


def test_seeds_have_separate_subject_version_and_storage(service: CompanionMemoryService) -> None:
    persona = load_persona()
    store = CharacterMemoryStore(service.store.database)
    store.install(persona, "xiaohe")
    store.install(persona, "xiaohe")
    memories = store.recall("xiaohe", "0.1.1", "xiaohe", "狗")
    assert len(memories) == 1
    assert memories[0].subject_actor_id == "xiaohe"
    assert memories[0].reality_layer.value == "fiction"
    assert memories[0].seed.occurred_at is None
    assert not store.recall("xiaohe", "0.1.1", "another", "狗")
    assert not store.recall("xiaohe", "0.1.2", "xiaohe", "狗")
    assert not service.export("u").memories
    persona.kernel.core_values.append("新原则")
    with pytest.raises(ValueError, match="increment version"):
        store.install(persona, "xiaohe")
    persona.version = "0.1.2"
    store.install(persona, "xiaohe")
    assert store.recall("xiaohe", "0.1.2", "xiaohe", "狗")


def test_seed_validates_salience_and_dates() -> None:
    seed = load_persona().character_memories[0].model_dump()
    with pytest.raises(ValidationError):
        CharacterMemorySeed.model_validate({**seed, "salience": float("nan")})
    with pytest.raises(ValidationError, match="timezone"):
        CharacterMemorySeed.model_validate({**seed, "occurred_at": "2001-01-01T00:00:00"})


@pytest.mark.parametrize("mode", list(MemoryReferenceMode))
def test_composer_preserves_modes_and_never_exposes_suppressed_evidence(
    service: CompanionMemoryService,
    mode: MemoryReferenceMode,
) -> None:
    stored = service.remember(
        MemoryInput(
            user_id="u",
            scope=SCOPE,
            kind=MemoryKind.SHARED_MOMENT,
            title="紫色风筝",
            content="用户小时候有一只紫色风筝",
            subject_actor_id="u",
            consent=ConsentState.GRANTED,
            explicit_user_request=True,
        )
    )
    assert stored.memory is not None
    recalled = service.recall(RecallRequest(user_id="u", scope=SCOPE, query="紫色风筝"))
    assert any(
        item.memory.id == stored.memory.id for items in recalled.sections.values() for item in items
    )
    plan = MemoryUsePlan(
        decisions=[
            MemoryUseDecision(
                evidence=ExperienceEvidenceRef(
                    kind=ExperienceEvidenceKind.MEMORY, id=stored.memory.id
                ),
                mode=mode,
            )
        ]
    )
    compiled = compile_persona_context(load_persona(), ResponseGoal.REFLECT, RelationshipStage.NEW)
    context = compose_context(
        persona=compiled,
        user_id="u",
        scope=SCOPE,
        current_user_turn="旧事",
        memory_context=recalled,
        memory_use_plan=plan,
    )
    assert ("紫色风筝" in context.text) == (mode is not MemoryReferenceMode.SUPPRESS)
    assert mode.value in context.text
    if mode is not MemoryReferenceMode.SUPPRESS:
        assert '"subject_actor_id":"u"' in context.text
    with pytest.raises(ValueError, match="another user"):
        compose_context(
            persona=compiled,
            user_id="other",
            scope=SCOPE,
            current_user_turn="hi",
            memory_context=recalled,
        )


def test_runtime_continuous_chat_restart_retry_and_metadata(
    service: CompanionMemoryService,
) -> None:
    model = StubLLM()
    agent = CompanionAgent(service, load_persona(), model)
    first = agent.chat(request("先听我说完，别给建议"), RelationshipStage.FAMILIAR)
    second_request = request("我小时候怕狗", "turn-2")
    second = agent.chat(second_request, RelationshipStage.FAMILIAR)
    assert first.turn.content in model.inputs[1][1].content
    assert (
        "阿灰" not in model.inputs[1][1].content
    )  # persistent listening withholds unsolicited backstory
    assert first.turn.metadata["response_goal"] == "listen"
    assert second.turn.metadata["persona_version"] == "0.1.1"
    assert second.turn.metadata["familiarity_stage"] == "new"
    assert second.turn.metadata["relationship_distance"] == "cautious"
    assert second.turn.actor_id == "xiaohe"
    assert len(service.list_turns("u", SCOPE)) == 4
    assert all(
        plan.status is ResponsePlanStatus.COMPLETED
        for plan in service.list_response_plans("u", SCOPE)
    )
    restarted = CompanionAgent(service, load_persona(), model)
    reused = restarted.chat(second_request, RelationshipStage.FAMILIAR)
    assert reused.reused and reused.turn.id == second.turn.id and len(model.inputs) == 2
    with pytest.raises(ValueError, match="idempotency"):
        restarted.chat(request("不同消息", "turn-2"), RelationshipStage.FAMILIAR)


def test_no_model_consent_means_no_call(service: CompanionMemoryService) -> None:
    model = StubLLM()
    agent = CompanionAgent(service, load_persona(), model)
    with pytest.raises(ValueError, match="consent"):
        agent.chat(
            request("hi").model_copy(update={"model_consent": ConsentState.DENIED}),
            RelationshipStage.NEW,
        )
    assert not model.inputs


def test_failed_generation_preserves_user_turn_and_cancels_plan(
    service: CompanionMemoryService,
) -> None:
    class FailingLLM:
        def generate(self, messages: list[ChatMessage]) -> ModelResponse:
            raise MainLLMError("main_llm_timeout")

    with pytest.raises(MainLLMError):
        CompanionAgent(service, load_persona(), FailingLLM()).chat(
            request("hi"), RelationshipStage.NEW
        )
    assert len(service.list_turns("u", SCOPE)) == 1
    assert service.list_response_plans("u", SCOPE)[0].status is ResponsePlanStatus.CANCELLED
    retry = CompanionAgent(service, load_persona(), StubLLM()).chat(
        request("hi"), RelationshipStage.NEW
    )
    assert retry.turn.content
    assert len(service.list_turns("u", SCOPE)) == 2


def test_new_turn_during_generation_prevents_stale_assistant_write(
    service: CompanionMemoryService,
) -> None:
    class InterruptedLLM:
        def generate(self, messages: list[ChatMessage]) -> ModelResponse:
            service.append_turn(
                ConversationTurnInput(
                    user_id="u",
                    scope=SCOPE,
                    actor_id="u",
                    role=ConversationRole.USER,
                    content="换个话题",
                    consent=ConsentState.GRANTED,
                )
            )
            return ModelResponse(text="旧回复", model="stub")

    with pytest.raises(ValueError):
        CompanionAgent(service, load_persona(), InterruptedLLM()).chat(
            request("hi"), RelationshipStage.NEW
        )
    assert all(turn.role is ConversationRole.USER for turn in service.list_turns("u", SCOPE))


def test_history_excludes_deleted_and_cross_scope_turns(service: CompanionMemoryService) -> None:
    hidden = service.append_turn(
        ConversationTurnInput(
            user_id="u",
            scope=SCOPE,
            actor_id="u",
            role=ConversationRole.USER,
            content="已删除的独特文字",
            consent=ConsentState.GRANTED,
        )
    )
    assert hidden.turn
    service.forget_turn(hidden.turn.id, "u")
    prepared = CompanionAgent(service, load_persona()).prepare(
        request("现在的问题"), RelationshipStage.NEW
    )
    assert "已删除的独特文字" not in prepared.context.text
    assert prepared.context.messages[-1].role == "user"


def test_http_adapter_serializes_real_input_and_rejects_incomplete_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import companion_agent.llm as transport

    response_body: dict[str, Any] = {
        "model": "configured-model",
        "choices": [{"finish_reason": "stop", "message": {"content": "接口回复"}}],
        "usage": {"prompt_tokens": 30, "completion_tokens": 4, "total_tokens": 34},
    }
    sent: list[Any] = []

    class HTTPReply:
        def __enter__(self) -> HTTPReply:
            return self

        def __exit__(self, *args: Any) -> None:
            pass

        def read(self, size: int) -> bytes:
            return json.dumps(response_body).encode()[:size]

    class Opener:
        def open(self, req: Any, timeout: float) -> HTTPReply:
            sent.append(req)
            return HTTPReply()

    monkeypatch.setattr(transport, "build_opener", lambda *args: Opener())
    monkeypatch.setenv("TEST_AGENT_KEY", "private-test-key")
    model = OpenAICompatibleMainLLM(
        InterpreterConfig(
            base_url="https://example.invalid/v1",
            model="configured-model",
            api_key_env="TEST_AGENT_KEY",
        )
    )
    result = model.generate([ChatMessage(role="user", content="hello")])
    assert result.text == "接口回复" and result.usage and result.usage.total_tokens == 34
    assert json.loads(sent[0].data)["messages"] == [{"role": "user", "content": "hello"}]
    response_body["choices"][0]["finish_reason"] = "length"
    with pytest.raises(MainLLMError, match="incomplete"):
        model.generate([ChatMessage(role="user", content="hello")])


def test_default_resources_ship_as_files() -> None:
    import companion_agent

    root = Path(companion_agent.__file__).parent
    assert (root / "persona_source/full_backstory.md").is_file()
    assert len(load_persona().examples) >= 10
