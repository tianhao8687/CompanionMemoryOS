"""Current-state behavior is checked at the actual Main LLM input boundary."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from companion_agent import CompanionAgent, CurrentStateConfig, load_persona
from companion_agent.context import ChatMessage
from companion_agent.current_state.models import StateStatus
from companion_agent.llm import MainLLMError, ModelResponse
from companion_agent.relationship import RelationshipKey
from companion_memoryos.schemas import (
    ConsentState,
    ConversationRole,
    ConversationTurnInput,
    ExperienceEvidenceKind,
    ExperienceEvidenceRef,
    MemoryReferenceFeedbackInput,
    MemoryReferenceMode,
    MemoryScope,
    MemoryUseDecision,
    MemoryUsePlan,
    OpenLoopInput,
    OpenLoopKind,
    OpenLoopStatus,
    ProcessTurnRequest,
    RealityLayer,
    ReferenceFeedbackKind,
    Sensitivity,
)
from companion_memoryos.service import CompanionMemoryService

KEY = RelationshipKey(user_id="user", companion_id="xiaohe", relationship_id="state-test")
SCOPE = MemoryScope(
    companion_id=KEY.companion_id, relationship_id=KEY.relationship_id, conversation_id="chat"
)


class CaptureModel:
    def __init__(self) -> None:
        self.messages: list[list[ChatMessage]] = []

    def generate(self, messages: list[ChatMessage]) -> ModelResponse:
        self.messages.append(messages)
        return ModelResponse(text="本地传输测试回应", model="capture-stub")


def request(
    text: str, key: str, *, scope: MemoryScope = SCOPE, **kwargs: object
) -> ProcessTurnRequest:
    return ProcessTurnRequest.model_validate(
        {
            "user_id": "user",
            "scope": scope,
            "content": text,
            "idempotency_key": key,
            "consent": "granted",
            "model_consent": "granted",
            "enable_recall": False,
            **kwargs,
        }
    )


def state_payload(model: CaptureModel) -> dict[str, object]:
    return json.loads(model.messages[-1][0].content.split("[CURRENT STATE]\n", 1)[1])


def make_agent(service: CompanionMemoryService) -> tuple[CompanionAgent, CaptureModel]:
    model = CaptureModel()
    return CompanionAgent(service, load_persona(), model, recent_turn_limit=1), model


@pytest.mark.parametrize(
    "opening",
    [
        "今天很累，先别给建议，听我说就好。",
        "我有点疲惫，别急着给方案，让我把事情说完。",
    ],
)
def test_listening_survives_history_window_restart_and_switches_now(
    service: CompanionMemoryService, opening: str
) -> None:
    agent, model = make_agent(service)
    agent.chat(request(opening, "one"))
    for index in range(3):
        reply = agent.chat(request(f"接着还有第{index}件事想说。", f"follow-{index}"))
        assert reply.turn.metadata["response_goal"] == "listen"
    recent = (
        model.messages[-1][1]
        .content.split("[RECENT CONVERSATION]\n")[1]
        .split("[CURRENT USER TURN]")[0]
    )
    assert opening not in recent
    restarted = CompanionAgent(service, load_persona(), model, recent_turn_limit=1)
    assert (
        restarted.chat(request("我还没讲完。", "restart")).turn.metadata["response_goal"]
        == "listen"
    )
    response = restarted.chat(request("缓过来了，帮我列两个办法。", "switch"))
    assert response.turn.metadata["response_goal"] == "problem_solve"
    payload = state_payload(model)
    assert payload["response_goal"] == "problem_solve"
    assert all(item["value"] != "listen" for item in payload["influence"])
    assert restarted.current_states
    assert any(
        record.value == "fatigue" for record in restarted.current_states.snapshot(KEY, "chat")
    )


def test_time_expiry_is_not_recovery_and_does_not_block_question(
    service: CompanionMemoryService,
) -> None:
    agent, model = make_agent(service)
    agent.chat(request("我昨晚没睡好。", "sleep"))
    assert agent.current_states
    assert any(
        record.value == "sleep_loss" for record in agent.current_states.snapshot(KEY, "chat")
    )
    at = datetime.now(UTC) + timedelta(hours=13)
    agent.current_states.clock = lambda: at
    response = agent.chat(request("请解释一下二分查找。", "question"))
    assert response.turn.metadata["response_goal"] == "direct_answer"
    assert not state_payload(model)["influence"]
    assert any(
        record.status is StateStatus.EXPIRED and record.reason == "expired_is_not_recovery"
        for record in agent.current_states.snapshot(KEY, "chat", include_inactive=True)
    )
    assert "已经恢复" not in json.dumps(state_payload(model), ensure_ascii=False)


def test_conflict_is_with_companion_and_repair_affects_current_turn(
    service: CompanionMemoryService,
) -> None:
    agent, model = make_agent(service)
    agent.chat(request("你刚才一直打断我，让我很不舒服。", "conflict"))
    before = agent.relationships.get_relationship(KEY)
    assert before.recent_dynamics.recent_conflict_level > 0
    agent.chat(request("还有一点我想接着讲。", "continue"))
    assert state_payload(model)["response_goal"] == "listen"
    assert "减少玩笑" in state_payload(model)["interaction_guidance"]
    reply = agent.chat(request("刚才的误会已经说开了。", "repair"))
    after = agent.relationships.get_relationship(KEY)
    assert after.recent_dynamics.recent_conflict_level == 0
    assert after.identity == before.identity and after.stage == before.stage
    assert "停止沿用" in state_payload(model)["interaction_guidance"]
    assert reply.turn.metadata["relationship_distance"] == "open"


@pytest.mark.parametrize(
    "text", ["我和同事吵架了。", "我和朋友的误会已经说开了。", "你可以随时打断我。"]
)
def test_third_party_conflict_and_permission_do_not_create_companion_conflict(
    service: CompanionMemoryService, text: str
) -> None:
    agent, _ = make_agent(service)
    agent.chat(request(text, "other"))
    assert agent.relationships.get_relationship(KEY).recent_dynamics.recent_conflict_level == 0


def test_task_priority_and_outcome_end_only_related_pressure_and_loop(
    service: CompanionMemoryService,
) -> None:
    agent, model = make_agent(service)
    source = service.append_turn(
        ConversationTurnInput(
            user_id="user",
            scope=SCOPE,
            actor_id="user",
            role=ConversationRole.USER,
            content="明天有面试",
            consent=ConsentState.GRANTED,
        )
    )
    assert source.turn
    loop = service.create_open_loop(
        OpenLoopInput(
            user_id="user",
            scope=SCOPE,
            kind=OpenLoopKind.EVENT_OUTCOME,
            summary="周一的面试",
            topic_keys=["面试"],
            source_turn_id=source.turn.id,
            consent=ConsentState.GRANTED,
        )
    )
    assert loop.open_loop
    agent.chat(request("面试让我很紧张。房租也让我担心。", "pressure"))
    response = agent.chat(request("帮我润色这段面试自我介绍。", "edit"))
    assert response.turn.metadata["response_goal"] == "direct_answer"
    assert state_payload(model)["response_goal"] == "direct_answer"
    agent.chat(request("面试已经结束，结果不错。", "outcome"))
    assert service.store.get_open_loop(loop.open_loop.id, "user").status is OpenLoopStatus.RESOLVED
    assert agent.current_states
    records = agent.current_states.snapshot(KEY, "chat")
    assert not any(record.topic == "面试" for record in records)
    assert any(record.topic == "房租" for record in records)


@pytest.mark.parametrize(
    "text",
    [
        "我朋友最近很焦虑。",
        "但我朋友最近很焦虑。",
        "我可能有点难过。",
        "去年那阵子我很难过。",
        "假设角色正在生气。",
        "你很累吗？我想问一个问题。",
        "帮我把难过翻译成英文。",
        "小禾很疲惫，我还好。",
    ],
)
def test_non_current_non_user_and_task_material_are_not_user_states(
    service: CompanionMemoryService, text: str
) -> None:
    agent, model = make_agent(service)
    agent.chat(request(text, "subject"))
    assert agent.current_states
    assert not agent.current_states.snapshot(KEY, "chat")
    assert not state_payload(model)["influence"]


def test_explicit_correction_retracts_one_state_without_clearing_others(
    service: CompanionMemoryService,
) -> None:
    agent, model = make_agent(service)
    agent.chat(request("我今天很难过，也有点累。", "start"))
    agent.chat(request("我不是难过，只是累。", "correct"))
    assert agent.current_states
    records = agent.current_states.snapshot(KEY, "chat")
    assert any(record.value == "fatigue" for record in records)
    assert not any(record.value == "sadness" for record in records)
    assert all(item["value"] != "sadness" for item in state_payload(model)["influence"])


def test_temporary_humor_expires_without_revoking_permanent_boundary(
    service: CompanionMemoryService,
) -> None:
    agent, model = make_agent(service)
    agent.chat(request("今天先别开玩笑。以后不要这样称呼我。", "limits"))
    assert any(
        boundary.id == "rejected-address" and boundary.active
        for boundary in agent.relationships.get_relationship(KEY).boundaries
    )
    assert agent.current_states
    agent.current_states.clock = lambda: datetime.now(UTC) + timedelta(days=2)
    agent.chat(request("请解释一下递归。", "later"))
    assert not any(item["slot"] == "style:humor" for item in state_payload(model)["influence"])
    assert "不随临时状态过期" in model.messages[-1][0].content


def test_stop_reference_is_not_resolution(service: CompanionMemoryService) -> None:
    agent, model = make_agent(service)
    agent.chat(request("我担心面试。", "pressure"))
    agent.chat(request("这件事别再提了。", "stop"))
    assert agent.current_states
    assert any(
        record.topic == "面试" and record.status is StateStatus.ACTIVE
        for record in agent.current_states.snapshot(KEY, "chat")
    )
    assert all(item["kind"] != "condition" for item in state_payload(model)["influence"])


def test_deleted_and_suppressed_source_cannot_drive_goal(service: CompanionMemoryService) -> None:
    agent, _ = make_agent(service)
    agent.chat(request("我只想倾诉，不想听建议。", "listen"))
    assert agent.current_states
    record = next(
        record
        for record in agent.current_states.snapshot(KEY, "chat")
        if record.slot == "communication:need"
    )
    plan = MemoryUsePlan(
        decisions=[
            MemoryUseDecision(
                evidence=ExperienceEvidenceRef(
                    kind=ExperienceEvidenceKind.TURN, id=record.source_turn_id
                ),
                mode=MemoryReferenceMode.SUPPRESS,
            )
        ]
    )
    assert not agent.current_states.snapshot(KEY, "chat", memory_use_plan=plan)
    service.record_reference_feedback(
        MemoryReferenceFeedbackInput(
            user_id="user",
            scope=SCOPE,
            evidence_kind=ExperienceEvidenceKind.TURN,
            evidence_id=record.source_turn_id,
            kind=ReferenceFeedbackKind.DO_NOT_REFERENCE,
        )
    )
    assert (
        agent.chat(request("我换个内容说。", "suppressed")).turn.metadata["response_goal"]
        != "listen"
    )
    service.forget_turn(record.source_turn_id, "user")
    assert not agent.current_states.snapshot(KEY, "chat")


def test_scope_semantics_isolation_and_sensitive_input(service: CompanionMemoryService) -> None:
    agent, _ = make_agent(service)
    agent.chat(request("我有点累，先别给建议。", "ordinary"))
    assert agent.current_states
    across = agent.current_states.snapshot(KEY, "new-conversation")
    assert any(record.value == "fatigue" for record in across)
    assert not any(record.slot == "communication:need" for record in across)
    other = RelationshipKey(user_id="someone", companion_id="xiaohe", relationship_id="state-test")
    assert not agent.current_states.snapshot(other, "chat")
    agent.prepare(
        request(
            "我很难过。",
            "sensitive",
            sensitivity=Sensitivity.SENSITIVE,
            allow_sensitive_model_input=False,
        )
    )
    assert not any(
        record.value == "sadness" for record in agent.current_states.snapshot(KEY, "chat")
    )


def test_retry_does_not_extend_deadline_and_late_turn_does_not_overwrite(
    service: CompanionMemoryService,
) -> None:
    agent, _ = make_agent(service)
    first = request("我很难过。", "sad", occurred_at=datetime.now(UTC) - timedelta(minutes=5))
    agent.chat(first)
    assert agent.current_states
    before = agent.current_states.snapshot(KEY, "chat")
    assert agent.chat(first).reused
    assert agent.current_states.snapshot(KEY, "chat") == before
    agent.chat(request("我不是难过。", "correct"))
    other_scope = SCOPE.model_copy(update={"conversation_id": "older"})
    agent.prepare(
        request(
            "我很难过。",
            "late",
            scope=other_scope,
            occurred_at=datetime.now(UTC) - timedelta(minutes=10),
        )
    )
    assert not any(
        record.value == "sadness" for record in agent.current_states.snapshot(KEY, "chat")
    )


def test_state_failure_falls_back_without_failing_chat(
    service: CompanionMemoryService, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent, model = make_agent(service)
    assert agent.current_states

    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("simulated state adapter failure")

    monkeypatch.setattr(agent.current_states, "process", fail)
    reply = agent.chat(request("帮我列两条建议。", "fallback"))
    assert reply.turn.content and reply.turn.metadata["current_state_status"] == "degraded"
    assert reply.turn.metadata["response_goal"] == "problem_solve"
    assert len(model.messages) == 1


def test_user_directive_survives_model_failure_but_no_shared_experience_is_created(
    service: CompanionMemoryService,
) -> None:
    class FailedModel:
        def generate(self, messages: list[ChatMessage]) -> ModelResponse:
            raise MainLLMError("failed")

    agent = CompanionAgent(service, load_persona(), FailedModel())
    with pytest.raises(MainLLMError):
        agent.chat(request("我只想倾诉。", "failed"))
    assert agent.current_states and any(
        record.value == "listen" for record in agent.current_states.snapshot(KEY, "chat")
    )
    assert not agent.experiences.list_experiences(KEY)


def test_opt_out_keeps_original_entrypoint(service: CompanionMemoryService) -> None:
    agent = CompanionAgent(
        service,
        load_persona(),
        CaptureModel(),
        current_state_config=CurrentStateConfig(enabled=False),
    )
    reply = agent.chat(request("你好。", "disabled"))
    assert reply.turn.metadata["current_state_status"] == "disabled"
    assert agent.current_states is None


def test_restricted_conflict_source_does_not_drive_current_distance(
    service: CompanionMemoryService,
) -> None:
    agent, model = make_agent(service)
    response = agent.chat(request("你刚才打断我，让我很不舒服。", "conflict-policy"))
    source_id = response.turn.reply_to_turn_id
    assert source_id
    service.record_reference_feedback(
        MemoryReferenceFeedbackInput(
            user_id="user",
            scope=SCOPE,
            evidence_kind=ExperienceEvidenceKind.TURN,
            evidence_id=source_id,
            kind=ReferenceFeedbackKind.DO_NOT_REFERENCE,
        )
    )
    response = agent.chat(request("我换一个内容说。", "after-policy"))
    assert response.turn.metadata["response_goal"] != "listen"
    assert response.turn.metadata["relationship_distance"] == "open"
    assert "interaction_guidance" not in state_payload(model)
    assert agent.relationships.get_relationship(KEY).recent_dynamics.recent_conflict_level > 0


def test_explicit_today_need_crosses_sessions_but_roleplay_does_not_import_it(
    service: CompanionMemoryService,
) -> None:
    agent, model = make_agent(service)
    agent.chat(request("今天只想倾诉，不用给建议。", "today"))
    other_scope = SCOPE.model_copy(update={"conversation_id": "next"})
    assert (
        agent.chat(request("我继续讲刚才的事。", "next", scope=other_scope)).turn.metadata[
            "response_goal"
        ]
        == "listen"
    )
    agent.chat(request("假设角色正在生气。", "fiction", reality_layer=RealityLayer.ROLEPLAY))
    assert not state_payload(model)["influence"]
    assert agent.current_states and agent.current_states.snapshot(KEY, "chat")


def test_storage_opt_out_keeps_current_directive_without_persisting(
    service: CompanionMemoryService,
) -> None:
    agent, _ = make_agent(service)
    response = agent.chat(request("我只想倾诉。", "no-actions", apply_low_risk_actions=False))
    assert response.turn.metadata["response_goal"] == "listen"
    assert agent.current_states and not agent.current_states.snapshot(KEY, "chat")


def test_state_migration_is_additive_and_unsupported_state_schema_degrades(
    service: CompanionMemoryService,
) -> None:
    with service.store.database.connection() as connection:
        baseline = connection.execute("PRAGMA user_version").fetchone()[0]
    make_agent(service)
    make_agent(service)
    with service.store.database.atomic() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == baseline
        assert (
            connection.execute(
                "SELECT version FROM agent_schema_versions WHERE component='current_state'"
            ).fetchone()[0]
            == 1
        )
        connection.execute(
            "UPDATE agent_schema_versions SET version=99 WHERE component='current_state'"
        )
    agent, _ = make_agent(service)
    response = agent.chat(request("请解释一下递归。", "future-schema"))
    assert response.turn.metadata["current_state_status"] == "degraded"
    assert response.turn.content


def test_pressure_can_remain_after_outcome_when_user_explicitly_reasserts_it(
    service: CompanionMemoryService,
) -> None:
    agent, _model = make_agent(service)
    agent.chat(request("我担心面试。", "stress-first"))
    agent.chat(request("面试已经结束，但我还是担心面试结果。", "stress-remains"))
    assert agent.current_states
    assert any(record.topic == "面试" for record in agent.current_states.snapshot(KEY, "chat"))


def test_concrete_character_question_temporarily_takes_priority_over_listening(
    service: CompanionMemoryService,
) -> None:
    agent, model = make_agent(service)
    agent.chat(request("今天先听我说就好。", "listen-first"))
    response = agent.chat(request("你小时候养过狗吗？", "direct-question"))
    assert response.turn.metadata["response_goal"] == "direct_answer"
    assert "阿灰" in model.messages[-1][1].content
    assert all(item["value"] != "listen" for item in state_payload(model)["influence"])


def test_reopening_releases_temporary_reference_hold(service: CompanionMemoryService) -> None:
    agent, _model = make_agent(service)
    agent.chat(request("我担心面试。", "worry"))
    agent.chat(request("这件事不要再提了。", "pause"))
    agent.chat(request("现在我们继续讨论面试。", "reopen"))
    assert agent.current_states
    assert not any(
        record.slot == "style:reference" for record in agent.current_states.snapshot(KEY, "chat")
    )


def test_corrupt_optional_state_payload_falls_back_safely(service: CompanionMemoryService) -> None:
    agent, _ = make_agent(service)
    agent.chat(request("我只想倾诉。", "first"))
    with service.store.database.atomic() as connection:
        row = connection.execute("SELECT rowid,data_json FROM agent_current_states").fetchone()
        payload = json.loads(row["data_json"])
        payload["value"] = "unsupported"
        connection.execute(
            "UPDATE agent_current_states SET data_json=? WHERE rowid=?",
            (json.dumps(payload), row["rowid"]),
        )
    response = agent.chat(request("帮我改一下开头。", "recover"))
    assert response.turn.metadata["current_state_status"] == "degraded"
    assert response.turn.metadata["response_goal"] == "direct_answer"
