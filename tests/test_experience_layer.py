"""v0.3 semantics, sourced experience lifecycle, migration and runtime regression."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from companion_agent import CompanionAgent, FamiliarityStage, load_persona
from companion_agent.character_memory import CharacterMemoryStore
from companion_agent.context import ChatMessage
from companion_agent.experience import ExperienceService, ExperienceType
from companion_agent.experience.compiler import compile_experience_context
from companion_agent.experience.models import (
    ExperienceEvidenceKind,
    ExperienceStatus,
)
from companion_agent.llm import MainLLMError, ModelResponse
from companion_agent.persona.loader import loads_persona
from companion_agent.relationship import RelationshipKey, RelationshipService
from companion_agent.relationship.models import (
    RelationshipConfig,
    RelationshipIdentity,
    RelationshipModel,
    RelationshipPattern,
    RelationshipStageState,
)
from companion_agent.relationship.store import RelationshipStore
from companion_agent.relationship.transitions import evaluate_distance, evaluate_transition
from companion_agent.semantics import RelationshipDistance, RelationshipIdentityType
from companion_memoryos.schemas import (
    ConsentState,
    ConversationRole,
    ConversationTurnInput,
    EpisodeDetachRequest,
    MemoryReferenceMode,
    MemoryScope,
    MemoryUseDecision,
    MemoryUsePlan,
    ProcessTurnRequest,
    RealityLayer,
    Sensitivity,
    SpeechSpan,
)
from companion_memoryos.schemas import (
    ExperienceEvidenceKind as MemoryEvidenceKind,
)
from companion_memoryos.schemas import (
    ExperienceEvidenceRef as MemoryEvidenceRef,
)
from companion_memoryos.service import CompanionMemoryService

KEY = RelationshipKey(user_id="alice", companion_id="xiaohe", relationship_id="v3")
SCOPE = MemoryScope(companion_id="xiaohe", relationship_id="v3", conversation_id="chat")


class ModelStub:
    def __init__(self) -> None:
        self.inputs: list[list[ChatMessage]] = []

    def generate(self, messages: list[ChatMessage]) -> ModelResponse:
        self.inputs.append(messages)
        return ModelResponse(text="已记录的模型测试回应", model="local-stub")


def request(text: str, identifier: str = "one") -> ProcessTurnRequest:
    return ProcessTurnRequest(
        user_id="alice",
        scope=SCOPE,
        content=text,
        idempotency_key=identifier,
        consent=ConsentState.GRANTED,
        model_consent=ConsentState.GRANTED,
    )


def pair(
    service: CompanionMemoryService,
    text: str,
    at: datetime,
    *,
    scope: MemoryScope = SCOPE,
    **kwargs: Any,
) -> tuple[Any, Any]:
    user = service.append_turn(
        ConversationTurnInput(
            user_id="alice",
            scope=scope,
            actor_id="alice",
            role=ConversationRole.USER,
            content=text,
            consent=ConsentState.GRANTED,
            occurred_at=at,
            **kwargs,
        )
    )
    assert user.turn
    assistant = service.append_turn(
        ConversationTurnInput(
            user_id="alice",
            scope=scope,
            actor_id="xiaohe",
            role=ConversationRole.ASSISTANT,
            content="角色作出了一次真实回应",
            consent=ConsentState.GRANTED,
            occurred_at=at + timedelta(seconds=1),
            reply_to_turn_id=user.turn.id,
        )
    )
    assert assistant.turn
    return user.turn, assistant.turn


def employment(service: CompanionMemoryService) -> tuple[ExperienceService, Any]:
    experiences = ExperienceService(service)
    start = datetime.now(UTC) - timedelta(days=4)
    for day, message in enumerate(("我想辞职。", "老板又找我谈了。", "我决定再待一个月。")):
        experiences.observe(*pair(service, message, start + timedelta(days=day)))
    shared = [
        item for item in experiences.list_experiences(KEY) if item.type is ExperienceType.SHARED
    ]
    assert len(shared) == 1
    return experiences, shared[0]


@pytest.mark.parametrize("configured", [True, False])
def test_day_one_romantic_identity_does_not_fabricate_history(
    service: CompanionMemoryService, configured: bool
) -> None:
    model = ModelStub()
    agent = CompanionAgent(
        service,
        load_persona(),
        model,
        initial_relationship_identity=RelationshipIdentityType.ROMANTIC_PARTNER
        if configured
        else None,
    )
    reply = agent.chat(request("你好。" if configured else "你以后就是我女朋友。"))
    state = agent.relationships.get_relationship(KEY)
    assert state.identity.type is RelationshipIdentityType.ROMANTIC_PARTNER
    assert state.stage is FamiliarityStage.NEW
    assert state.identity.confirmed_by_user and state.identity.evidence_ids
    assert not state.shared_experiences and not state.milestones
    assert reply.turn.metadata["relationship_identity"] == "romantic_partner"
    assert "情侣称呼" in model.inputs[0][0].content
    assert '"familiarity_stage":"new"' in model.inputs[0][1].content
    assert "[RELATIONSHIP CONTEXT]" not in model.inputs[0][0].content
    assert not agent.experiences.list_experiences(KEY)


@pytest.mark.parametrize(
    "identity",
    [
        RelationshipIdentityType.FRIEND,
        RelationshipIdentityType.ROMANTIC_PARTNER,
        RelationshipIdentityType.COMPANION,
    ],
)
def test_identity_familiarity_and_distance_are_independent(
    identity: RelationshipIdentityType,
) -> None:
    start = datetime.now(UTC) - timedelta(days=80)
    model = RelationshipModel(
        **KEY.model_dump(),
        stage="close",
        stage_state=RelationshipStageState(stage="close", entered_at=start),
        identity=RelationshipIdentity(
            type=identity,
            labels=[identity.value],
            confirmed_by_user=True,
            confirmed_at=start,
            evidence_ids=["configuration:id"],
        ),
        distance_ceiling=FamiliarityStage.NEW,
        distance_evidence_ids=["turn:distance"],
    )
    assert (
        evaluate_transition(model, RelationshipConfig(), datetime.now(UTC)).stage
        is FamiliarityStage.ESTABLISHED
    )
    assert (
        evaluate_distance(model, RelationshipConfig(), datetime.now(UTC))
        is RelationshipDistance.RESERVED
    )
    assert model.identity.type is identity


def test_familiarity_does_not_require_milestone_or_identity() -> None:
    at = datetime.now(UTC)
    refs = {f"turn:{i}": at - timedelta(days=10 - i * 4) for i in range(3)}
    model = RelationshipModel(
        **KEY.model_dump(),
        interactions=refs,
        shared_experiences={"experience:a": at, "experience:b": at},
    )
    assert evaluate_transition(model, RelationshipConfig(), at).stage is FamiliarityStage.FAMILIAR
    model.shared_experiences = {}
    model.patterns = [
        RelationshipPattern(
            id="p",
            description="稳定偏好",
            category="communication",
            confidence=0.9,
            first_observed_at=min(refs.values()),
            last_observed_at=max(refs.values()),
            evidence_ids=list(refs),
            observation_count=3,
            status="established",
        )
    ]
    assert evaluate_transition(model, RelationshipConfig(), at).stage is FamiliarityStage.FAMILIAR
    model.interactions = {ref: at for ref in refs}
    model.started_at = at - timedelta(days=365)
    assert evaluate_transition(model, RelationshipConfig(), at).stage is FamiliarityStage.NEW


def test_multiday_experience_merges_closes_and_traces_evidence(
    service: CompanionMemoryService,
) -> None:
    experiences, shared = employment(service)
    assert shared.status is ExperienceStatus.CLOSED
    assert shared.ended_at and shared.ended_at > shared.started_at
    assert len(shared.facts) == 6
    assert "再待一个月" in shared.summary
    assert shared.participants == ["alice", "xiaohe"]
    assert len({fact.evidence_ref.episode_id for fact in shared.facts}) == 1
    assert experiences.trace(KEY, shared.experience_id) == shared.facts
    result = experiences.recall(KEY, "还记得我之前差点辞职那次吗？", explicit_recall=True)
    assert result[0].experience.experience_id == shared.experience_id
    assert result[0].use_mode is MemoryReferenceMode.EXPLICIT_RECALL
    assert len(result) == 1  # three correlated viewpoints must not be three occurrences
    context = compile_experience_context(KEY, result, service.token_counter)
    assert context.estimated_tokens <= 800 and "再待一个月" in context.text


def test_user_character_and_shared_views_preserve_subject_and_source(
    service: CompanionMemoryService,
) -> None:
    experiences, shared = employment(service)
    records = experiences.list_experiences(KEY)
    assert {item.type for item in records} == set(ExperienceType)
    for record in records:
        assert record.source == "lived"
        assert "阿灰" not in record.summary
    character = next(item for item in records if item.type is ExperienceType.CHARACTER)
    assert character.participants == ["xiaohe"] and "参与" in character.summary
    assert "我决定再待" not in character.summary
    user = next(item for item in records if item.type is ExperienceType.USER)
    assert user.participants == ["alice"]
    assert all(fact.actor_id == "alice" for fact in user.facts if not fact.is_assistant_action)
    assert shared.anchor_id == character.anchor_id == user.anchor_id


def test_first_pair_is_candidate_not_established_shared_experience(
    service: CompanionMemoryService,
) -> None:
    experiences = ExperienceService(service)
    decisions = experiences.observe(
        *pair(service, "我想辞职。", datetime.now(UTC) - timedelta(minutes=1))
    )
    assert decisions
    assert not any(item.type is ExperienceType.SHARED for item in experiences.list_experiences(KEY))
    assert any(
        item.type is ExperienceType.SHARED and item.status is ExperienceStatus.CANDIDATE
        for item in experiences.list_experiences(KEY, include_candidates=True)
    )


def test_episode_reingestion_is_idempotent(service: CompanionMemoryService) -> None:
    experiences, shared = employment(service)
    episode_id = shared.facts[0].evidence_ref.episode_id
    assert episode_id
    experiences.ingest_episode(KEY, episode_id)
    first = experiences.get(KEY, shared.experience_id)
    experiences.ingest_episode(KEY, episode_id)
    assert experiences.get(KEY, shared.experience_id).revision == first.revision


def test_important_experience_promotes_but_ordinary_experience_does_not(
    service: CompanionMemoryService,
) -> None:
    relations = RelationshipService(service)
    experiences, ordinary = employment(service)
    relations.commit_candidates(KEY, experiences.relationship_candidates(KEY))
    assert not relations.get_relationship(KEY).milestones
    start = datetime.now(UTC) - timedelta(days=1)
    experiences.observe(*pair(service, "这段讨论对我很重要。", start))
    # Explicit significance plus actual multiple-day discussion supports promotion.
    updated = experiences.get(KEY, ordinary.experience_id)
    assert updated.explicit_user_importance
    relations.commit_candidates(KEY, experiences.relationship_candidates(KEY))
    assert relations.get_relationship(KEY).milestones
    assert all(
        ref.startswith("experience:")
        for milestone in relations.get_relationship(KEY).milestones
        for ref in milestone.evidence_ids
    )


def test_sustained_emotional_experience_can_promote_without_magic_phrase(
    service: CompanionMemoryService,
) -> None:
    relations = RelationshipService(service)
    start = datetime.now(UTC) - timedelta(days=4)
    for index in range(6):
        at = start + timedelta(days=index // 2, minutes=index)
        relations.experiences.observe(*pair(service, "我最近压力很大，今天还是难过。", at))
    candidates = relations.experiences.relationship_candidates(KEY)
    state = relations.commit_candidates(KEY, candidates)
    assert state.milestones
    assert all(
        not item.explicit_user_importance for item in relations.experiences.list_experiences(KEY)
    )


def test_recall_question_does_not_create_new_experience(service: CompanionMemoryService) -> None:
    experiences, shared = employment(service)
    revision = shared.revision
    assert not experiences.observe(
        *pair(service, "还记得我差点辞职吗？", datetime.now(UTC) - timedelta(seconds=2))
    )
    assert experiences.get(KEY, shared.experience_id).revision == revision


def test_different_occurrence_does_not_merge_with_closed_history(
    service: CompanionMemoryService,
) -> None:
    experiences, shared = employment(service)
    start = datetime.now(UTC) - timedelta(hours=1)
    experiences.observe(*pair(service, "这次又想辞职了。", start))
    experiences.observe(*pair(service, "老板又找我谈了。", start + timedelta(minutes=5)))
    records = [
        item for item in experiences.list_experiences(KEY) if item.type is ExperienceType.SHARED
    ]
    assert len(records) == 2
    assert experiences.get(KEY, shared.experience_id).status is ExperienceStatus.CLOSED


def test_detach_invalidates_experience_and_downstream_relationship(
    service: CompanionMemoryService,
) -> None:
    experiences, shared = employment(service)
    relations = RelationshipService(service)
    relations.commit_candidates(KEY, experiences.relationship_candidates(KEY))
    fact = shared.facts[0]
    assert fact.evidence_ref.episode_id
    service.detach_episode_turn(
        fact.evidence_ref.episode_id,
        EpisodeDetachRequest(user_id="alice", scope=SCOPE, turn_id=fact.evidence_ref.id),
    )
    assert experiences.get(KEY, shared.experience_id).status is ExperienceStatus.SUPERSEDED
    assert not relations.get_relationship(KEY).shared_experiences
    assert not experiences.recall(KEY, "辞职")
    assert any(
        revision.get("redacted") for revision in experiences.history(KEY, shared.experience_id)
    )


def test_cross_owner_roleplay_quote_and_sensitive_sources(service: CompanionMemoryService) -> None:
    experiences, shared = employment(service)
    other = RelationshipKey(user_id="bob", companion_id="xiaohe", relationship_id="v3")
    assert not experiences.list_experiences(other)
    with pytest.raises(KeyError):
        experiences.get(other, shared.experience_id)
    at = datetime.now(UTC) - timedelta(minutes=10)
    text = "我想辞职"
    quoted = pair(
        service,
        text,
        at,
        speech_spans=[
            SpeechSpan(
                start_offset=0,
                end_offset=len(text),
                quote_depth=1,
                reality_layer=RealityLayer.QUOTE,
                machine_generated=False,
            )
        ],
    )
    assert not experiences.observe(*quoted)
    sensitive_scope = SCOPE.model_copy(update={"relationship_id": "sensitive"})
    sensitive_key = KEY.model_copy(update={"relationship_id": "sensitive"})
    for index in range(2):
        experiences.observe(
            *pair(
                service,
                text,
                at + timedelta(minutes=index + 1),
                scope=sensitive_scope,
                sensitivity=Sensitivity.SENSITIVE,
            )
        )
    assert not experiences.recall(sensitive_key, "辞职")
    assert experiences.recall(sensitive_key, "辞职", allow_sensitive=True)


@pytest.mark.parametrize(
    "mode",
    [
        MemoryReferenceMode.SUPPRESS,
        MemoryReferenceMode.SILENT_INFLUENCE,
        MemoryReferenceMode.CLARIFY,
    ],
)
def test_memory_use_restrictions_survive_experience_compression(
    service: CompanionMemoryService, mode: MemoryReferenceMode
) -> None:
    experiences, shared = employment(service)
    reference = shared.facts[0].evidence_ref
    plan = MemoryUsePlan(
        decisions=[
            MemoryUseDecision(
                evidence=MemoryEvidenceRef(kind=MemoryEvidenceKind.TURN, id=reference.id), mode=mode
            )
        ]
    )
    recalled = experiences.recall(KEY, "辞职", memory_use_plan=plan, explicit_recall=True)
    if mode is MemoryReferenceMode.SUPPRESS:
        assert not recalled
    else:
        assert recalled[0].use_mode is mode


def test_runtime_commits_experience_with_response_and_retry_is_idempotent(
    service: CompanionMemoryService,
) -> None:
    agent = CompanionAgent(service, load_persona(), ModelStub())
    agent.chat(request("我想辞职。"))
    reply = agent.chat(request("老板又找我谈了。", "two"))
    shared = [
        item
        for item in agent.experiences.list_experiences(KEY)
        if item.type is ExperienceType.SHARED
    ]
    assert len(shared) == 1
    assert reply.turn.metadata["experience_decisions"]
    before = shared[0].revision
    assert agent.chat(request("老板又找我谈了。", "two")).reused
    assert agent.experiences.get(KEY, shared[0].experience_id).revision == before
    prepared = agent.prepare(request("还记得我之前想辞职那次吗？", "three"))
    assert prepared.context.experiences and prepared.context.experiences.experience_ids
    assert "relevant_experiences" in prepared.context.messages[1].content


def test_model_failure_creates_no_lived_experience(service: CompanionMemoryService) -> None:
    class Failing:
        def generate(self, messages: list[ChatMessage]) -> ModelResponse:
            raise MainLLMError("failure")

    agent = CompanionAgent(service, load_persona(), Failing())
    with pytest.raises(MainLLMError):
        agent.chat(request("我想辞职。"))
    assert not agent.experiences.list_experiences(KEY, include_candidates=True)


def test_legacy_close_migration_preserves_revision_identity_and_snapshots(
    service: CompanionMemoryService,
) -> None:
    store = RelationshipStore(service.store.database)
    at = datetime.now(UTC) - timedelta(days=2)
    model = RelationshipModel(
        **KEY.model_dump(),
        stage="close",
        stage_state=RelationshipStageState(stage="close", entered_at=at),
        revision=7,
        identity=RelationshipIdentity(
            labels=["恋人"],
            romantic=True,
            confirmed_by_user=True,
            confirmed_at=at,
            evidence_ids=["turn:legacy"],
        ),
    )
    data = model.model_dump(mode="json")
    data["stage"] = data["stage_state"]["stage"] = "close"
    data["identity"].pop("type")
    data.pop("shared_experiences")
    revision = {
        "revision": 7,
        "created_at": at.isoformat(),
        "change_type": "stage_changed",
        "summary": "旧原因",
        "evidence_ids": ["turn:legacy"],
        "before": data,
        "after": data,
    }
    with service.store.database.atomic() as connection:
        connection.execute(
            "INSERT INTO agent_relationship_models VALUES(?,?,?,?,?)",
            (*KEY.values, 7, json.dumps(data)),
        )
        connection.execute(
            "INSERT INTO agent_relationship_revisions VALUES(?,?,?,?,?)",
            (*KEY.values, 7, json.dumps(revision)),
        )
        connection.execute(
            "UPDATE agent_schema_versions SET version=1 WHERE component='relationship'"
        )
    store.migrate()
    restored = store.get(KEY)
    assert restored and restored.stage is FamiliarityStage.ESTABLISHED and restored.revision == 7
    assert restored.identity.type is RelationshipIdentityType.ROMANTIC_PARTNER
    assert restored.stage_state.entered_at == at
    history = store.history(KEY)
    assert history[0].summary == "旧原因" and history[0].after["stage"] == "established"
    assert history[0].evidence_ids == ["turn:legacy"]
    store.migrate()
    assert store.get(KEY) == restored


def test_legacy_persona_hash_and_close_yaml_remain_compatible(
    service: CompanionMemoryService,
) -> None:
    import yaml

    data = load_persona().model_dump(mode="json")
    data.pop("identity_styles")
    data["relationship_styles"]["close"] = data["relationship_styles"].pop("established")
    data["version"] = "0.1.0"
    canonical = json.dumps(data, sort_keys=True, ensure_ascii=False)
    store = CharacterMemoryStore(service.store.database)
    with service.store.database.atomic() as connection:
        connection.execute(
            "INSERT INTO agent_persona_sources VALUES(?,?,?,?,?)",
            (
                "xiaohe",
                "xiaohe",
                "0.1.0",
                hashlib.sha256(canonical.encode()).hexdigest(),
                json.dumps(data["character_memories"]),
            ),
        )
    persona = loads_persona(yaml.safe_dump(data, allow_unicode=True))
    store.install(persona, "xiaohe")
    assert store.recall("xiaohe", "0.1.0", "xiaohe", "狗")


def test_experience_status_and_merge_revisions(service: CompanionMemoryService) -> None:
    experiences, original = employment(service)
    at = datetime.now(UTC) - timedelta(hours=2)
    experiences.observe(*pair(service, "这次又想辞职了。", at))
    experiences.observe(*pair(service, "老板又找我谈了。", at + timedelta(minutes=5)))
    newer = next(
        item
        for item in experiences.list_experiences(KEY)
        if item.type is ExperienceType.SHARED and item.experience_id != original.experience_id
    )
    merged = experiences.merge(
        KEY, original.experience_id, newer.experience_id, expected_revision=original.revision
    )
    assert len(merged.facts) == 10 and merged.status is ExperienceStatus.OPEN
    assert experiences.get(KEY, newer.experience_id).superseded_by == merged.experience_id
    closed = experiences.set_status(
        KEY,
        merged.experience_id,
        ExperienceStatus.CLOSED,
        expected_revision=merged.revision,
        evidence_refs=[merged.facts[-2].evidence_ref],
    )
    assert closed.status is ExperienceStatus.CLOSED and closed.revision > merged.revision
    assert len(experiences.recall(KEY, "辞职")) == 1


def test_temporal_recall_uses_memoryos_calendar_windows(service: CompanionMemoryService) -> None:
    experiences, shared = employment(service)
    assert not experiences.recall(KEY, "上个月辞职", explicit_recall=True)
    assert (
        experiences.recall(KEY, "本月辞职", explicit_recall=True)[0].experience.experience_id
        == shared.experience_id
    )


def test_observe_same_pair_twice_is_idempotent(service: CompanionMemoryService) -> None:
    experiences = ExperienceService(service)
    turns = pair(service, "我想辞职。", datetime.now(UTC) - timedelta(minutes=1))
    experiences.observe(*turns)
    before = {
        item.experience_id: item.revision
        for item in experiences.list_experiences(KEY, include_candidates=True)
    }
    experiences.observe(*turns)
    assert {
        item.experience_id: item.revision
        for item in experiences.list_experiences(KEY, include_candidates=True)
    } == before


def test_open_loop_resolution_closes_linked_experience(service: CompanionMemoryService) -> None:
    from companion_memoryos.schemas import (
        OpenLoopInput,
        OpenLoopKind,
        OpenLoopTransition,
        OpenLoopUpdateRequest,
    )

    experiences = ExperienceService(service)
    at = datetime.now(UTC) - timedelta(minutes=10)
    first = pair(service, "我想辞职。", at)
    loop = service.create_open_loop(
        OpenLoopInput(
            user_id="alice",
            scope=SCOPE,
            kind=OpenLoopKind.EVENT_OUTCOME,
            summary="换工作的决定",
            source_turn_id=first[0].id,
            consent=ConsentState.GRANTED,
        )
    )
    assert loop.open_loop
    experiences.observe(*first)
    second = pair(service, "老板又找我谈了。", at + timedelta(minutes=1))
    service.update_open_loop(
        loop.open_loop.id,
        OpenLoopUpdateRequest(
            user_id="alice",
            transition=OpenLoopTransition.RESOLVE,
            source_turn_id=second[0].id,
            resolution_summary="宿主确认事项已结束",
        ),
    )
    experiences.observe(*second)
    shared = next(
        item for item in experiences.list_experiences(KEY) if item.type is ExperienceType.SHARED
    )
    assert shared.status is ExperienceStatus.CLOSED
    assert any(ref.kind is ExperienceEvidenceKind.OPEN_LOOP for ref in shared.evidence_refs)
    assert all(fact.evidence_ref.episode_id for fact in shared.facts)
