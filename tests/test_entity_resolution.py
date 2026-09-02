import hashlib
from datetime import UTC, datetime, timedelta

import pytest

from companion_memoryos.entity_resolution import entity_catalog
from companion_memoryos.interpretation_service import interpretation_request_hash
from companion_memoryos.schemas import (
    ConversationTurnInput,
    EntityProposal,
    EpisodeAttachRequest,
    EpisodeDetachRequest,
    EpisodeHint,
    EpisodeInput,
    EpisodeStatus,
    InterpreterContext,
    InterpreterOutput,
    MemoryKind,
    MemoryScope,
    ProcessTurnRequest,
    RealityLayer,
    StateClaim,
    TurnInterpretation,
    TurnInterpretationRequest,
)
from companion_memoryos.service import CompanionMemoryService

SCOPE = MemoryScope(companion_id="ai", relationship_id="rel", conversation_id="chat")


def apply(service, text, entities, *, claims=None, layer=RealityLayer.REAL_WORLD, key=None):
    turn = service.append_turn(
        ConversationTurnInput(
            user_id="user",
            scope=SCOPE,
            actor_id="user",
            role="user",
            content=text,
            consent="granted",
            idempotency_key=key,
        )
    ).turn
    result = service.apply_turn_interpretation(
        turn.id,
        TurnInterpretationRequest(
            user_id="user",
            scope=SCOPE,
            model_fingerprint="fixture-entities",
            idempotency_key=f"entity:{turn.id}",
            model_output=TurnInterpretation(
                entities=entities,
                state_claims=claims or [],
            ),
        ),
    )
    return turn, result


def test_observed_cat_alias_resolves_same_actor_without_copying_original_raw(service) -> None:
    first_turn, first = apply(
        service,
        "团子是我的猫，我也叫它小团",
        [EntityProposal(ref="cat", name="团子", kind="PET", aliases=["小团", "从未说过的绰号"])],
    )
    first_entity = first.entity_resolutions[0].entity
    assert first_entity.kind == "pet" and first_entity.aliases == ["小团"]
    second_turn, second = apply(
        service,
        "小团今天在窗边睡觉",
        [
            EntityProposal(ref="cat", name="小团", kind="pet"),
        ],
        claims=[
            StateClaim(
                title="猫的习惯",
                content="小团今天在窗边睡觉",
                kind=MemoryKind.SHARED_MOMENT,
                subject_actor_id="cat",
                predicate="resting_place",
                entity_refs=["cat"],
            )
        ],
    )
    resolved = second.entity_resolutions[0]
    assert resolved.status == "matched" and resolved.entity.id == first_entity.id
    candidate = service.store.get(second.memory_ids[0], "user")
    assert candidate.subject_actor_id == first_entity.id
    assert candidate.entities[0].id == first_entity.id
    assert candidate.evidence_turn_ids == [second_turn.id]
    assert service.store.get_turn(first_turn.id, "user").content_hash == first_turn.content_hash
    assert "小团" in service.store.get_turn(second_turn.id, "user").retrieval_keys


def test_two_people_with_same_name_defer_state_without_asking_or_auto_merging(service) -> None:
    _, first = apply(service, "同事小王来了", [EntityProposal(ref="wang", name="小王")])
    _, second = apply(
        service,
        "这是另一个小王，是我的同学",
        [EntityProposal(ref="wang", name="小王", action="new")],
    )
    assert first.entity_resolutions[0].entity.id != second.entity_resolutions[0].entity.id
    turn, ambiguous = apply(
        service,
        "小王喜欢咖啡",
        [EntityProposal(ref="wang", name="小王")],
        claims=[
            StateClaim(
                title="喜好",
                content="小王喜欢咖啡",
                subject_actor_id="wang",
                predicate="likes_coffee",
                entity_refs=["wang"],
            )
        ],
    )
    assert ambiguous.entity_resolutions[0].status == "ambiguous"
    assert len(ambiguous.entity_resolutions[0].candidate_ids) == 2
    assert ambiguous.memory_ids == []
    assert service.store.get_turn(turn.id, "user").content == "小王喜欢咖啡"


def test_proposal_cannot_invent_alias_or_overwrite_user_identity(service) -> None:
    _, result = apply(
        service,
        "今天有点累",
        [EntityProposal(ref="someone", name="不存在的人")],
        claims=[
            StateClaim(
                title="喜好", content="他喜欢咖啡", subject_actor_id="someone", predicate="likes"
            )
        ],
    )
    assert result.entity_resolutions[0].status == "unanchored"
    assert result.memory_ids == []
    with pytest.raises(ValueError, match="authenticated actor"):
        apply(service, "我叫小王", [EntityProposal(ref="user", name="小王")])


def test_deleted_alias_root_is_not_restored_by_a_later_observed_nickname(service) -> None:
    root, _ = apply(
        service,
        "团子也叫小团",
        [EntityProposal(ref="cat", name="团子", aliases=["小团"], kind="pet")],
    )
    _, second = apply(service, "小团睡着了", [EntityProposal(ref="cat", name="小团", kind="pet")])
    identity = second.entity_resolutions[0].entity.id
    service.forget_turn(root.id, "user")
    old_name, _ = entity_catalog(
        service.store, "user", SCOPE, RealityLayer.REAL_WORLD, datetime.now(UTC), 24, names=["团子"]
    )
    current_name, _ = entity_catalog(
        service.store, "user", SCOPE, RealityLayer.REAL_WORLD, datetime.now(UTC), 24, names=["小团"]
    )
    assert old_name == []
    assert [entity.id for entity in current_name] == [identity]


def test_entity_lookup_does_not_cross_relationship_or_reality(service) -> None:
    _, result = apply(service, "小王是同事", [EntityProposal(ref="wang", name="小王")])
    assert result.entity_resolutions[0].entity is not None
    for scope, realm in [
        (SCOPE.model_copy(update={"relationship_id": "other"}), RealityLayer.REAL_WORLD),
        (SCOPE, RealityLayer.ROLEPLAY),
    ]:
        found, _ = entity_catalog(
            service.store, "user", scope, realm, datetime.now(UTC), 24, names=["小王"]
        )
        assert found == []


def test_075_additive_fields_preserve_074_interpretation_hash_and_retry(service) -> None:
    turn = service.append_turn(
        ConversationTurnInput(
            user_id="user",
            scope=SCOPE,
            actor_id="user",
            role="user",
            content="我喜欢雨天",
            consent="granted",
        )
    ).turn
    request = TurnInterpretationRequest(
        user_id="user",
        scope=SCOPE,
        idempotency_key="old-version",
        model_fingerprint="0.7.4",
        model_output=TurnInterpretation(
            state_claims=[
                StateClaim(
                    title="天气", content="喜欢雨天", subject_actor_id="user", predicate="likes"
                )
            ]
        ),
    )
    old_json = request.model_dump_json(
        exclude={
            "processing_metadata": True,
            "model_output": {
                "entities": True,
                "state_claims": {"__all__": {"entity_refs"}},
                "memory_candidates": {"__all__": {"entity_refs"}},
            },
        }
    )
    old_digest = hashlib.sha256(old_json.encode("utf-8")).hexdigest()
    assert interpretation_request_hash(request) == old_digest
    record = service.apply_turn_interpretation(turn.id, request)
    with service.store.database.connection() as connection:
        connection.execute(
            "UPDATE turn_interpretations SET request_hash = ? WHERE id = ?", (old_digest, record.id)
        )
    assert service.apply_turn_interpretation(turn.id, request).id == record.id


def test_cross_day_episode_uses_context_ids_and_reversible_detach(service) -> None:
    class InterviewInterpreter:
        def interpret(self, context: InterpreterContext) -> InterpreterOutput:
            hint = (
                EpisodeHint(
                    action="attach",
                    episode_id=context.episodes[0].id,
                    continuity_turn_id=context.episodes[0].continuity_turn_id,
                    participant_actor_ids=["user"],
                )
                if context.episodes
                else EpisodeHint(
                    action="new", title="那家公司的面试", participant_actor_ids=["user"]
                )
            )
            return InterpreterOutput(
                interpretation=TurnInterpretation(topics=["面试"], episode_hint=hint),
                model_fingerprint="scripted-interview",
            )

    memory = CompanionMemoryService(
        service.store, service.config, turn_interpreter=InterviewInterpreter()
    )
    time = datetime.now(UTC) - timedelta(days=4)
    results = []
    for day, text in enumerate(["我面试完了", "昨天那家公司给我打电话了", "他们最后还是拒了我"]):
        # A different conversation per day, same relationship consent domain.
        results.append(
            memory.process_turn(
                ProcessTurnRequest(
                    user_id="user",
                    scope=SCOPE.model_copy(update={"conversation_id": f"day-{day}"}),
                    content=text,
                    idempotency_key=f"day-{day}",
                    occurred_at=time + timedelta(days=day),
                    consent="granted",
                    model_consent="granted",
                    enable_recall=False,
                )
            )
        )
    assert all(result.interpretation_status == "completed" for result in results)
    episode_id = results[0].interpretation.episode_id
    assert {result.interpretation.episode_id for result in results} == {episode_id}
    relationship = SCOPE.model_copy(update={"conversation_id": None})
    episode = memory.list_episodes("user", relationship)[0]
    assert len(memory.episode_turns(episode_id, "user", relationship)) == 3
    turn = results[-1].storage.turn
    detached = memory.detach_episode_turn(
        episode_id,
        EpisodeDetachRequest(
            user_id="user",
            scope=relationship,
            turn_id=turn.id,
            expected_revision=episode.revision,
        ),
    )
    assert detached.revision > episode.revision and detached.last_event_at < episode.last_event_at
    assert memory.store.get_turn(turn.id, "user").episode_id is None
    assert memory.store.get_turn(turn.id, "user").content_hash == turn.content_hash
    with pytest.raises(ValueError, match="revision"):
        memory.detach_episode_turn(
            episode_id,
            EpisodeDetachRequest(
                user_id="user",
                scope=relationship,
                turn_id=results[0].storage.turn.id,
                expected_revision=episode.revision,
            ),
        )


def test_detach_last_turn_empties_episode_and_rejects_wrong_scope(service) -> None:
    turn = service.append_turn(
        ConversationTurnInput(
            user_id="user",
            scope=SCOPE,
            actor_id="user",
            role="user",
            content="面试",
            consent="granted",
        )
    ).turn
    episode = service.create_episode(EpisodeInput(user_id="user", scope=SCOPE, title="面试"))
    service.attach_episode_turn(
        episode.id, EpisodeAttachRequest(user_id="user", scope=SCOPE, turn_id=turn.id)
    )
    with pytest.raises(ValueError):
        service.detach_episode_turn(
            episode.id,
            EpisodeDetachRequest(
                user_id="user",
                scope=SCOPE.model_copy(update={"companion_id": "other"}),
                turn_id=turn.id,
            ),
        )
    result = service.detach_episode_turn(
        episode.id,
        EpisodeDetachRequest(
            user_id="user",
            scope=SCOPE,
            turn_id=turn.id,
        ),
    )
    assert result.status is EpisodeStatus.EMPTY
