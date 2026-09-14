"""Scope regressions through direct parsing, persistence and the next model input."""

from __future__ import annotations

import json

import pytest

from companion_agent import CompanionAgent, CurrentStateConfig, load_persona
from companion_agent.current_state.evaluator import analyze_current_turn
from companion_memoryos.discourse import grounded_model_signals
from companion_memoryos.schemas import DiscourseSignal, ResponseGoal, TurnInterpretation
from companion_memoryos.service import CompanionMemoryService
from tests.test_current_state import KEY, CaptureModel, make_agent, request, state_payload
from tests.test_process_turn import ScriptedInterpreter, hosted

CONDITIONAL_REPAIRS = [
    "如果你道歉，我就原谅你。",
    "假如你认真道歉，我才原谅你。",
    "只要你不再打断我，我就原谅你。",
    "你道歉的话，我就原谅你。",
    "我会原谅你，前提是你先道歉。",
    "如果你道歉，我们之间的误会就说开了。",
    "我原谅你，只要你认真道歉。",
    "等你道歉，我才原谅你。",
    "你先认真道歉，我才原谅你。",
]
ORDERED_REQUESTS = [
    "先听我说完，之后再帮我想办法。",
    "请先听我讲完，再给我两个建议。",
    "先听我说完再帮我想办法。",
    "稍后再帮我想办法，现在先听我说。",
    "先听我说，等我说完再帮我分析。",
    "先不要再给我建议，之后再帮我想办法。",
]
DENIED_REPORTS = [
    "我没有说你打断我。",
    "我没说过你刚才误解我。",
    "我并不是说你不尊重我。",
    "你记错了，我没有说你打断我。",
    "我没有说我原谅你了。",
    "我没有说过，你刚才打断了我。",
    "我没有否认你打断我。",
]


def relationship_payload(model: CaptureModel) -> dict:
    content = model.messages[-1][1].content.split("[RELATIONSHIP CONTEXT]\n", 1)[1]
    return json.JSONDecoder().raw_decode(content)[0]


@pytest.mark.parametrize("text", CONDITIONAL_REPAIRS + DENIED_REPORTS)
def test_unasserted_relation_is_neither_conflict_nor_repair(text: str) -> None:
    analysis = analyze_current_turn(text)
    assert not analysis.repair
    assert not analysis.conflict
    assert not analysis.conflict_correction


@pytest.mark.parametrize("text", ORDERED_REQUESTS)
def test_current_request_precedes_deferred_action(text: str) -> None:
    analysis = analyze_current_turn(text)
    assert analysis.explicit_goal is ResponseGoal.LISTEN
    assert not analysis.concrete_task
    assert grounded_model_signals(text, [DiscourseSignal.ADVICE_REQUESTED]) == []


@pytest.mark.parametrize("text", CONDITIONAL_REPAIRS)
@pytest.mark.parametrize("current_state_enabled", [False, True])
def test_conditional_repair_preserves_dynamics_thread_and_next_context(
    service: CompanionMemoryService, text: str, current_state_enabled: bool
) -> None:
    model = CaptureModel()
    agent = CompanionAgent(
        service,
        load_persona(),
        model,
        recent_turn_limit=1,
        current_state_config=CurrentStateConfig(enabled=current_state_enabled),
    )
    agent.chat(request("你刚才确实打断了我。", "conflict"))
    before = agent.relationships.get_relationship(KEY)
    assert before.recent_dynamics.recent_conflict_level > 0
    agent.chat(request(text, "conditional"))
    assert text in model.messages[-1][1].content
    after = agent.relationships.get_relationship(KEY)
    assert after.recent_dynamics == before.recent_dynamics
    assert after.unresolved_threads == before.unresolved_threads
    assert any(t.status.value == "open" for t in after.unresolved_threads)
    agent.chat(request("关于我们的关系，还有一些事情想说。", "next-turn"))
    payload = relationship_payload(model)
    assert payload["recent_dynamic_summary"] == before.recent_dynamics.summary
    assert payload["unresolved_threads"]
    agent.chat(request("我原谅你了。", "actual-repair"))
    repaired = agent.relationships.get_relationship(KEY)
    assert repaired.recent_dynamics.recent_conflict_level == 0
    assert all(t.status.value == "resolved" for t in repaired.unresolved_threads)
    assert relationship_payload(model)["recent_dynamic_summary"] == repaired.recent_dynamics.summary


@pytest.mark.parametrize("text", DENIED_REPORTS)
@pytest.mark.parametrize("existing_conflict", [False, True])
def test_denied_report_does_not_create_or_erase_other_conflict(
    service: CompanionMemoryService, text: str, existing_conflict: bool
) -> None:
    agent, model = make_agent(service)
    if existing_conflict:
        agent.chat(request("你刚才确实误解了我。", "other-conflict"))
    else:
        agent.chat(request("你好。", "greeting"))
    before = agent.relationships.get_relationship(KEY)
    agent.chat(request(text, "denied-report"))
    after = agent.relationships.get_relationship(KEY)
    assert after.recent_dynamics == before.recent_dynamics
    assert after.unresolved_threads == before.unresolved_threads
    agent.chat(request("关于我们的关系，还有一些事情想说。", "next-turn"))
    payload = relationship_payload(model)
    assert payload["recent_dynamic_summary"] == (
        before.recent_dynamics.summary if existing_conflict else None
    )
    assert bool(payload["unresolved_threads"]) is existing_conflict


@pytest.mark.parametrize("text", ORDERED_REQUESTS)
def test_order_survives_window_and_switches_only_on_current_request(
    service: CompanionMemoryService, text: str
) -> None:
    agent, model = make_agent(service)
    reply = agent.chat(request(text, "ordered"))
    assert reply.turn.metadata["response_goal"] == "listen"
    for index in range(3):
        reply = agent.chat(request("还有后面的事情。", f"continuation-{index}"))
        assert reply.turn.metadata["response_goal"] == "listen"
        assert any(item["value"] == "listen" for item in state_payload(model)["influence"])
    reply = agent.chat(request("现在可以帮我想办法。", "now-advice"))
    assert reply.turn.metadata["response_goal"] == "problem_solve"
    assert not any(item["value"] == "listen" for item in state_payload(model)["influence"])


@pytest.mark.parametrize(
    "text",
    [
        "我现在很累，如果你有空，先听我说说。",
        "我没有说你打断我，但我现在很累。",
        "我现在很累，等我说完再帮我分析。",
    ],
)
def test_independent_current_self_report_is_preserved(
    service: CompanionMemoryService, text: str
) -> None:
    agent, model = make_agent(service)
    agent.chat(request(text, "mixed-scope"))
    agent.chat(request("我接着讲。", "next-turn"))
    assert agent.current_states
    assert any(r.value == "fatigue" for r in agent.current_states.snapshot(KEY, "chat"))
    assert any(item["value"] == "fatigue" for item in state_payload(model)["influence"])


@pytest.mark.parametrize(
    "text",
    [
        "等我说完再帮我想办法。",
        "等我讲完，再给我建议。",
        "如果你有空，帮我想办法。",
        "我没有说现在要你帮我想办法。",
    ],
)
def test_interpreter_cannot_promote_unasserted_advice(
    service: CompanionMemoryService, text: str
) -> None:
    interpreter = ScriptedInterpreter(
        TurnInterpretation(discourse_signals=[DiscourseSignal.ADVICE_REQUESTED])
    )
    memory = hosted(service, interpreter)
    result = memory.process_turn(request(text, "unasserted-model"))
    assert result.discourse and DiscourseSignal.ADVICE_REQUESTED not in result.discourse.signals
    assert len(interpreter.contexts) == 1
    analysis = analyze_current_turn(text)
    assert analysis.explicit_goal is None and not analysis.concrete_task


@pytest.mark.parametrize(
    "text",
    [
        "我没有说你打断我，但你刚才确实误解了我。",
        "先听我说，你刚才确实打断了我。",
    ],
)
def test_independent_positive_complaint(text: str) -> None:
    analysis = analyze_current_turn(text)
    assert analysis.conflict and not analysis.repair


def test_action_order_can_start_with_advice() -> None:
    analysis = analyze_current_turn("先帮我想办法，之后再听我说完。")
    assert analysis.explicit_goal is ResponseGoal.PROBLEM_SOLVE


@pytest.mark.parametrize(
    "text",
    [
        "我原谅你了。",
        "你已经道歉了，我这才原谅你。",
        "我已经原谅你了，如果以后再有误会，我会告诉你。",
        "然后我已经原谅你了。",
    ],
)
def test_affirmed_repair_is_preserved_alongside_other_scopes(text: str) -> None:
    analysis = analyze_current_turn(text)
    assert analysis.repair and not analysis.conflict


def test_denied_self_report_does_not_retract_an_existing_condition(
    service: CompanionMemoryService,
) -> None:
    agent, model = make_agent(service)
    agent.chat(request("我很累。", "fatigue"))
    agent.chat(request("我没有说我不累。", "denied-self-report"))
    agent.chat(request("还有一些事情。", "next-turn"))
    assert any(item["value"] == "fatigue" for item in state_payload(model)["influence"])


def test_unfinished_speech_is_not_a_denied_report() -> None:
    analysis = analyze_current_turn("我还没说完，先听我说。")
    assert analysis.explicit_goal is ResponseGoal.LISTEN
