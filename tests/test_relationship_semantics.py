from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from companion_memoryos.schemas import (
    AnswerSemantics,
    ConsentState,
    ConversationRole,
    ConversationTurnInput,
    EpistemicKind,
    EvidenceActor,
    MemoryInput,
    MemoryKind,
    MemoryScope,
    MemoryStatus,
    RecallRequest,
    ResolutionStatus,
    StateQuery,
)
from companion_memoryos.service import CompanionMemoryService
from companion_memoryos.temporal import extract_temporal_hint

SCOPE = MemoryScope(
    companion_id="companion-a", relationship_id="relationship-a", conversation_id="chat"
)


def test_state_subjects_do_not_query_or_supersede_each_other(
    service: CompanionMemoryService,
) -> None:
    records = {}
    for subject, color in [
        (None, "蓝色"),
        ("companion-a", "红色"),
        ("wang", "绿色"),
        ("li", "黄色"),
    ]:
        result = service.remember(
            MemoryInput(
                user_id="user",
                scope=SCOPE,
                subject_actor_id=subject,
                kind=MemoryKind.PREFERENCE,
                title="颜色",
                content=f"{subject or 'user'}喜欢{color}",
                predicate="likes_color",
                stable_key="same-host-key",
                consent=ConsentState.GRANTED,
                explicit_user_request=True,
            )
        )
        assert result.memory is not None
        records[subject or "user"] = result.memory
    for subject, record in records.items():
        result = service.query_state(
            StateQuery(
                user_id="user", scope=SCOPE, predicate="likes_color", subject_actor_id=subject
            )
        )
        assert [memory.id for memory in result.memories] == [record.id]
        assert service.store.get(record.id, "user").status is MemoryStatus.ACTIVE
    default = service.query_state(StateQuery(user_id="user", scope=SCOPE, predicate="likes_color"))
    assert [memory.id for memory in default.memories] == [records["user"].id]
    assert [memory.id for memory in service.profile("user", SCOPE).preferences] == [
        records["user"].id
    ]
    context = service.recall(
        RecallRequest(
            user_id="user",
            scope=SCOPE,
            query="你喜欢什么颜色？",
            state_predicate="likes_color",
            state_subject_actor_id="companion-a",
            answer_semantics=AnswerSemantics.STATE_AT_VALID_TIME,
        )
    )
    assert context.state_result is not None
    assert [memory.id for memory in context.state_result.memories] == [records["companion-a"].id]
    assert records["companion-a"].content in context.prompt_text
    assert records["wang"].content not in context.prompt_text


@pytest.mark.parametrize(
    "subject,text,expected",
    [
        (None, "记住，我喜欢咖啡。", EpistemicKind.DIRECT_SELF_REPORT),
        ("user", "记住，我喜欢咖啡。", EpistemicKind.DIRECT_SELF_REPORT),
        ("wang", "记住，小王喜欢咖啡。", EpistemicKind.OBSERVATION),
        ("companion-a", "记住，你喜欢咖啡。", EpistemicKind.OBSERVATION),
    ],
)
def test_only_user_subject_becomes_direct_self_report(
    service: CompanionMemoryService, subject: str | None, text: str, expected: EpistemicKind
) -> None:
    result = service.remember(
        MemoryInput(
            user_id="user",
            scope=SCOPE,
            subject_actor_id=subject,
            kind=MemoryKind.PREFERENCE,
            title="咖啡",
            content=text,
            predicate="likes_coffee",
            consent=ConsentState.GRANTED,
        )
    )
    assert result.memory is not None
    assert result.memory.epistemic_kind is expected
    assert result.memory.subject_actor_id == subject


def test_explicit_wrong_subject_self_report_is_not_qualified(
    service: CompanionMemoryService,
) -> None:
    result = service.remember(
        MemoryInput(
            user_id="user",
            scope=SCOPE,
            subject_actor_id="wang",
            predicate="likes_coffee",
            kind=MemoryKind.PREFERENCE,
            title="小王",
            content="小王说他喜欢咖啡",
            epistemic_kind=EpistemicKind.DIRECT_SELF_REPORT,
            source_actor=EvidenceActor.AUTHENTICATED_USER,
            consent=ConsentState.GRANTED,
            explicit_user_request=True,
        )
    )
    assert result.memory is not None
    assert result.memory.epistemic_kind is EpistemicKind.OBSERVATION
    assert result.memory.status is MemoryStatus.CANDIDATE
    assert (
        service.query_state(
            StateQuery(user_id="user", scope=SCOPE, predicate="likes_coffee")
        ).resolution_status
        is ResolutionStatus.UNKNOWN
    )


@pytest.mark.parametrize(
    "zone,now,query,start,end",
    [
        (
            "Asia/Singapore",
            "2026-09-01T17:00:00+00:00",
            "今天聊了什么",
            "2026-09-01T16:00:00+00:00",
            "2026-09-02T16:00:00+00:00",
        ),
        (
            "America/Los_Angeles",
            "2026-09-02T08:00:00+00:00",
            "昨天聊了什么",
            "2026-09-01T07:00:00+00:00",
            "2026-09-02T07:00:00+00:00",
        ),
        (
            "UTC",
            "2026-09-02T01:00:00+00:00",
            "今天聊了什么",
            "2026-09-02T00:00:00+00:00",
            "2026-09-03T00:00:00+00:00",
        ),
        (
            "America/Los_Angeles",
            "2026-03-09T08:00:00+00:00",
            "昨天聊了什么",
            "2026-03-08T08:00:00+00:00",
            "2026-03-09T07:00:00+00:00",
        ),
    ],
)
def test_relative_calendar_dates_use_local_midnight(
    zone: str, now: str, query: str, start: str, end: str
) -> None:
    hint = extract_temporal_hint(query, datetime.fromisoformat(now), zone)
    assert hint.start == datetime.fromisoformat(start)
    assert hint.end == datetime.fromisoformat(end)


def test_recall_uses_calendar_timezone_before_database_filter(
    service: CompanionMemoryService,
) -> None:
    records = []
    for at, content in [
        (datetime(2026, 9, 1, 15, tzinfo=UTC), "昨晚煮了面"),
        (datetime(2026, 9, 1, 16, 30, tzinfo=UTC), "今天凌晨泡了热可可"),
    ]:
        record = service.append_turn(
            ConversationTurnInput(
                user_id="user",
                scope=SCOPE,
                actor_id="user",
                role=ConversationRole.USER,
                consent=ConsentState.GRANTED,
                content=content,
                occurred_at=at,
            )
        ).turn
        assert record is not None
        records.append(record)
    context = service.recall(
        RecallRequest(
            user_id="user",
            scope=SCOPE,
            query="今天聊了什么",
            calendar_timezone="Asia/Singapore",
            as_of=datetime(2026, 9, 1, 17, tzinfo=UTC),
            answer_semantics=AnswerSemantics.UTTERANCE_HISTORY,
            utterance_actor_id="user",
        )
    )
    assert [item.turn.id for item in context.turn_fallback] == [records[1].id]
    assert records[1].content in context.prompt_text
    assert records[0].content not in context.prompt_text


def test_invalid_calendar_and_subject_fail_early() -> None:
    with pytest.raises(ValidationError):
        RecallRequest(user_id="user", query="今天", calendar_timezone="not/a-zone")
    with pytest.raises(ValidationError):
        RecallRequest(user_id="user", query="蓝色", state_subject_actor_id="companion-a")
    with pytest.raises(ValidationError):
        StateQuery(user_id="user", predicate="color", subject_actor_id=" ")


def test_subject_change_history_remains_separate(service: CompanionMemoryService) -> None:
    now = datetime.now(UTC)
    for subject in ["user", "companion-a"]:
        for index, content in enumerate(["喜欢雨天", "更喜欢晴天"]):
            service.remember(
                MemoryInput(
                    user_id="user",
                    scope=SCOPE,
                    subject_actor_id=subject,
                    kind=MemoryKind.PREFERENCE,
                    title="天气",
                    content=content,
                    predicate="weather",
                    event_at=now - timedelta(days=2 - index),
                    consent=ConsentState.GRANTED,
                    explicit_user_request=True,
                )
            )
    history = service.query_state(
        StateQuery(
            user_id="user",
            scope=SCOPE,
            predicate="weather",
            subject_actor_id="companion-a",
            semantics=AnswerSemantics.CHANGE_TRAJECTORY,
        )
    )
    assert len(history.memories) == 2
    assert {memory.subject_actor_id for memory in history.memories} == {"companion-a"}
