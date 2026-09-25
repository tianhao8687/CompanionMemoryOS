"""Long-history failures: provenance, completed dialogue and bounded database work."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from companion_agent.app import LOCAL_USER
from companion_agent.cognition import CognitionSettings
from companion_agent.llm import ModelResponse
from companion_agent.memory_language import forget_target
from companion_agent.memory_lifecycle import is_conversation_task
from companion_agent.recall_completion import complete_candidates
from companion_memoryos.schemas import (
    ConsentState,
    ConversationRole,
    ConversationTurnInput,
    EntityRef,
    EpisodeAttachRequest,
    EpisodeInput,
    InterpreterOutput,
    MemoryInput,
    MemoryKind,
    MemoryStatus,
    OpenLoopInput,
    OpenLoopKind,
    OpenLoopStatus,
    RealityLayer,
    RecallRequest,
    Sensitivity,
    TurnDeletionState,
    TurnInterpretation,
)
from companion_memoryos.temporal import TemporalHint
from tests.test_automatic_memory import visible_context
from tests.test_companion_functional import chat, host_for
from tests.test_romance_app import RecordingLLM


def test_direct_writing_request_for_someone_else_is_immediate_not_a_future_task():
    assert is_conversation_task(
        "相机展志愿服务那天要拼车，给同事写一条接送备注，把确定的日期、时间和目的地放进去。"
    )
    assert not is_conversation_task("我给同事写了一条接送备注。")
    assert not is_conversation_task("如果有需要，给同事写一条接送备注。")


def test_connection_session_preserves_commit_rollback_and_fresh_reads(service):
    db = service.store.database
    with db.connection() as connection:
        connection.execute("CREATE TABLE session_probe (value TEXT)")
    with db.session():
        with db.connection() as first:
            first.execute("INSERT INTO session_probe VALUES ('committed')")
        assert not first.in_transaction
        external = sqlite3.connect(db.path, timeout=0.01)
        try:
            assert external.execute("SELECT value FROM session_probe").fetchone()[0] == "committed"
            external.execute("INSERT INTO session_probe VALUES ('external')")
            external.commit()
            with pytest.raises(RuntimeError), db.connection() as rolled_back:
                rolled_back.execute("INSERT INTO session_probe VALUES ('rolled back')")
                raise RuntimeError("abort this transaction")
            with db.session(), db.connection() as second:
                assert second is first
                assert [r[0] for r in second.execute("SELECT value FROM session_probe")] == [
                    "committed",
                    "external",
                ]
        finally:
            external.close()
    with pytest.raises(sqlite3.ProgrammingError):
        first.execute("SELECT 1")


def test_connection_session_does_not_reuse_closed_or_foreign_thread_context(service):
    db = service.store.database
    with db.session(), db.connection() as first:
        first.execute("SELECT 1")
    with db.session():
        with db.connection() as original:
            original.execute("SELECT 1")
        saved = copy_context()

        def in_worker():
            with db.session(), db.connection() as other:
                assert other is not original
                return other.execute("SELECT 2").fetchone()[0]

        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(copy_context().run, in_worker).result() == 2
    # A context copied during a request can outlive that request.
    assert saved.run(in_worker) == 2


def test_copied_active_transaction_cannot_reuse_another_threads_connection(service):
    db = service.store.database
    with db.session(), db.connection() as original:
        saved = copy_context()

        def read():
            with db.connection() as other:
                assert other is not original
                return other.execute("SELECT 1").fetchone()[0]

        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(saved.run, read).result() == 1
    assert saved.run(read) == 1


def test_nested_atomic_failure_is_not_committed_by_connection_reuse(service):
    db = service.store.database
    with db.connection() as connection:
        connection.execute("CREATE TABLE rollback_probe (value INTEGER)")
    with db.session(), pytest.raises(ValueError), db.atomic() as outer:
        outer.execute("INSERT INTO rollback_probe VALUES (1)")
        with db.atomic() as inner:
            assert inner is outer
            inner.execute("INSERT INTO rollback_probe VALUES (2)")
            raise ValueError("abort both")
    with db.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM rollback_probe").fetchone()[0] == 0


def test_bad_episode_and_reserved_entity_do_not_discard_independent_memory(tmp_path: Path):
    host = host_for(tmp_path, RecordingLLM())
    old = chat(host, "听完了音乐。", "old")
    scope = host.scope(host.conversations()[0]["id"])
    episode = host.memory.create_episode(
        EpisodeInput(
            user_id=LOCAL_USER,
            scope=scope,
            title="音乐",
            topic_keys=["音乐"],
            participant_actor_ids=[LOCAL_USER],
        )
    )
    host.memory.attach_episode_turn(
        episode.id,
        EpisodeAttachRequest(
            user_id=LOCAL_USER,
            scope=scope,
            turn_id=old["user"]["id"],
        ),
    )

    class Interpreter:
        def interpret(self, context):
            return InterpreterOutput(
                model_fingerprint="fixture",
                interpretation=TurnInterpretation.model_validate(
                    {
                        "topics": ["预算"],
                        "entities": [{"ref": LOCAL_USER, "name": "我", "kind": "person"}],
                        "episode_hint": {
                            "action": "attach",
                            "episode_id": episode.id,
                            "continuity_turn_id": old["user"]["id"],
                            "participant_actor_ids": [LOCAL_USER],
                        },
                        "memory_candidates": [
                            {
                                "kind": "preference",
                                "title": "杯子",
                                "content": "我喜欢蓝色杯子",
                                "subject_actor_id": LOCAL_USER,
                                "confidence": 0.99,
                            }
                        ],
                    }
                ),
            )

    host.memory.turn_interpreter = Interpreter()
    result = chat(host, "我喜欢蓝色杯子。", "new")
    receipt = host.memory.get_turn_interpretation(result["user"]["id"], LOCAL_USER)
    assert receipt is not None and receipt.memory_ids
    assert receipt.episode_id is None
    assert (
        "reserved_actor_entity_proposal_deferred"
        in receipt.processing_metadata["proposal_filter_reasons"]
    )


def test_embedded_forget_command_redacts_location_and_retains_independent_reply(tmp_path: Path):
    model = RecordingLLM()
    host = host_for(tmp_path, model)
    original = chat(host, "翻包时把旧门禁卡塞进了紫色雨伞套里，它已经停用了。", "source")
    command = (
        "还有一件小事：请把旧门禁卡放在哪里这件事忘掉，以后别拿出来说。"
        "卡已经停用了，位置也没必要留着。"
    )
    assert forget_target(command) == "@location:旧门禁卡"
    chat(host, command, "forget", host.new_conversation()["id"])
    source = host.memory.store.get_turn(original["user"]["id"], LOCAL_USER)
    assert source.deletion_state is TurnDeletionState.ACTIVE
    assert "紫色雨伞套" not in source.content
    assert "已经停用" in source.content
    reply = host.memory.store.get_turn(original["assistant"]["id"], LOCAL_USER)
    assert reply.deletion_state is TurnDeletionState.ACTIVE
    assert reply.content == original["assistant"]["content"]
    with host.database.connection() as db:
        assert (
            db.execute(
                "SELECT COUNT(*) FROM turn_fts WHERE content LIKE '%紫色雨伞套%'"
            ).fetchone()[0]
            == 0
        )
    restarted = host_for(tmp_path, model)
    chat(restarted, "旧门禁卡放哪里了？", "recall", restarted.new_conversation()["id"])
    assert "紫色雨伞套" not in visible_context(model)


@pytest.mark.parametrize(
    "text",
    [
        "如果我不需要了，请把旧门卡的位置忘掉。",
        "她说：请把旧门卡的位置忘掉。",
        "还有一件小事：请把旧门卡的位置不要忘掉。",
        "小说里写着：请把旧门卡的位置忘掉。",
    ],
)
def test_embedded_forget_is_not_a_conditional_report_or_negation(text):
    assert forget_target(text) is None


def test_recent_forget_also_works_when_extraction_created_no_card(tmp_path: Path):
    host = host_for(tmp_path, RecordingLLM())
    original = chat(host, "临时便条夹在蓝色夹板里。", "source")
    assert not host.memory.list_memories(LOCAL_USER)
    chat(host, "请忘掉刚才那件事。", "forget")
    assert (
        host.memory.store.get_turn(original["user"]["id"], LOCAL_USER).deletion_state
        is TurnDeletionState.FORGOTTEN
    )


def make_loop(host, sent, summary, keys):
    source = host.memory.store.get_turn(sent["user"]["id"], LOCAL_USER)
    loop = host.memory.create_open_loop(
        OpenLoopInput(
            user_id=LOCAL_USER,
            scope=source.scope,
            kind=OpenLoopKind.EVENT_OUTCOME,
            summary=summary,
            topic_keys=keys,
            source_turn_id=source.id,
            consent=ConsentState.GRANTED,
        )
    ).open_loop
    assert loop
    return loop


def test_cancel_updates_rescheduled_duplicates_but_leaves_other_event(tmp_path: Path):
    host = host_for(tmp_path, RecordingLLM())
    first = chat(host, "十月十七日有档案馆志愿讲解，另有小册子讨论。", "first")
    second = chat(host, "志愿讲解改期到十月十八日。", "second")
    loops = [
        make_loop(host, first, "原志愿讲解", ["志愿讲解"]),
        make_loop(host, second, "改期的志愿讲解", ["志愿讲解改期", "榆桥档案馆"]),
        make_loop(host, second, "新场地讲解", ["档案馆讲解", "河岸展厅一楼"]),
        make_loop(host, second, "场地尚待确认", ["场地变动", "外出讲解", "榆桥档案馆"]),
    ]
    unrelated = make_loop(host, first, "小册子讨论", ["小册子讨论"])
    other_event = make_loop(host, first, "同馆午餐", ["档案馆聚餐", "档案馆", "十月十八日"])
    result = chat(
        host,
        "档案馆通知十月十八日的志愿讲解整个取消了，不是再改期。小册子仍打算自己做。",
        "cancel",
        host.new_conversation()["id"],
    )
    for loop in loops:
        updated = host.memory.store.get_open_loop(loop.id, LOCAL_USER)
        assert updated.status is OpenLoopStatus.CANCELLED
        assert updated.metadata["last_update_source_turn_id"] == result["user"]["id"]
    assert host.memory.store.get_open_loop(unrelated.id, LOCAL_USER).status is OpenLoopStatus.OPEN
    assert host.memory.store.get_open_loop(other_event.id, LOCAL_USER).status is OpenLoopStatus.OPEN


def test_newer_budget_source_survives_a_stronger_old_vector_hit(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "companion_agent.cognition.Embeddings.encode",
        lambda self, text: [0.0, 1.0] if "二百一十" in text else [1.0, 0.0],
    )
    model = RecordingLLM()
    host = host_for(tmp_path, model)
    chat(host, "声音小册子先留二百八十元预算。", "old")
    updated = chat(host, "小册子预算收紧到二百一十元，原来的数作废。", "new")
    source = host.memory.store.get_turn(updated["user"]["id"], LOCAL_USER)
    host.memory.remember(
        MemoryInput(
            user_id=LOCAL_USER,
            scope=source.scope.model_copy(update={"conversation_id": None}),
            kind=MemoryKind.PREFERENCE,
            title="小册子预算",
            predicate="booklet_budget",
            content=source.content,
            consent=ConsentState.GRANTED,
            explicit_user_request=True,
            evidence_turn_ids=[source.id],
            source_ref=f"turn:{source.id}",
        )
    )
    for i in range(9):
        chat(host, f"声音小册子还有第{i}个制作想法。", f"noise-{i}")
    chat(host, "声音小册子这件事我还想完成。", "query", host.new_conversation()["id"])
    assert "二百一十" in visible_context(model)
    host.memory.forget_turn(source.id, LOCAL_USER)
    chat(host, "声音小册子还是想做完。", "after-forget", host.new_conversation()["id"])
    assert "二百一十" not in visible_context(model)


def test_explicit_previous_preference_joins_existing_version_chain(tmp_path: Path):
    host = host_for(tmp_path, RecordingLLM())
    original = chat(host, "最近通勤最爱听无词钢琴。", "old")
    source = host.memory.store.get_turn(original["user"]["id"], LOCAL_USER)
    old = host.memory.remember(
        MemoryInput(
            user_id=LOCAL_USER,
            scope=source.scope.model_copy(update={"conversation_id": None}),
            kind=MemoryKind.PREFERENCE,
            title="通勤",
            predicate="commute_music",
            subject_actor_id=LOCAL_USER,
            content=source.content,
            consent=ConsentState.GRANTED,
            explicit_user_request=True,
            evidence_turn_ids=[source.id],
            source_ref=f"turn:{source.id}",
        )
    ).memory
    assert old
    changed = chat(host, "以后通勤最喜欢的改成城市环境录音，钢琴是之前的偏好。", "change")
    assert host.memory.store.get(old.id, LOCAL_USER).status is MemoryStatus.SUPERSEDED
    active = host.memory.list_memories(LOCAL_USER, {MemoryStatus.ACTIVE})
    latest = next(m for m in active if m.predicate == old.predicate)
    assert latest.supersedes_id == old.id
    assert latest.evidence_turn_ids == [changed["user"]["id"]]
    assert "城市环境录音" in latest.content
    assert "城市环境录音" in latest.title and "钢琴" not in latest.title


@pytest.mark.parametrize(
    "replacement",
    [
        "以后默哥最喜欢的改成城市环境录音，钢琴是之前的偏好。",
        "以后通勤最喜欢的不要改成城市环境录音，钢琴是之前的偏好。",
        "如果以后通勤最喜欢的改成城市环境录音，钢琴是之前的偏好。",
    ],
)
def test_preference_correction_does_not_merge_other_person_negation_or_condition(
    tmp_path: Path, replacement: str
):
    host = host_for(tmp_path, RecordingLLM())
    original = chat(host, "最近通勤最爱听无词钢琴。", "old")
    source = host.memory.store.get_turn(original["user"]["id"], LOCAL_USER)
    old = host.memory.remember(
        MemoryInput(
            user_id=LOCAL_USER,
            scope=source.scope.model_copy(update={"conversation_id": None}),
            kind=MemoryKind.PREFERENCE,
            title="通勤",
            predicate="commute_music",
            subject_actor_id=LOCAL_USER,
            content=source.content,
            consent=ConsentState.GRANTED,
            explicit_user_request=True,
            evidence_turn_ids=[source.id],
            source_ref=f"turn:{source.id}",
        )
    ).memory
    assert old
    chat(host, replacement, "change")
    assert host.memory.store.get(old.id, LOCAL_USER).status is MemoryStatus.ACTIVE


@pytest.mark.parametrize(
    "restriction",
    ["none", "user", "companion", "relationship", "conversation", "future", "sensitive", "fiction"],
)
def test_completion_preserves_scope_time_sensitivity_and_reality(tmp_path: Path, restriction: str):
    host = host_for(tmp_path, RecordingLLM())
    scope = host.scope(host.new_conversation()["id"])
    scope = scope.model_copy(update={"conversation_id": None})
    stored_scope = scope.model_copy(update={"conversation_id": "earlier"})
    if restriction in {"companion", "relationship"}:
        stored_scope = stored_scope.model_copy(update={restriction + "_id": "different"})
    user = "other-user" if restriction == "user" else LOCAL_USER
    at = datetime.now(UTC)
    fact_time = at + timedelta(days=1) if restriction == "future" else at - timedelta(days=1)
    source = host.memory.append_turn(
        ConversationTurnInput(
            user_id=user,
            actor_id=user,
            scope=stored_scope,
            role=ConversationRole.USER,
            content="小册子预算收紧到二百一十元。",
            consent=ConsentState.GRANTED,
            occurred_at=fact_time,
            sensitivity=Sensitivity.SENSITIVE if restriction == "sensitive" else Sensitivity.NORMAL,
            metadata={"reality_layer": "fiction"} if restriction == "fiction" else {},
        )
    ).turn
    assert source
    host.memory.remember(
        MemoryInput(
            user_id=user,
            scope=stored_scope.model_copy(update={"conversation_id": None}),
            kind=MemoryKind.PREFERENCE,
            title="小册子预算",
            predicate="booklet_budget",
            content=source.content,
            consent=ConsentState.GRANTED,
            explicit_user_request=True,
            event_at=fact_time,
            evidence_turn_ids=[source.id],
            source_ref=f"turn:{source.id}",
            reality_layer=RealityLayer.FICTION
            if restriction == "fiction"
            else RealityLayer.REAL_WORLD,
        )
    )
    request = RecallRequest(
        user_id=LOCAL_USER,
        scope=scope.model_copy(update={"conversation_id": "current"}),
        query="声音小册子还想做完。",
        include_turn_evidence=True,
        include_relationship_turns=restriction != "conversation",
        as_of=at,
    )
    recalled = complete_candidates(host.memory, request, TemporalHint(), [])
    assert (source.id in {i.turn.id for i in recalled}) is (restriction == "none")


@pytest.mark.parametrize("with_fact_card", [True, False])
def test_named_people_each_retain_preferences_among_stronger_vector_noise(
    tmp_path: Path, monkeypatch, with_fact_card: bool
):
    monkeypatch.setattr(
        "companion_agent.cognition.Embeddings.encode",
        lambda self, text: [0.4, 0.9] if "不碰香菜" in text else [1.0, 0.0],
    )
    model = RecordingLLM()
    host = host_for(tmp_path, model)
    for i, (name, alias, fact) in enumerate(
        [
            ("林默", "默哥", "默哥不碰香菜。"),
            ("陈沫", "沫沫", "沫沫吃面喜欢香菜。"),
        ]
    ):
        identity = chat(host, f"我的朋友{name}，平时我叫他{alias}。", f"identity-{i}")
        fact_result = chat(host, fact, f"person-{i}")
        result = fact_result if with_fact_card else identity
        source = host.memory.store.get_turn(result["user"]["id"], LOCAL_USER)
        host.memory.remember(
            MemoryInput(
                user_id=LOCAL_USER,
                scope=source.scope.model_copy(update={"conversation_id": None}),
                kind=MemoryKind.PREFERENCE if with_fact_card else MemoryKind.SHARED_MOMENT,
                title="朋友口味",
                predicate="food_preference",
                content=source.content,
                subject_actor_id=f"entity:person-{i}",
                entities=[
                    EntityRef(id=f"entity:person-{i}", name=name, aliases=[alias], kind="person")
                ],
                consent=ConsentState.GRANTED,
                evidence_turn_ids=[source.id],
                source_ref=f"turn:{source.id}",
                confidence=0.99,
            )
        )
    for i in range(9):
        chat(host, f"默哥和沫沫的第{i}次聚会真热闹。", f"noise-{i}")
    chat(
        host,
        "沫沫周五想吃面，默哥也来，两份备注帮我写清楚。",
        "query",
        host.new_conversation()["id"],
    )
    context = visible_context(model)
    assert "默哥不碰香菜" in context and "沫沫吃面喜欢香菜" in context


def test_saved_reply_is_retrieved_as_assistant_words_not_as_unfinished_task(tmp_path: Path):
    class WritingModel(RecordingLLM):
        def generate(self, messages):
            self.inputs.append(messages)
            return ModelResponse(text="封底可以写：把路上的声音留一页给明天。", model="fixture")

    model = WritingModel()
    host = host_for(tmp_path, model, cognition=CognitionSettings(embedding_backend="local"))
    result = chat(host, "我想在小册子封底加一句简短的话，你试着写一个有点余味的。", "write")
    chat(host, "以前小册子封底那句你写的是什么？", "query", host.new_conversation()["id"])
    context = visible_context(model)
    assert result["assistant"]["id"] in context
    assert "把路上的声音留一页给明天" in context
    assert '"role": "assistant"' in context or '"role":"assistant"' in context


def test_raw_venue_update_is_not_displaced_by_an_unrelated_assistant_reply(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(
        "companion_agent.cognition.Embeddings.encode",
        lambda self, text: [0.7, 0.7] if "河岸展厅" in text else [1.0, 0.0],
    )
    model = RecordingLLM()
    host = host_for(tmp_path, model)
    chat(host, "志愿讲解改到十月十八日十点四十，在旧馆二楼。", "old")
    chat(host, "档案馆又把讲解搬到河岸展厅一楼了，还是十月十八日十点四十。", "new")
    unrelated = chat(host, "准备给朋友点面，备注帮我写一下。", "unrelated")
    for i in range(8):
        chat(host, f"今天有第{i}项准备工作。", f"noise-{i}")
    chat(
        host,
        "外出讲解那天要拼车，写一条接送备注，放入确定的目的地。",
        "query",
        host.new_conversation()["id"],
    )
    assert "河岸展厅一楼" in visible_context(model)
    assert unrelated["assistant"]["id"] not in visible_context(model)


@pytest.mark.parametrize(
    "removal",
    [
        "我把小册子的封面烫字去掉了，只留内页和装订。",
        "小册子我决定不做封面烫字了，只打印内页和装订。",
    ],
)
def test_removed_order_item_is_retrieved_without_a_memory_card(
    tmp_path: Path, monkeypatch, removal
):
    monkeypatch.setattr(
        "companion_agent.cognition.Embeddings.encode",
        lambda self, text: [0.7, 0.7] if "去掉" in text else [1.0, 0.0],
    )
    model = RecordingLLM()
    host = host_for(tmp_path, model)
    chat(host, "小册子内页128元，装订46元，封面烫字24元。", "quote")
    removed = chat(host, removal, "remove")
    for i in range(9):
        chat(host, f"小册子还有第{i}个版式想法。", f"noise-{i}")
    chat(
        host,
        "小册子店催我确认订单，按最后留下的项目列付款核对。",
        "query",
        host.new_conversation()["id"],
    )
    assert removed["user"]["id"] in visible_context(model)


def test_old_immediate_dialogue_candidate_is_not_kept_as_future_todo(tmp_path: Path):
    host = host_for(tmp_path, RecordingLLM())
    result = chat(host, "我想在小册子封底加一句简短的话，你试着写一个有点余味的。", "write")
    source = host.memory.store.get_turn(result["user"]["id"], LOCAL_USER)
    old = host.memory.create_open_loop(
        OpenLoopInput(
            user_id=LOCAL_USER,
            scope=source.scope.model_copy(update={"conversation_id": None}),
            kind=OpenLoopKind.ASSISTANT_COMMITMENT,
            summary="小册子封底文案尚待完成",
            topic_keys=["小册子", "封底文案"],
            source_turn_id=source.id,
            consent=ConsentState.GRANTED,
            metadata={"candidate_only": True},
        )
    ).open_loop
    assert old
    chat(host, "刚买了一本书。", "next")
    assert host.memory.store.get_open_loop(old.id, LOCAL_USER).status is OpenLoopStatus.CANCELLED
