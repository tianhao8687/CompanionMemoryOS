"""v0.2 engineering regression; all models are local stubs, no live model experiments."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from companion_agent import CompanionAgent, RelationshipStage, load_persona
from companion_agent.context import ChatMessage, compose_context
from companion_agent.llm import MainLLMError, ModelResponse
from companion_agent.persona import compile_persona_context
from companion_agent.relationship import RelationshipConfig, RelationshipKey, RelationshipService
from companion_agent.relationship.compiler import (
    RelationshipBudgetError,
    compile_relationship_context,
)
from companion_agent.relationship.evaluator import LocalRelationshipEvaluator
from companion_agent.relationship.models import (
    EvidenceStrength,
    RelationshipChangeType,
    RelationshipDynamics,
    RelationshipEvidenceRef,
    RelationshipIdentity,
    RelationshipMilestone,
    RelationshipModel,
    RelationshipPattern,
    RelationshipPatternStatus,
    RelationshipStageState,
    RelationshipThreadStatus,
    RelationshipUpdateKind,
)
from companion_agent.relationship.service import candidate_for
from companion_agent.relationship.store import RelationshipConflictError, RelationshipStore
from companion_agent.relationship.transitions import evaluate_distance, evaluate_transition
from companion_agent.semantics import RelationshipDistance
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
    OpenLoopInput,
    OpenLoopKind,
    OpenLoopTransition,
    OpenLoopUpdateRequest,
    ProcessTurnRequest,
    RealityLayer,
    ResponseGoal,
    Sensitivity,
    SpeechSpan,
)
from companion_memoryos.service import CompanionMemoryService

KEY = RelationshipKey(user_id="alice", companion_id="xiaohe", relationship_id="r1")
SCOPE = MemoryScope(
    companion_id=KEY.companion_id, relationship_id=KEY.relationship_id, conversation_id="c1"
)


def turn(
    service: CompanionMemoryService,
    text: str = "用户直接反馈",
    *,
    at: datetime | None = None,
    scope: MemoryScope = SCOPE,
    user: str = "alice",
    **kwargs: Any,
) -> str:
    stored = service.append_turn(
        ConversationTurnInput(
            user_id=user,
            scope=scope,
            actor_id=user,
            role=ConversationRole.USER,
            content=text,
            consent=ConsentState.GRANTED,
            occurred_at=at or datetime.now(UTC),
            **kwargs,
        )
    )
    assert stored.turn is not None
    return stored.turn.id


def process(
    service: CompanionMemoryService,
    text: str,
    *,
    at: datetime | None = None,
    key: str | None = None,
) -> Any:
    at = at or datetime.now(UTC)
    return service.process_turn(
        ProcessTurnRequest(
            user_id="alice",
            scope=SCOPE,
            content=text,
            idempotency_key=key or at.isoformat(),
            consent=ConsentState.GRANTED,
            model_consent=ConsentState.DENIED,
            occurred_at=at,
        )
    )


def evaluate_and_commit(
    service: CompanionMemoryService, text: str, *, at: datetime | None = None
) -> RelationshipModel:
    relations = RelationshipService(service)
    result = process(service, text, at=at)
    at = result.storage.turn.occurred_at
    model = relations.get_relationship(KEY, as_of=at)
    candidates = LocalRelationshipEvaluator().evaluate(result, model, relations)
    return relations.commit_candidates(KEY, candidates, as_of=at)


class StubLLM:
    def __init__(self) -> None:
        self.inputs: list[list[ChatMessage]] = []

    def generate(self, messages: list[ChatMessage]) -> ModelResponse:
        self.inputs.append(messages)
        return ModelResponse(text="本地接口测试回复", model="stub")


def chat_request(text: str, key: str = "message-1") -> ProcessTurnRequest:
    return ProcessTurnRequest(
        user_id="alice",
        scope=SCOPE,
        content=text,
        idempotency_key=key,
        consent=ConsentState.GRANTED,
        model_consent=ConsentState.GRANTED,
    )


def test_additive_migration_is_idempotent_and_preserves_memoryos(
    service: CompanionMemoryService,
) -> None:
    identifier = turn(service, "迁移前的原始消息")
    with service.store.database.connection() as connection:
        before = connection.execute("PRAGMA user_version").fetchone()[0]
    RelationshipStore(service.store.database).migrate()
    RelationshipStore(service.store.database).migrate()
    with service.store.database.connection() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == before
        assert (
            connection.execute(
                "SELECT version FROM agent_schema_versions WHERE component='relationship'"
            ).fetchone()[0]
            == 2
        )
    assert service.store.get_turn(identifier, "alice").content == "迁移前的原始消息"


@pytest.mark.parametrize(
    "other",
    [
        RelationshipKey(user_id="bob", companion_id="xiaohe", relationship_id="r1"),
        RelationshipKey(user_id="alice", companion_id="another", relationship_id="r1"),
        RelationshipKey(user_id="alice", companion_id="xiaohe", relationship_id="r2"),
    ],
)
def test_relationship_identity_isolation(
    service: CompanionMemoryService, other: RelationshipKey
) -> None:
    relations = RelationshipService(service)
    model = evaluate_and_commit(service, "我们是朋友。")
    assert model.identity.labels == ["朋友"]
    assert not relations.get_relationship(other).identity.labels
    assert not relations.get_history(other)
    candidate = relations.get_candidates(KEY)[0][0]
    with pytest.raises((KeyError, ValueError)):
        relations.commit_candidates(other, [candidate])


def test_identity_requires_direct_confirmation_and_aware_time() -> None:
    with pytest.raises(ValidationError):
        RelationshipIdentity(labels=["恋人"], confirmed_by_user=False)
    with pytest.raises(ValidationError, match="timezone"):
        RelationshipStageState(entered_at=datetime(2026, 1, 1))
    with pytest.raises(ValueError, match="qualified"):
        RelationshipEvidenceRef.parse("raw-id")
    with pytest.raises(ValidationError):
        RelationshipKey(user_id="same", companion_id="same", relationship_id="r")


def test_pattern_merges_distinct_observations_and_retry_does_not_count(
    service: CompanionMemoryService,
) -> None:
    relations = RelationshipService(service)
    start = datetime.now(UTC) - timedelta(days=4)
    counts: list[int] = []
    confidence: list[float] = []
    for day in range(3):
        result = process(service, "直接告诉我哪个好。", at=start + timedelta(days=day))
        candidates = LocalRelationshipEvaluator().evaluate(
            result, relations.get_relationship(KEY), relations
        )
        model = relations.commit_candidates(KEY, candidates)
        before_retry = model.revision
        assert relations.commit_candidates(KEY, candidates).revision == before_retry
        assert len(model.patterns) == 1
        counts.append(model.patterns[0].observation_count)
        confidence.append(model.patterns[0].confidence)
    assert counts == [1, 2, 3]
    assert confidence[0] < confidence[1] < confidence[2]
    assert model.patterns[0].status is RelationshipPatternStatus.ESTABLISHED
    assert model.stage is RelationshipStage.NEW


def test_single_weak_humor_feedback_never_establishes_preference(
    service: CompanionMemoryService,
) -> None:
    model = evaluate_and_commit(service, "哈哈你嘴真毒。")
    assert model.patterns[0].status is RelationshipPatternStatus.CANDIDATE
    context = compile_relationship_context(model, ResponseGoal.LISTEN, "再来个玩笑")
    assert not context.relevant_patterns
    assert model.stage is RelationshipStage.NEW


def test_context_specific_exception_preserves_long_term_pattern(
    service: CompanionMemoryService,
) -> None:
    model = evaluate_and_commit(service, "讨论技术时我更喜欢直接回答。")
    assert model.patterns[0].status is RelationshipPatternStatus.ESTABLISHED
    agent = CompanionAgent(service, load_persona(), StubLLM())
    reply = agent.chat(chat_request("今天我不想听方案，就想吐槽。", "listen"))
    model = agent.relationships.get_relationship(KEY)
    assert len(model.patterns) == 1 and model.patterns[0].id == "technical-directness"
    assert reply.turn.metadata["response_goal"] == "listen"
    assert agent.current_states and any(
        r.value == "listen" for r in agent.current_states.snapshot(KEY, "c1")
    )
    assert model.recent_dynamics.summary is None
    context = compile_relationship_context(model, ResponseGoal.LISTEN, "今天老板又找我谈了")
    assert not context.relevant_patterns
    assert context.recent_dynamic_summary is None


@pytest.mark.parametrize("text", ["她说我们是恋人。", "如果我们是恋人会怎样？", "我们不是朋友吗？"])
def test_reported_hypothetical_or_question_does_not_confirm_identity(
    service: CompanionMemoryService, text: str
) -> None:
    model = evaluate_and_commit(service, text)
    assert not model.identity.confirmed_by_user


def test_quote_roleplay_assistant_and_third_party_memory_are_not_evidence(
    service: CompanionMemoryService,
) -> None:
    relations = RelationshipService(service)
    roleplay = service.process_turn(
        chat_request("我们是恋人。", "rp").model_copy(
            update={"reality_layer": RealityLayer.ROLEPLAY}
        )
    )
    assert not LocalRelationshipEvaluator().evaluate(
        roleplay, relations.get_relationship(KEY), relations
    )
    text = "我们是恋人"
    quoted = turn(
        service,
        text,
        speech_spans=[
            SpeechSpan(
                start_offset=0,
                end_offset=len(text),
                quote_depth=1,
                attributed_speaker_id="other",
                reality_layer=RealityLayer.QUOTE,
                machine_generated=False,
            )
        ],
    )
    assert not relations.evidence_valid(KEY, f"turn:{quoted}", datetime.now(UTC))
    assistant = service.append_turn(
        ConversationTurnInput(
            user_id="alice",
            scope=SCOPE,
            actor_id="xiaohe",
            role=ConversationRole.ASSISTANT,
            content=text,
            consent=ConsentState.GRANTED,
        )
    )
    assert assistant.turn
    assert not relations.evidence_valid(KEY, f"turn:{assistant.turn.id}", datetime.now(UTC))
    stored = service.remember(
        MemoryInput(
            user_id="alice",
            scope=SCOPE,
            kind=MemoryKind.RELATIONSHIP,
            title="第三人的朋友",
            content="李明和王强是朋友",
            subject_actor_id="liming",
            consent=ConsentState.GRANTED,
            explicit_user_request=True,
        )
    )
    assert stored.memory
    assert not relations.evidence_valid(KEY, f"memory:{stored.memory.id}", datetime.now(UTC))


def test_direct_identity_and_calendar_correction_do_not_invent_history(
    service: CompanionMemoryService,
) -> None:
    model = evaluate_and_commit(service, "我们不是恋人。")
    assert model.identity.romantic is False and model.identity.confirmed_by_user
    assert model.boundaries[0].active
    model = evaluate_and_commit(service, "我们其实已经认识半年了。")
    assert model.started_at.month != datetime.now(UTC).month
    assert len(model.interactions) == 2
    assert model.stage is RelationshipStage.NEW
    assert any(
        item.change_type is RelationshipChangeType.TEMPORAL_CORRECTED
        for item in RelationshipService(service).get_history(KEY)
    )


def test_user_boundary_is_in_current_reply_preview_but_only_commits_after_success(
    service: CompanionMemoryService,
) -> None:
    model = StubLLM()
    agent = CompanionAgent(service, load_persona(), model)
    prepared = agent.prepare(chat_request("我不喜欢你这么叫我。"))
    assert prepared.context.relationship and prepared.context.relationship.active_boundaries
    assert not agent.relationships.get_relationship(KEY).boundaries
    reply = agent.chat(chat_request("我不喜欢你这么叫我。"))
    assert "不要再使用" in model.inputs[0][1].content
    assert agent.relationships.get_relationship(KEY).boundaries
    assert reply.turn.metadata["agent_version"] == "0.4.1"
    assert (
        reply.turn.metadata["relationship_revision_after"]
        > reply.turn.metadata["relationship_revision"]
    )
    revision = agent.relationships.get_relationship(KEY).revision
    assert agent.chat(chat_request("我不喜欢你这么叫我。")).reused
    assert agent.relationships.get_relationship(KEY).revision == revision


def stage_fixture() -> RelationshipModel:
    start = datetime.now(UTC) - timedelta(days=90)
    refs = [f"turn:{i}" for i in range(14)]
    return RelationshipModel(
        **KEY.model_dump(),
        started_at=start,
        interactions={ref: start + timedelta(days=i * 7) for i, ref in enumerate(refs)},
        identity=RelationshipIdentity(
            labels=["朋友"], confirmed_by_user=True, confirmed_at=start, evidence_ids=[refs[0]]
        ),
        patterns=[
            RelationshipPattern(
                id=f"p{i}",
                description="稳定习惯",
                category="ritual",
                confidence=0.9,
                first_observed_at=start,
                last_observed_at=start + timedelta(days=80),
                evidence_ids=refs[:3],
                observation_count=3,
                status="established",
            )
            for i in range(2)
        ],
        milestones=[
            RelationshipMilestone(
                id=f"m{i}",
                title="重要共同经历",
                summary="有来源的共同经历",
                importance=0.9,
                evidence_ids=[refs[i]],
            )
            for i in range(3)
        ],
    )


def test_stage_multi_dimension_upgrade_and_inactivity_preserves_history() -> None:
    model = stage_fixture()
    at = datetime.now(UTC) + timedelta(days=2)
    state = evaluate_transition(model, RelationshipConfig(), at)
    assert state.stage is RelationshipStage.FAMILIAR and state.reasons and state.evidence_ids
    model.stage, model.stage_state = state.stage, state
    state = evaluate_transition(model, RelationshipConfig(), at)
    assert state.stage is RelationshipStage.CLOSE
    model.stage, model.stage_state = state.stage, state
    state = evaluate_transition(model, RelationshipConfig(), at + timedelta(days=50))
    assert state.stage is RelationshipStage.ESTABLISHED
    model.stage, model.stage_state = state.stage, state
    assert (
        evaluate_transition(model, RelationshipConfig(), at + timedelta(days=51)).stage
        is RelationshipStage.ESTABLISHED
    )


def test_message_volume_alone_and_long_duration_alone_do_not_upgrade() -> None:
    model = RelationshipModel(
        **KEY.model_dump(),
        started_at=datetime.now(UTC) - timedelta(days=365),
        interactions={f"turn:{i}": datetime.now(UTC) for i in range(100)},
    )
    assert (
        evaluate_transition(model, RelationshipConfig(), datetime.now(UTC)).stage
        is RelationshipStage.NEW
    )


def test_conflict_is_context_but_user_distance_is_binding() -> None:
    model = stage_fixture()
    at = datetime.now(UTC)
    model.stage = RelationshipStage.CLOSE
    model.stage_state = RelationshipStageState(stage="close", entered_at=at)
    model.recent_dynamics = RelationshipDynamics(
        updated_at=at, recent_conflict_level=0.95, evidence_ids=["turn:1"]
    )
    assert (
        evaluate_transition(model, RelationshipConfig(), at).stage is RelationshipStage.ESTABLISHED
    )
    assert evaluate_distance(model, RelationshipConfig(), at) is RelationshipDistance.OPEN
    assert model.recent_dynamics.recent_conflict_level == 0.95
    model.distance_ceiling = RelationshipStage.NEW
    model.distance_evidence_ids = ["turn:2"]
    state = evaluate_transition(model, RelationshipConfig(), at)
    assert state.stage is RelationshipStage.ESTABLISHED
    assert evaluate_distance(model, RelationshipConfig(), at) is RelationshipDistance.RESERVED


def test_temporary_host_stage_never_overrides_explicit_user_distance(
    service: CompanionMemoryService,
) -> None:
    agent = CompanionAgent(service, load_persona(), StubLLM())
    response = agent.chat(chat_request("我们保持距离吧。"), RelationshipStage.CLOSE)
    assert response.turn.metadata["relationship_stage"] == "new"
    assert agent.relationships.get_relationship(KEY).distance_ceiling is RelationshipStage.NEW


def test_milestone_importance_filter_and_revision_history(service: CompanionMemoryService) -> None:
    relations = RelationshipService(service)
    ref = f"turn:{turn(service)}"
    low = candidate_for(
        RelationshipUpdateKind.MILESTONE,
        "低价值事件",
        [ref],
        {"id": "low", "title": "普通问候", "summary": "普通问候", "importance": 0.2},
        datetime.now(UTC),
    )
    assert not relations.commit_candidates(KEY, [low]).milestones
    model = evaluate_and_commit(service, "这次和你的深夜聊天对我很重要。")
    assert not model.milestones  # a single importance statement is no longer a milestone
    history = relations.get_history(KEY)
    assert [revision.revision for revision in history] == list(range(1, model.revision + 1))
    assert all(revision.before is not None and revision.after is not None for revision in history)


def test_openloop_creation_and_resolution_are_reused(service: CompanionMemoryService) -> None:
    relations = RelationshipService(service)
    source = process(service, "我在考虑换工作")
    assert source.storage.turn
    loop = service.create_open_loop(
        OpenLoopInput(
            user_id="alice",
            scope=SCOPE,
            kind=OpenLoopKind.EVENT_OUTCOME,
            summary="是否换工作",
            topic_keys=["工作"],
            source_turn_id=source.storage.turn.id,
            consent=ConsentState.GRANTED,
        )
    )
    assert loop.open_loop
    candidates = LocalRelationshipEvaluator().evaluate(
        source, relations.get_relationship(KEY), relations
    )
    model = relations.commit_candidates(KEY, candidates)
    assert model.unresolved_threads[0].open_loop_id == loop.open_loop.id
    service.update_open_loop(
        loop.open_loop.id,
        OpenLoopUpdateRequest(
            user_id="alice",
            transition=OpenLoopTransition.RESOLVE,
            resolution_summary="已经决定留任",
        ),
    )
    model = evaluate_and_commit(service, "我已经决定留任了。")
    assert model.unresolved_threads[0].status is RelationshipThreadStatus.RESOLVED


def test_compiler_selects_topic_relevance_and_prioritizes_boundaries(
    service: CompanionMemoryService,
) -> None:
    model = evaluate_and_commit(service, "讨论技术时我更喜欢直接回答。")
    model = evaluate_and_commit(service, "我不喜欢空泛安慰。")
    model = evaluate_and_commit(service, "这次和你的深夜聊天对我很重要。")
    model.milestones.append(
        RelationshipMilestone(
            id="reviewed-history",
            title="深夜聊天",
            summary="一段已审阅的共同交流",
            importance=0.9,
            evidence_ids=list(model.interactions)[-1:],
        )
    )
    technical = compile_relationship_context(model, ResponseGoal.DIRECT_ANSWER, "RTX 5070哪个好？")
    assert technical.relevant_patterns and technical.active_boundaries
    assert not technical.relevant_milestones
    relational = compile_relationship_context(
        model, ResponseGoal.REFLECT, "感觉你最近跟以前不一样了"
    )
    assert relational.relevant_milestones
    assert relational.estimated_tokens <= 700
    assert relational.estimated_tokens == service.token_counter.count(relational.text)
    with pytest.raises(RelationshipBudgetError):
        compile_relationship_context(model, ResponseGoal.REFLECT, "我们", max_relationship_tokens=5)


def test_old_dynamics_expire_and_core_persona_never_changes() -> None:
    model = stage_fixture()
    persona = load_persona()
    before = persona.model_dump_json()
    model.recent_dynamics = RelationshipDynamics(
        summary="过期紧张状态",
        updated_at=datetime.now(UTC) - timedelta(days=10),
        evidence_ids=["turn:1"],
    )
    compiled = compile_relationship_context(model, ResponseGoal.REFLECT, "我们最近")
    assert compiled.recent_dynamic_summary is None
    for stage in RelationshipStage:
        output = compile_persona_context(persona, ResponseGoal.COMFORT, stage)
        assert all(rule.description in output.text for rule in persona.invariants)
    assert persona.model_dump_json() == before


def test_suppress_and_sensitive_evidence_cannot_reenter_through_relationship_context(
    service: CompanionMemoryService,
) -> None:
    model = evaluate_and_commit(service, "讨论技术时我更喜欢直接回答。")
    relations = RelationshipService(service)
    reference = RelationshipEvidenceRef.parse(model.patterns[0].evidence_ids[0])
    plan = MemoryUsePlan(
        decisions=[
            MemoryUseDecision(
                evidence=ExperienceEvidenceRef(kind=ExperienceEvidenceKind.TURN, id=reference.id),
                mode=MemoryReferenceMode.SUPPRESS,
            )
        ]
    )
    context = relations.get_relationship_context(
        KEY, ResponseGoal.DIRECT_ANSWER, "技术问题", memory_use_plan=plan
    )
    assert not context.relevant_patterns
    sensitive = f"turn:{turn(service, '敏感关系边界', sensitivity=Sensitivity.SENSITIVE)}"
    boundary = candidate_for(
        RelationshipUpdateKind.BOUNDARY,
        "敏感关系边界",
        [sensitive],
        {"id": "private", "description": "敏感关系边界"},
        datetime.now(UTC),
    )
    relations.commit_candidates(KEY, [boundary])
    assert (
        "敏感关系边界"
        not in relations.get_relationship_context(KEY, ResponseGoal.LISTEN, "我们").text
    )
    assert (
        "敏感关系边界"
        in relations.get_relationship_context(
            KEY, ResponseGoal.LISTEN, "我们", allow_sensitive=True
        ).text
    )


def test_deleted_evidence_invalidates_state_and_redacts_history(
    service: CompanionMemoryService,
) -> None:
    model = evaluate_and_commit(service, "我不喜欢空泛安慰。")
    relations = RelationshipService(service)
    reference = RelationshipEvidenceRef.parse(model.boundaries[0].evidence_ids[0])
    service.forget_turn(reference.id, "alice")
    model = relations.get_relationship(KEY)
    assert not model.boundaries
    assert not model.interactions
    assert all("空泛" not in revision.model_dump_json() for revision in relations.get_history(KEY))
    assert all(
        "空泛" not in candidate.model_dump_json() for candidate, _ in relations.get_candidates(KEY)
    )


def test_optimistic_revision_conflict_has_no_partial_update(
    service: CompanionMemoryService,
) -> None:
    relations = RelationshipService(service)
    model = evaluate_and_commit(service, "我们是朋友。")
    ref = f"turn:{turn(service)}"
    candidate = candidate_for(
        RelationshipUpdateKind.BOUNDARY,
        "新边界",
        [ref],
        {"id": "new", "description": "新边界"},
        datetime.now(UTC),
    )
    with pytest.raises(RelationshipConflictError):
        relations.commit_candidates(KEY, [candidate], expected_revision=model.revision - 1)
    assert relations.get_relationship(KEY) == model


def test_failed_model_does_not_commit_relationship_candidates(
    service: CompanionMemoryService,
) -> None:
    class Failure:
        def generate(self, messages: list[ChatMessage]) -> ModelResponse:
            raise MainLLMError("test failure")

    agent = CompanionAgent(service, load_persona(), Failure())
    with pytest.raises(MainLLMError):
        agent.chat(chat_request("我们是朋友。"))
    assert agent.relationships.get_relationship(KEY).revision == 0
    assert all(decision is None for _, decision in agent.relationships.get_candidates(KEY))
    agent.main_llm = StubLLM()
    agent.chat(chat_request("我们是朋友。"))
    assert agent.relationships.get_relationship(KEY).identity.labels == ["朋友"]


def test_concurrent_relationship_change_rolls_back_reply_and_use_ledger(
    service: CompanionMemoryService,
) -> None:
    agent = CompanionAgent(service, load_persona())
    ref = f"turn:{turn(service)}"

    class Concurrent:
        def generate(self, messages: list[ChatMessage]) -> ModelResponse:
            agent.relationships.commit_candidates(
                KEY,
                [
                    candidate_for(
                        RelationshipUpdateKind.BOUNDARY,
                        "生成期间新增边界",
                        [ref],
                        {"id": "new", "description": "新增边界"},
                        datetime.now(UTC),
                    )
                ],
            )
            return ModelResponse(text="应回滚的回复", model="stub")

    agent.main_llm = Concurrent()
    with pytest.raises(RelationshipConflictError):
        agent.chat(chat_request("现在的问题"))
    assert not any(t.role is ConversationRole.ASSISTANT for t in service.list_turns("alice", SCOPE))
    assert not service.store.list_memory_uses("alice")


def test_composer_rejects_cross_relationship_compiled_data() -> None:
    model = stage_fixture()
    compiled = compile_relationship_context(model, ResponseGoal.LISTEN, "hi")
    persona = compile_persona_context(load_persona(), ResponseGoal.LISTEN, RelationshipStage.NEW)
    with pytest.raises(ValueError, match="different owner"):
        compose_context(
            persona=persona,
            user_id="bob",
            scope=SCOPE,
            current_user_turn="hi",
            relationship_context=compiled,
        )


def test_relationship_delete_does_not_delete_memoryos_or_other_relationship(
    service: CompanionMemoryService,
) -> None:
    relations = RelationshipService(service)
    evaluate_and_commit(service, "我们是朋友。")
    other = RelationshipKey(user_id="bob", companion_id="xiaohe", relationship_id="r1")
    relations.get_relationship(other)
    relations.delete_relationship(KEY)
    assert relations.store.get(KEY) is None
    assert not relations.get_history(KEY)
    assert relations.store.get(other) is not None
    assert service.list_turns("alice", SCOPE)


def test_matching_pattern_with_different_candidate_id_merges(
    service: CompanionMemoryService,
) -> None:
    relations = RelationshipService(service)
    start = datetime.now(UTC) - timedelta(days=3)
    for index in range(3):
        at = start + timedelta(days=index)
        ref = f"turn:{turn(service, at=at)}"
        candidate = candidate_for(
            RelationshipUpdateKind.PATTERN,
            "同一互动模式",
            [ref],
            {
                "id": f"host-id-{index}",
                "description": "讨论技术时直接给结论",
                "category": "communication",
                "context_keys": ["技术"],
            },
            at,
            strength=EvidenceStrength.REPEATED,
            confidence=0.7,
        )
        model = relations.commit_candidates(KEY, [candidate])
    assert len(model.patterns) == 1
    assert model.patterns[0].id == "host-id-0" and model.patterns[0].observation_count == 3


def test_returning_turn_preserves_history_and_contracts_distance(
    service: CompanionMemoryService,
) -> None:
    start = datetime.now(UTC) - timedelta(days=150)
    refs = [f"turn:{turn(service, at=start + timedelta(days=i * 7))}" for i in range(14)]
    model = stage_fixture()
    model.started_at = start
    model.interactions = {ref: start + timedelta(days=i * 7) for i, ref in enumerate(refs)}
    model.last_interaction_at = max(model.interactions.values())
    model.identity.evidence_ids = [refs[0]]
    for pattern in model.patterns:
        pattern.evidence_ids = refs[:3]
        pattern.first_observed_at = start
        pattern.last_observed_at = start + timedelta(days=14)
    for index, milestone in enumerate(model.milestones):
        milestone.evidence_ids = [refs[index]]
    model.stage = RelationshipStage.CLOSE
    model.stage_state = RelationshipStageState(
        stage="close", entered_at=model.last_interaction_at, evidence_ids=refs
    )
    agent = CompanionAgent(service, load_persona(), StubLLM())
    agent.relationships.store.create(model)
    reply = agent.chat(chat_request("好久不见。"))
    assert reply.turn.metadata["familiarity_stage"] == "established"
    assert reply.turn.metadata["relationship_distance"] == "open"
    assert agent.relationships.get_relationship(KEY).stage is RelationshipStage.ESTABLISHED
    agent.chat(chat_request("今天过得怎么样？", "return-2"))
    assert agent.relationships.get_relationship(KEY).stage is RelationshipStage.ESTABLISHED


def test_pure_compiler_does_not_upgrade_suppress_or_clarify() -> None:
    model = stage_fixture()
    ref = model.milestones[0].evidence_ids[0]
    suppressed = compile_relationship_context(
        model,
        ResponseGoal.REFLECT,
        "我们的关系",
        evidence_modes={ref: MemoryReferenceMode.SUPPRESS},
    )
    assert len(suppressed.relevant_milestones) == 2
    assert ref not in suppressed.evidence_ids
    uncertain = compile_relationship_context(
        model, ResponseGoal.REFLECT, "我们的关系", evidence_modes={ref: MemoryReferenceMode.CLARIFY}
    )
    assert any("只能澄清" in item for item in uncertain.relevant_milestones)


def test_stage_transitions_are_persisted_with_evidence(service: CompanionMemoryService) -> None:
    relations = RelationshipService(service)
    start = datetime.now(UTC) - timedelta(days=80)
    refs = [f"turn:{turn(service, at=start + timedelta(days=i * 6))}" for i in range(14)]
    model = stage_fixture()
    model.started_at = start
    model.interactions = {ref: start + timedelta(days=i * 6) for i, ref in enumerate(refs)}
    model.last_interaction_at = max(model.interactions.values())
    model.identity.evidence_ids = [refs[0]]
    for pattern in model.patterns:
        pattern.evidence_ids = refs[:3]
    for index, milestone in enumerate(model.milestones):
        milestone.evidence_ids = [refs[index]]
    relations.store.create(model)
    assert relations.evaluate_stage(KEY).stage is RelationshipStage.FAMILIAR
    assert relations.evaluate_stage(KEY).stage is RelationshipStage.CLOSE
    history = relations.get_history(KEY)
    assert [item.change_type for item in history] == [RelationshipChangeType.STAGE_CHANGED] * 2
    assert all(item.evidence_ids and item.before and item.after for item in history)
