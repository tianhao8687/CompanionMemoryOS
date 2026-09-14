"""Regression pairs at the parser, durable state and actual main-model boundary."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from companion_agent import CompanionAgent, CurrentStateConfig, load_persona
from companion_agent.current_state.compiler import CurrentStateBudgetError
from companion_agent.current_state.evaluator import analyze_current_turn
from companion_agent.current_state.models import StateStatus
from companion_agent.relationship.models import RelationshipUpdateKind
from companion_agent.relationship.service import candidate_for
from companion_memoryos.schemas import (
    DiscourseSignal,
    ExperienceEvidenceKind,
    MemoryReferenceFeedbackInput,
    ReferenceFeedbackKind,
    ResponseGoal,
    SpeechSpanProposal,
    TurnInterpretation,
)
from companion_memoryos.service import CompanionMemoryService
from tests.test_current_state import KEY, SCOPE, CaptureModel, make_agent, request, state_payload
from tests.test_process_turn import ScriptedInterpreter, hosted


@pytest.mark.parametrize(
    "text",
    [
        "你刚才没有打断我，我很感谢你。",
        "你并没有误解我。",
        "我并不生你的气。",
        "你不曾打断我。",
        "你刚才打断我了吗？",
        "如果你打断我，我会生气。",
        "我担心你误会我。",
        "你说我误会了你。",
    ],
)
def test_no_positive_conflict_from_negation_or_uncertainty(
    service: CompanionMemoryService, text: str
) -> None:
    agent, model = make_agent(service)
    result = service.process_turn(request(text, "negative"))
    assert not analyze_current_turn(text, result).conflict
    agent.chat(request(text, "negative"))
    assert agent.relationships.get_relationship(KEY).recent_dynamics.recent_conflict_level == 0
    assert "用户对角色的互动方式表达不满" not in model.messages[-1][0].content


@pytest.mark.parametrize(
    "text",
    [
        "我不能原谅你。",
        "我暂时不想原谅你。",
        "我还没原谅你。",
        "他说“我已经原谅你了”，但我还没有。",
        "我和同事的误会说开了，但和你还没有。",
        "如果我们和解了，我会告诉你。",
        "我明天会原谅你。",
        "我和同事有误会。误会已经说开了。",
    ],
)
def test_repair_requires_current_user_and_companion(
    service: CompanionMemoryService, text: str
) -> None:
    agent, model = make_agent(service)
    agent.chat(request("你刚才一直打断我，让我很不舒服。", "conflict"))
    result = service.process_turn(request(text, "no-repair"))
    assert not analyze_current_turn(text, result).repair
    agent.chat(request(text, "no-repair"))
    assert agent.relationships.get_relationship(KEY).recent_dynamics.recent_conflict_level > 0
    assert "用户明确表示误会已说开" not in model.messages[-1][0].content


@pytest.mark.parametrize(
    "text",
    [
        "今天我朋友很难过。",
        "最近我的同事有点累，压力也很大。",
        "他今天告诉我，他很难过。",
        "我朋友说，先别给建议。",
        "我说的不是我，是我朋友很难过。",
        "我看到朋友很难过。",
        "我觉得同事很疲惫。",
        "也许我只想倾诉。",
    ],
)
def test_subject_does_not_leak_across_clauses(service: CompanionMemoryService, text: str) -> None:
    agent, model = make_agent(service)
    agent.chat(request(text, "third-party"))
    assert agent.current_states and not agent.current_states.snapshot(KEY, "chat")
    assert not state_payload(model)["influence"]


def test_listen_then_task_is_a_changeable_request(service: CompanionMemoryService) -> None:
    agent, model = make_agent(service)
    agent.chat(request("我不是不想听建议，只是想先说完。", "order"))
    for index in range(4):
        response = agent.chat(request("还有一件事没讲。", f"continue-{index}"))
        assert response.turn.metadata["response_goal"] == "listen"
    response = agent.chat(request("现在给我两个办法。", "solutions"))
    assert response.turn.metadata["response_goal"] == "problem_solve"
    assert all(item["value"] != "listen" for item in state_payload(model)["influence"])
    assert not agent.relationships.get_relationship(KEY).boundaries


def test_question_mark_does_not_override_explicit_listening(
    service: CompanionMemoryService,
) -> None:
    agent, _ = make_agent(service)
    agent.chat(request("先听我说，别给建议。", "listen"))
    result = service.process_turn(request("唉？", "punctuation"))
    assert not analyze_current_turn("唉？", result).concrete_task
    response = agent.chat(request("唉？", "punctuation"))
    assert response.turn.metadata["response_goal"] == ResponseGoal.LISTEN.value


@pytest.mark.parametrize("text", ["我已经原谅你了。", "我们之间的误会已经说开了。"])
def test_real_repair_is_not_lost(service: CompanionMemoryService, text: str) -> None:
    agent, _ = make_agent(service)
    agent.chat(request("你刚才误解我，我很生气。", "complaint"))
    assert agent.relationships.get_relationship(KEY).recent_dynamics.recent_conflict_level > 0
    agent.chat(request(text, "repair"))
    assert agent.relationships.get_relationship(KEY).recent_dynamics.recent_conflict_level == 0


def test_current_user_subject_can_resume_after_third_party(service: CompanionMemoryService) -> None:
    agent, _ = make_agent(service)
    agent.chat(request("今天我朋友很难过，但我也有点累。", "mixed-subjects"))
    assert agent.current_states
    assert {r.value for r in agent.current_states.snapshot(KEY, "chat")} == {"fatigue"}


def test_requested_humor_overrides_temporary_style_without_claiming_recovery(
    service: CompanionMemoryService,
) -> None:
    agent, model = make_agent(service)
    agent.chat(request("我很难过，今天先别开玩笑，听我说就好。", "sad"))
    reply = agent.chat(request("讲个笑话让我缓缓。", "joke"))
    assert reply.turn.metadata["response_goal"] != "listen"
    assert "hard/reduce_humor_when_distressed" not in model.messages[-1][0].content
    assert "soft/reduce_humor_when_distressed" in model.messages[-1][0].content
    assert agent.current_states
    assert any(r.value == "sadness" for r in agent.current_states.snapshot(KEY, "chat"))
    assert not any(item["slot"] == "style:humor" for item in state_payload(model)["influence"])
    agent.chat(request("接着帮我改一段介绍。", "edit"))
    assert all(item["value"] != "listen" for item in state_payload(model)["influence"])


@pytest.mark.parametrize("explicit_distance", [False, True])
def test_returning_warmth_and_explicit_distance(
    service: CompanionMemoryService, explicit_distance: bool
) -> None:
    agent, model = make_agent(service)
    agent.chat(
        request(
            "以后保持距离吧。" if explicit_distance else "很高兴认识你！",
            "before-gap",
            occurred_at=datetime.now(UTC) - timedelta(days=60),
        )
    )
    reply = agent.chat(request("好久不见！见到你真开心！", "return"))
    assert reply.turn.metadata["relationship_distance"] == (
        "reserved" if explicit_distance else "open"
    )
    if explicit_distance:
        assert "不主动使用亲密表达" in model.messages[-1][1].content
    assert reply.turn.metadata["familiarity_stage"] == "new"


def test_reopen_only_one_topic_and_completion_does_not_release_other_holds(
    service: CompanionMemoryService,
) -> None:
    agent, model = make_agent(service)
    agent.chat(request("我担心面试。房租也让我担心。", "two-pressures"))
    agent.chat(request("先别提面试了。房租也别提了。", "two-holds"))
    agent.chat(request("帮我分析工作安排。", "different-task"))
    assert not any(item["kind"] == "condition" for item in state_payload(model)["influence"])
    agent.chat(request("现在继续聊面试。", "reopen-one"))
    assert agent.current_states
    records = agent.current_states.snapshot(KEY, "chat")
    assert {r.topic for r in records if r.slot.startswith("style:reference")} == {"房租"}
    assert {r.topic for r in records if r.kind.value == "condition"} == {"面试", "房租"}
    agent.chat(request("面试已经结束。", "outcome"))
    assert any(
        r.topic == "房租" and r.value == "hold" for r in agent.current_states.snapshot(KEY, "chat")
    )


@pytest.mark.parametrize("delete", [False, True])
@pytest.mark.parametrize("legacy", [False, True])
def test_source_restriction_covers_recent_and_derived_replies(
    service: CompanionMemoryService,
    delete: bool,
    legacy: bool,
) -> None:
    class RevealingModel(CaptureModel):
        def generate(self, messages):
            response = super().generate(messages)
            response.text = "紫丁香是一段只属于这次倾诉的暗号。"
            return response

    model = RevealingModel()
    agent = CompanionAgent(service, load_persona(), model, recent_turn_limit=6)
    first = agent.chat(request("我很难过，暗号是紫丁香。", "source"))
    agent.chat(request("我接着讲。", "derived"))
    if legacy:
        import json

        with service.store.database.atomic() as connection:
            for turn in service.list_turns("user", SCOPE):
                if turn.role.value == "assistant":
                    metadata = dict(turn.metadata)
                    metadata.pop("context_turn_ids", None)
                    connection.execute(
                        "UPDATE conversation_turns SET metadata_json=? WHERE id=?",
                        (json.dumps(metadata), turn.id),
                    )
    source_id = first.turn.reply_to_turn_id
    assert source_id
    if delete:
        service.forget_turn(source_id, "user")
    else:
        service.record_reference_feedback(
            MemoryReferenceFeedbackInput(
                user_id="user",
                scope=SCOPE,
                evidence_kind=ExperienceEvidenceKind.TURN,
                evidence_id=source_id,
                kind=ReferenceFeedbackKind.DO_NOT_REFERENCE,
            )
        )
    agent.chat(request("帮我解释一下递归。", "after-restriction"))
    assert "紫丁香" not in "\n".join(m.content for m in model.messages[-1])
    assert not any(item["value"] == "sadness" for item in state_payload(model)["influence"])


def test_explicit_correction_recovers_old_conflict_without_announcing_repair(
    service: CompanionMemoryService,
) -> None:
    agent, model = make_agent(service)
    source = service.process_turn(request("你刚才没有打断我，我很感谢你。", "old-source"))
    assert source.storage.turn
    # Simulate a state written by the baseline; correction uses the normal evidence ledger.
    agent.relationships.commit_candidates(
        KEY,
        [
            candidate_for(
                RelationshipUpdateKind.DYNAMICS,
                "旧版本的误判",
                [f"turn:{source.storage.turn.id}"],
                {
                    "recent_conflict_level": 0.85,
                    "interaction_tone": "tense",
                    "active_topics": ["关系"],
                },
                source.storage.turn.occurred_at,
            )
        ],
    )
    agent.chat(request("你记错了，我们没有吵架。", "correct-conflict"))
    dynamics = agent.relationships.get_relationship(KEY).recent_dynamics
    assert dynamics.recent_conflict_level == 0 and dynamics.interaction_tone.value == "neutral"
    assert dynamics.recent_closeness_change.value == "stable"
    assert dynamics.evidence_ids[0].startswith("user_correction:")
    assert "goal_authority" in state_payload(model)


def test_denied_repair_corrects_a_previous_false_resolution(
    service: CompanionMemoryService,
) -> None:
    agent, _ = make_agent(service)
    agent.chat(request("你刚才打断我，让我不舒服。", "conflict"))
    agent.chat(request("我原谅你了。", "old-repair"))
    agent.chat(request("你记错了，我还没原谅你。", "correction"))
    relationship = agent.relationships.get_relationship(KEY)
    assert relationship.recent_dynamics.recent_conflict_level > 0
    assert any(
        t.id == "relationship-conflict" and t.status.value == "open"
        for t in relationship.unresolved_threads
    )


@pytest.mark.parametrize("enabled", [False, True])
def test_legacy_relationship_path_uses_same_semantics(
    service: CompanionMemoryService, enabled: bool
) -> None:
    agent = CompanionAgent(
        service,
        load_persona(),
        CaptureModel(),
        current_state_config=CurrentStateConfig(enabled=enabled),
    )
    agent.chat(request("你刚才打断我，让我不舒服。", "complaint"))
    agent.chat(request("我不能原谅你。", "denial"))
    assert agent.relationships.get_relationship(KEY).recent_dynamics.recent_conflict_level > 0
    agent.chat(request("我已经原谅你了。", "accept"))
    assert agent.relationships.get_relationship(KEY).recent_dynamics.recent_conflict_level == 0


def test_unguarded_model_label_is_not_a_persistent_directive(
    service: CompanionMemoryService,
) -> None:
    interpreter = ScriptedInterpreter(
        TurnInterpretation(discourse_signals=[DiscourseSignal.LISTEN_ONLY])
    )
    memory = hosted(service, interpreter)
    agent, model = make_agent(memory)
    agent.chat(request("今天我朋友很难过。", "model-guess"))
    assert agent.current_states and not agent.current_states.snapshot(KEY, "chat")
    assert not state_payload(model)["influence"]
    assert len(interpreter.contexts) == 1  # No additional model call for Current State.


def test_model_direct_span_cannot_borrow_a_quoted_request(service: CompanionMemoryService) -> None:
    text = "他说先听我说，别给建议。我现在很好。"
    interpreter = ScriptedInterpreter(
        TurnInterpretation(
            speech_spans=[
                SpeechSpanProposal(start_offset=text.index("我现在"), end_offset=len(text))
            ],
            discourse_signals=[DiscourseSignal.LISTEN_ONLY],
        )
    )
    memory = hosted(service, interpreter)
    result = memory.process_turn(request(text, "quoted-directive"))
    assert result.discourse and DiscourseSignal.LISTEN_ONLY not in result.discourse.signals


def test_budget_never_silently_drops_explicit_restrictions(service: CompanionMemoryService) -> None:
    model = CaptureModel()
    agent = CompanionAgent(
        service,
        load_persona(),
        model,
        current_state_config=CurrentStateConfig(max_context_tokens=100),
    )
    with pytest.raises(CurrentStateBudgetError):
        agent.chat(request("先别提面试，也别提房租。今天不要开玩笑。", "too-many"))
    assert not model.messages
    assert agent.current_states
    assert all(r.status is StateStatus.ACTIVE for r in agent.current_states.snapshot(KEY, "chat"))


@pytest.mark.parametrize("text", ["以后不要叫我宝贝。", "以后不要叫我“宝贝”。"])
def test_rejected_address_keeps_its_object_after_the_recent_window(
    service: CompanionMemoryService,
    text: str,
) -> None:
    agent, model = make_agent(service)
    agent.chat(request(text, "address"))
    for index in range(3):
        agent.chat(request("帮我翻译一句话。", f"after-address-{index}"))
    relationship_data = model.messages[-1][1].content.split("[CURRENT STATE]")[0]
    assert "宝贝" in relationship_data
    assert "宝贝" not in model.messages[-1][0].content  # User data is not a system instruction.


def test_source_revoked_during_generation_prevents_sending_a_derived_reply(
    service: CompanionMemoryService,
) -> None:
    agent, model = make_agent(service)
    response = agent.chat(request("我很难过。", "source-before-race"))
    source = response.turn.reply_to_turn_id
    assert source

    class RevokingModel(CaptureModel):
        def generate(self, messages):
            service.forget_turn(source, "user")
            return super().generate(messages)

    agent.main_llm = RevokingModel()
    with pytest.raises(ValueError, match="context source invalidated"):
        agent.chat(request("我接着讲。", "race"))
    assert len(model.messages) == 1
    assert (
        len([turn for turn in service.list_turns("user", SCOPE) if turn.role.value == "assistant"])
        == 1
    )


@pytest.mark.parametrize("text", ["先听我说。", "请听我讲。"])
def test_short_explicit_listening_request_survives_the_window(
    service: CompanionMemoryService,
    text: str,
) -> None:
    agent, _ = make_agent(service)
    agent.chat(request(text, "short-request"))
    for index in range(3):
        response = agent.chat(request("还有后面的事。", f"follow-short-{index}"))
        assert response.turn.metadata["response_goal"] == "listen"


def test_host_style_hint_does_not_remove_an_active_user_request(
    service: CompanionMemoryService,
) -> None:
    agent, model = make_agent(service)
    agent.chat(request("今天先听我说，别给建议。", "user-request"))
    agent.chat(request("还有一些事。", "host-hint"), response_goal=ResponseGoal.COMFORT)
    assert state_payload(model)["goal_authority"] == "suggestion"
    assert any(
        item["authority"] == "explicit_request" and item["value"] == "listen"
        for item in state_payload(model)["influence"]
    )
