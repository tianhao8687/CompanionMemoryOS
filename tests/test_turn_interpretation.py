import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from typer.testing import CliRunner

from companion_memoryos.api import create_app
from companion_memoryos.cli import app
from companion_memoryos.schemas import (
    AutomaticActionStatus,
    ConsentState,
    ConversationRole,
    ConversationTurnInput,
    DiscourseSignal,
    EpisodeAttachRequest,
    EpisodeHint,
    EpisodeInput,
    EpisodeMergeRequest,
    EpisodeSplitRequest,
    EpisodeStatus,
    EpistemicKind,
    FollowUpMode,
    MemoryCandidate,
    MemoryKind,
    MemoryScope,
    MemoryStatus,
    OpenLoopCandidate,
    OpenLoopKind,
    ResolutionStatus,
    SpeechSpanProposal,
    StateClaim,
    StateQuery,
    TurnInterpretation,
    TurnInterpretationRequest,
)
from companion_memoryos.service import CompanionMemoryService

SCOPE = MemoryScope(companion_id="ai", relationship_id="relationship", conversation_id="chat")


def turn(service: CompanionMemoryService, text: str, *, day: int = 0):
    request = ConversationTurnInput(
        user_id="user",
        actor_id="user",
        scope=SCOPE,
        role=ConversationRole.USER,
        content=text,
        consent=ConsentState.GRANTED,
        occurred_at=datetime.now(UTC) - timedelta(days=day),
        idempotency_key=f"delivery:{text}",
    )
    stored = service.append_turn(request).turn
    assert stored is not None
    return request, stored


def proposal(**fields: object) -> TurnInterpretationRequest:
    return TurnInterpretationRequest(
        user_id="user",
        scope=SCOPE,
        model_fingerprint="fixture-model-0.7",
        idempotency_key="interpret-v1",
        model_output=TurnInterpretation.model_validate(fields),
    )


def test_interpretation_is_candidate_only_atomic_and_idempotent(
    service: CompanionMemoryService,
) -> None:
    original, stored = turn(service, "记住，小王喜欢咖啡，我下周要问问他的面试结果。")
    request = proposal(
        topics=["咖啡", "面试"],
        speech_spans=[
            SpeechSpanProposal(
                start_offset=0, end_offset=len(stored.content), attributed_speaker_id="user"
            )
        ],
        state_claims=[
            StateClaim(
                title="小王的喜好",
                content="小王喜欢咖啡",
                predicate="likes_coffee",
                subject_actor_id="wang",
                epistemic_kind=EpistemicKind.DIRECT_SELF_REPORT,
                evidence_span_indices=[0],
            )
        ],
        open_loop_candidates=[
            OpenLoopCandidate(
                kind=OpenLoopKind.USER_COMMITMENT, summary="询问小王面试结果", topic_keys=["面试"]
            )
        ],
    )
    first = service.apply_turn_interpretation(stored.id, request)
    assert service.apply_turn_interpretation(stored.id, request) == first
    assert len(service.list_memories("user")) == 1
    memory = service.store.get(first.memory_ids[0], "user")
    assert memory.status is MemoryStatus.CANDIDATE
    assert memory.subject_actor_id == "wang"
    assert memory.epistemic_kind is EpistemicKind.OBSERVATION
    assert memory.evidence_turn_ids == [stored.id]
    assert (
        service.query_state(
            StateQuery(user_id="user", scope=SCOPE, predicate="likes_coffee")
        ).resolution_status
        is ResolutionStatus.UNKNOWN
    )
    current = service.store.get_turn(stored.id, "user")
    assert current.content == original.content
    assert current.speech_spans == original.speech_spans
    assert current.content_hash == stored.content_hash
    assert "面试" in current.retrieval_keys
    assert service.append_turn(original).duplicate_of == stored.id
    loop = service.list_open_loops("user")[0]
    assert loop.follow_up_mode is FollowUpMode.USER_LED
    assert loop.source_turn_id == stored.id
    with pytest.raises(ValueError, match="already interpreted"):
        service.apply_turn_interpretation(
            stored.id, request.model_copy(update={"idempotency_key": "changed"})
        )


def test_invalid_span_or_candidate_rolls_back_all_derived_writes(
    service: CompanionMemoryService,
) -> None:
    _, stored = turn(service, "我面试完了")
    request = proposal(
        episode_hint=EpisodeHint(action="new", title="面试"),
        memory_candidates=[
            MemoryCandidate(
                kind=MemoryKind.SHARED_MOMENT,
                title="面试",
                content="面试完了",
                evidence_span_indices=[1],
            )
        ],
    )
    with pytest.raises(ValueError, match="unknown speech span"):
        service.apply_turn_interpretation(stored.id, request)
    assert service.list_episodes("user") == []
    assert service.list_memories("user") == []
    assert service.get_turn_interpretation(stored.id, "user") is None
    assert service.store.get_turn(stored.id, "user").content == stored.content
    too_long = proposal(
        speech_spans=[SpeechSpanProposal(start_offset=0, end_offset=len(stored.content) + 1)]
    )
    with pytest.raises(ValueError, match="exceeds original"):
        service.apply_turn_interpretation(stored.id, too_long)


def test_storage_failure_rolls_back_episode_and_earlier_candidates(
    service: CompanionMemoryService,
) -> None:
    _, stored = turn(service, "面试完了，回来喝了杯茶")
    with service.store.database.connection() as connection:
        connection.execute(
            "CREATE TRIGGER fixture_failure BEFORE INSERT ON memories "
            "WHEN new.title = 'fail' BEGIN SELECT RAISE(ABORT, 'fixture rejection'); END"
        )
    request = proposal(
        episode_hint=EpisodeHint(action="new", title="面试之后"),
        memory_candidates=[
            MemoryCandidate(kind=MemoryKind.SHARED_MOMENT, title="first", content="面试完成"),
            MemoryCandidate(kind=MemoryKind.SHARED_MOMENT, title="fail", content="喝了杯茶"),
        ],
    )
    with pytest.raises(sqlite3.IntegrityError, match="fixture rejection"):
        service.apply_turn_interpretation(stored.id, request)
    assert service.list_memories("user") == []
    assert service.list_episodes("user") == []
    assert service.get_turn_interpretation(stored.id, "user") is None
    assert service.store.get_turn(stored.id, "user").episode_id is None
    assert service.store.get_turn(stored.id, "user").content == stored.content


def test_episode_gap_comes_from_host_request_not_hidden_threshold(
    service: CompanionMemoryService,
) -> None:
    _, earlier = turn(service, "面试完了", day=2)
    record = service.apply_turn_interpretation(
        earlier.id,
        proposal(topics=["面试"], episode_hint=EpisodeHint(action="new", title="面试")),
    )
    _, later = turn(service, "公司给我打电话了")
    request = proposal(
        topics=["面试"],
        episode_hint=EpisodeHint(
            action="attach", episode_id=record.episode_id, continuity_turn_id=earlier.id
        ),
    )
    with pytest.raises(ValueError, match="host-declared time window"):
        service.apply_turn_interpretation(
            later.id, request.model_copy(update={"episode_max_gap_seconds": 1.0})
        )
    accepted = service.apply_turn_interpretation(later.id, request)
    assert accepted.episode_id == record.episode_id
    assert accepted.episode_max_gap_seconds is None


def test_plain_disagreement_uses_model_but_explicit_rules_win(
    service: CompanionMemoryService,
) -> None:
    _, stored = turn(service, "你怎么又把他们两个搞混了")
    interpreted = service.apply_turn_interpretation(
        stored.id, proposal(discourse_signals=[DiscourseSignal.WRONG_REFERENCE])
    )
    assert interpreted.discourse is not None
    assert interpreted.discourse.signals == [DiscourseSignal.WRONG_REFERENCE]
    assert interpreted.discourse.automatic_action_status is AutomaticActionStatus.NEEDS_TARGET
    _, direct = turn(service, "先听我说，别给建议")
    result = service.apply_turn_interpretation(
        direct.id, proposal(discourse_signals=[DiscourseSignal.ADVICE_REQUESTED])
    )
    assert result.discourse is not None
    assert DiscourseSignal.LISTEN_ONLY in result.discourse.signals
    assert DiscourseSignal.ADVICE_REQUESTED not in result.discourse.signals


def test_interview_phone_rejection_share_episode_then_can_split_and_merge(
    service: CompanionMemoryService,
) -> None:
    originals = [
        turn(service, text, day=day)
        for text, day in [
            ("我面试完了", 2),
            ("昨天那家公司给我打电话了", 1),
            ("他们最后还是拒了我", 0),
        ]
    ]
    first = service.apply_turn_interpretation(
        originals[0][1].id,
        proposal(
            topics=["面试"],
            episode_hint=EpisodeHint(
                action="new", title="第一次面试", participant_actor_ids=["company-a"]
            ),
        ),
    )
    assert first.episode_id is not None
    for index in [1, 2]:
        service.apply_turn_interpretation(
            originals[index][1].id,
            proposal(
                topics=["面试"],
                episode_hint=EpisodeHint(
                    action="attach",
                    episode_id=first.episode_id,
                    continuity_turn_id=originals[index - 1][1].id,
                    participant_actor_ids=["company-a"],
                ),
            ),
        )
    assert len(service.episode_turns(first.episode_id, "user", SCOPE)) == 3
    created = service.split_episode(
        first.episode_id,
        EpisodeSplitRequest(
            user_id="user", scope=SCOPE, turn_ids=[originals[2][1].id], title="另一家公司的拒信"
        ),
    )
    assert len(service.episode_turns(created.id, "user", SCOPE)) == 1
    merged = service.merge_episodes(
        first.episode_id,
        EpisodeMergeRequest(user_id="user", scope=SCOPE, source_episode_id=created.id),
    )
    assert merged.summary == ""
    assert len(service.episode_turns(first.episode_id, "user", SCOPE)) == 3
    assert (
        next(item for item in service.list_episodes("user") if item.id == created.id).status
        is EpisodeStatus.MERGED
    )
    for original, stored in originals:
        assert service.store.get_turn(stored.id, "user").content == original.content
        assert service.append_turn(original).duplicate_of == stored.id


def test_episode_reassign_requires_current_membership_and_scope(
    service: CompanionMemoryService,
) -> None:
    _, stored = turn(service, "今天去面试")
    first = service.create_episode(EpisodeInput(user_id="user", scope=SCOPE, title="第一家"))
    second = service.create_episode(EpisodeInput(user_id="user", scope=SCOPE, title="第二家"))
    service.attach_episode_turn(
        first.id, EpisodeAttachRequest(user_id="user", scope=SCOPE, turn_id=stored.id)
    )
    with pytest.raises(ValueError, match="membership changed"):
        service.attach_episode_turn(
            second.id, EpisodeAttachRequest(user_id="user", scope=SCOPE, turn_id=stored.id)
        )
    service.attach_episode_turn(
        second.id,
        EpisodeAttachRequest(
            user_id="user", scope=SCOPE, turn_id=stored.id, expected_episode_id=first.id
        ),
    )
    assert service.episode_turns(first.id, "user", SCOPE) == []
    assert service.episode_turns(second.id, "user", SCOPE)[0].id == stored.id


def test_bad_episode_continuity_keeps_raw_but_no_partial_interpretation(
    service: CompanionMemoryService,
) -> None:
    _, stored = turn(service, "面试完了", day=1)
    first = service.apply_turn_interpretation(
        stored.id,
        proposal(
            topics=["面试"],
            episode_hint=EpisodeHint(action="new", title="面试", participant_actor_ids=["a"]),
        ),
    )
    _, later = turn(service, "今天体检了")
    with pytest.raises(ValueError, match="shared topic"):
        service.apply_turn_interpretation(
            later.id,
            proposal(
                topics=["体检"],
                episode_hint=EpisodeHint(
                    action="attach",
                    episode_id=first.episode_id,
                    continuity_turn_id=stored.id,
                    participant_actor_ids=["a"],
                ),
            ),
        )
    assert service.store.get_turn(later.id, "user").episode_id is None
    assert service.get_turn_interpretation(later.id, "user") is None


def test_forgetting_source_invalidates_interpretation(service: CompanionMemoryService) -> None:
    _, stored = turn(service, "我喜欢那只蓝杯")
    record = service.apply_turn_interpretation(
        stored.id,
        proposal(
            topics=["蓝杯"],
            memory_candidates=[
                MemoryCandidate(kind=MemoryKind.SHARED_MOMENT, title="蓝杯", content="喜欢蓝杯")
            ],
        ),
    )
    service.forget_turn(stored.id, "user")
    assert service.get_turn_interpretation(stored.id, "user") is None
    assert service.store.get(record.memory_ids[0], "user").status is MemoryStatus.FORGOTTEN
    assert service.export("user").turn_interpretations == []


def test_interpretation_envelope_is_not_a_model_field() -> None:
    with pytest.raises(ValidationError):
        proposal(user_id="other")
    with pytest.raises(ValidationError):
        proposal(
            state_claims=[{"title": "咖啡", "content": "小王喜欢咖啡", "predicate": "likes_coffee"}]
        )


def test_api_and_cli_interpretation_entry_points(tmp_path: Path) -> None:
    api = create_app(tmp_path)
    client = TestClient(api)
    headers = {"Authorization": f"Bearer {api.state.tokens.get_or_create()}"}
    request = ConversationTurnInput(
        user_id="user",
        actor_id="user",
        scope=SCOPE,
        role=ConversationRole.USER,
        consent=ConsentState.GRANTED,
        content="我刚买了一束向日葵",
    )
    response = client.post("/api/v1/turns", headers=headers, json=request.model_dump(mode="json"))
    assert response.status_code == 200
    turn_id = response.json()["turn"]["id"]
    data = proposal(topics=["向日葵"])
    response = client.post(
        f"/api/v1/turns/{turn_id}/interpretation",
        headers=headers,
        json=data.model_dump(mode="json"),
    )
    assert response.status_code == 200
    assert (
        client.get(
            f"/api/v1/turns/{turn_id}/interpretation", headers=headers, params={"user_id": "user"}
        ).json()["id"]
        == response.json()["id"]
    )
    path = tmp_path / "interpretation.json"
    path.write_text(data.model_dump_json(), encoding="utf-8")
    result = CliRunner().invoke(
        app, ["--data-dir", str(tmp_path), "apply-interpretation", turn_id, str(path)]
    )
    assert result.exit_code == 0, result.output
