"""Fresh contract probes with independent source and transport outcomes.

These fixtures do not measure Chinese language quality or benchmark accuracy.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from itertools import pairwise
from threading import Event
from uuid import uuid4

import pytest

from companion_agent import CompanionAgent, load_persona
from companion_agent.cognition import ApplicationMemory, CognitionSettings
from companion_agent.deepseek import DeepSeekConfig
from companion_agent.embedding_backfill import EmbeddingBackfill
from companion_agent.index_worker import IndexWorker
from companion_agent.llm import ModelResponse
from companion_agent.testing.control import TestControl as Control
from companion_agent.testing.driver import ManagedInstance
from companion_memoryos.diagnostics import background_context, model_call, sink
from companion_memoryos.schemas import (
    ConsentState,
    ConversationRole,
    ConversationTurnInput,
    EpisodeHint,
    InterpreterOutput,
    MemoryInput,
    MemoryKind,
    MemoryScope,
    ProcessTurnRequest,
    RecallRequest,
    ReviewDecision,
    TurnInterpretation,
)
from companion_memoryos.semantic_index import SemanticKind
from companion_memoryos.store import TurnSearchCandidate
from companion_memoryos.temporal import TemporalHint

SCOPE = MemoryScope(companion_id="guide", relationship_id="boundaries", conversation_id="one")


@pytest.fixture
def memory(service):
    app = ApplicationMemory(service.store, service.config)
    app.configure(
        CognitionSettings(extract_memory=False, embedding_backend="off"),
        offline=True,
        model=DeepSeekConfig(),
        key=None,
    )
    try:
        yield app
    finally:
        app.close_indexer()


def put(memory, text, **changes):
    data = dict(
        user_id="user",
        scope=SCOPE,
        role=ConversationRole.USER,
        actor_id="user",
        content=text,
        consent=ConsentState.GRANTED,
    )
    data.update(changes)
    turn = memory.append_turn(ConversationTurnInput(**data)).turn
    assert turn is not None
    return turn


def request(text, **changes):
    data = dict(
        user_id="user",
        scope=SCOPE,
        content=text,
        consent=ConsentState.GRANTED,
        model_consent=ConsentState.GRANTED,
        idempotency_key=str(uuid4()),
    )
    data.update(changes)
    return ProcessTurnRequest(**data)


class Encoder:
    space = "fresh-boundary-2d"
    backend = "local"

    def __init__(self):
        self.inputs = []

    def encode(self, text):
        self.inputs.append(text)
        return [1.0, 0.0]


class Index:
    """No SQLite dependency, including deliberately falsey empty state."""

    def __init__(self):
        self.documents = {}
        self.writes = []
        self.deletes = []
        self.queries = []

    def __bool__(self):
        return bool(self.documents)

    def upsert(self, document):
        self.documents[document.kind, document.id] = document
        self.writes.append(document)

    def delete(self, kind, record_id, user_id):
        self.deletes.append((kind, record_id, user_id))
        self.documents.pop((kind, record_id), None)

    def search(self, query):
        self.queries.append(query)
        return []


class PassageIndex(Index):
    def __init__(self, namespace="fresh-custom-index"):
        super().__init__()
        self.cache_namespace = namespace
        self.passages = {}
        self.reads = []

    def indexed_ids(self, kind, user_id, space):
        return {
            doc.id
            for doc in self.documents.values()
            if doc.kind == kind and doc.user_id == user_id and doc.space == space
        }

    def upsert_passage(self, document, start, end):
        self.upsert(document)
        self.passages[document.id, document.source_hash, start, end] = document

    def passage_vectors(self, turn_id, user_id, space, source_hash):
        self.reads.append((turn_id, user_id, space, source_hash))
        return sorted(
            (start, end, doc.vector)
            for (identifier, version, start, end), doc in self.passages.items()
            if identifier == turn_id
            and version == source_hash
            and doc.user_id == user_id
            and doc.space == space
        )


@pytest.mark.parametrize("backend_type", [Index, PassageIndex])
def test_injected_backend_owns_writes_reads_and_deletes(memory, backend_type):
    from companion_memoryos.store import MemoryStore

    backend = backend_type()
    memory.store = MemoryStore(memory.store.database, semantic_index=backend)
    assert memory.store.semantic_index is backend
    memory.embeddings = Encoder()
    text = "仓储校对：每只圆筒单独贴签，空格也属于原文。\n" * 72
    source = put(memory, text)
    memory.index_turns("user", SCOPE, datetime.now(UTC))
    assert backend.writes and {d.id for d in backend.writes} == {source.id}
    assert all(d.source_hash == source.content_hash for d in backend.writes)
    with memory.store.database.connection() as db:
        assert db.execute("SELECT count(*) FROM turn_embeddings").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM turn_embedding_passages").fetchone()[0] == 0
    query = RecallRequest(
        user_id="user",
        scope=SCOPE,
        query="圆筒怎样贴签？",
        include_turn_evidence=True,
        query_embedding=[1.0, 0.0],
        embedding_space=memory.embeddings.space,
    )
    memory.recall(query)
    assert any(q.kind is SemanticKind.TURN for q in backend.queries)
    item = memory._turn_item(TurnSearchCandidate(source), query, TemporalHint())
    assert item.evidence_span is not None
    assert item.evidence_text == source.content[slice(*item.evidence_span)]
    if isinstance(backend, PassageIndex):
        assert backend.reads[-1] == (source.id, "user", Encoder.space, source.content_hash)
        spans = sorted((start, end) for _, _, start, end in backend.passages)
        assert spans[0][0] == 0 and spans[-1][1] == len(source.content)
        assert all(0 < end - start <= 240 for start, end in spans)
        assert all(a[1] == b[0] for a, b in pairwise(spans))
    else:
        assert memory.embeddings.inputs == [source.content]
    memory.forget_turn(source.id, "user")
    assert (SemanticKind.TURN, source.id, "user") in backend.deletes


@pytest.mark.parametrize("change", ["namespace", "eviction"])
def test_receipts_do_not_hide_missing_or_replaced_backend_data(memory, change):
    backend = PassageIndex()
    memory.store.semantic_index, memory.embeddings = backend, Encoder()
    source = memory.remember(
        MemoryInput(
            user_id="user",
            scope=SCOPE,
            kind=MemoryKind.SHARED_MOMENT,
            title="检修备忘",
            content="挡板用紫色标签编号。",
            consent=ConsentState.GRANTED,
        )
    ).memory
    assert source is not None
    memory.review(source.id, "user", ReviewDecision.CONFIRM)
    memory.index_active("user", SCOPE)
    assert len(backend.writes) == 1
    memory.index_active("user", SCOPE)
    assert len(backend.writes) == 1
    if change == "namespace":
        backend.cache_namespace = "another-physical-index"
    else:
        backend.documents.clear()
    memory.index_active("user", SCOPE)
    assert len(backend.writes) == 2


def test_index_replacement_during_encoding_cannot_publish_to_old_backend(memory):
    old, replacement = PassageIndex(), PassageIndex("replacement")
    memory.store.semantic_index = old
    source = put(memory, "本批次零件装在灰紫色箱中。")

    class SwitchingEncoder(Encoder):
        def encode(self, text):
            memory.store.semantic_index = replacement
            return super().encode(text)

    memory.embeddings = SwitchingEncoder()
    memory.index_turns("user", SCOPE, datetime.now(UTC))
    assert not old.writes and not replacement.writes
    assert memory.store.get_turn(source.id, "user").content == source.content


def test_passage_read_finishes_while_another_writer_remains_locked(memory):
    memory.embeddings.backend = "local"
    source = put(memory, "压纹样本每四页装订一次。" * 80)
    memory.index_turns("user", SCOPE, datetime.now(UTC))
    held, release, finished = Event(), Event(), Event()
    result = []

    def writer():
        with memory.store.database.atomic():
            held.set()
            assert release.wait(8)

    def reader():
        result.extend(
            memory.store.semantic_index.passage_vectors(
                source.id,
                "user",
                memory.embeddings.space,
                source.content_hash,
            )
        )
        finished.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        writing = pool.submit(writer)
        try:
            assert held.wait(3)
            reading = pool.submit(reader)
            assert finished.wait(2), "a SELECT waited for the writer to release"
            assert not release.is_set() and result
        finally:
            release.set()
        writing.result(timeout=5)
        reading.result(timeout=5)


@pytest.mark.parametrize("linked", [False, True])
@pytest.mark.parametrize(
    "question",
    [
        "进展能接着说一下吗？",
        "前面谈的后续是什么？",
        "再帮我整理成一段话。",
        "接下去由谁负责？",
        "这样还要重新预约吗？",
    ],
)
def test_reference_context_uses_a_link_not_a_sentence_prefix(memory, monkeypatch, linked, question):
    source = put(memory, "严澈周五送检磨砂玻璃，温榆负责登记，不确定当天能否完成。")
    observed = []
    recall = memory.recall

    def recording(actual):
        observed.append(actual.query)
        return recall(actual)

    monkeypatch.setattr(memory, "recall", recording)
    result = memory.process_turn(request(question, reply_to_turn_id=source.id if linked else None))
    assert observed == [question + "\n" + source.content if linked else question]
    assert result.storage.turn.content == question
    assert memory.store.get_turn(source.id, "user").content == source.content


@pytest.mark.parametrize(
    "question",
    [
        "之前的安排还能继续讲吗？",
        "这一步帮我写成便签吧。",
        "这个三角形有几条边？",
    ],
)
def test_unresolved_language_keeps_native_history_without_making_it_a_rule(memory, question):
    source = put(memory, "顾浔把深紫色布料放在三号工作台，孟遥明早来取。")

    class Recorder:
        def generate(self, messages):
            self.messages = messages
            return ModelResponse(text="本次只记录输入，不评判语言。", model="fixture")

    recorder = Recorder()
    CompanionAgent(memory, load_persona(), recorder).chat(request(question))
    assert any(m.source_turn_id == source.id for m in recorder.messages)
    assert any(source.content in m.content for m in recorder.messages if m.role != "system")
    assert all(source.content not in m.content for m in recorder.messages if m.role == "system")
    assert recorder.messages[-1].content == question


@pytest.mark.parametrize("detached", [False, True])
def test_applied_episode_continuity_can_supply_a_verified_source(memory, monkeypatch, detached):
    class Interpreter:
        def interpret(self, context):
            hint = (
                EpisodeHint(
                    action="attach",
                    episode_id=context.episodes[0].id,
                    continuity_turn_id=context.episodes[0].continuity_turn_id,
                )
                if context.episodes
                else EpisodeHint(action="new", title="相纸寄送")
            )
            return InterpreterOutput(
                interpretation=TurnInterpretation(topics=["相纸"], episode_hint=hint),
                model_fingerprint="offline-structural-proposal",
            )

    memory.turn_interpreter = Interpreter()
    first = memory.process_turn(request("这批相纸寄到北侧收发室。"))
    incoming = request("相纸接下来还有别的安排吗？")
    second = memory.process_turn(incoming, defer_recall=True)
    assert first.interpretation is not None and first.interpretation.episode_id
    assert second.interpretation is not None
    assert second.interpretation.episode_id == first.interpretation.episode_id
    if detached:
        with memory.store.database.connection() as db:
            db.execute(
                "UPDATE conversation_turns SET episode_id=NULL WHERE id=?", (first.storage.turn.id,)
            )
    queries = []
    recall = memory.recall

    def record_query(actual):
        queries.append(actual.query)
        return recall(actual)

    monkeypatch.setattr(memory, "recall", record_query)
    second = memory.recall_processed_turn(incoming, second)
    expected = incoming.content + ("" if detached else "\n" + first.storage.turn.content)
    assert queries == [expected]
    assert second.response_context.query_context_turn_ids == (
        [] if detached else [first.storage.turn.id]
    )


@pytest.mark.parametrize("change", ["forgotten", "restricted", "different_scope"])
def test_link_does_not_override_source_policy(memory, change):
    source = put(memory, "报修序列号是 HV-830，纸本在前台。")
    incoming = request("继续核对这一项。", reply_to_turn_id=source.id)
    result = memory.process_turn(incoming, defer_recall=True)
    if change == "forgotten":
        memory.forget_turn(source.id, "user")
    elif change == "restricted":
        from companion_memoryos.schemas import MemoryReferenceFeedbackInput

        memory.record_reference_feedback(
            MemoryReferenceFeedbackInput(
                user_id="user",
                scope=SCOPE,
                evidence_kind="turn",
                evidence_id=source.id,
                kind="do_not_reference",
            )
        )
    else:
        with memory.store.database.connection() as db:
            db.execute(
                "UPDATE conversation_turns SET conversation_id=? WHERE id=?",
                ("different", source.id),
            )
    result = memory.recall_processed_turn(incoming, result)
    assert result.response_context.query_context_turn_ids == []
    assert not any(i.turn.id == source.id for i in result.response_context.turn_fallback)


@pytest.mark.parametrize("denied", [False, True])
def test_plain_observer_runs_and_retains_its_call_guard(denied):
    attempted, body, completed = Event(), Event(), Event()

    class Observer:
        def begin_call(self, source, payload, live):
            attempted.set()
            if denied:
                raise PermissionError("synthetic call denied")
            return {}

        def finish_call(self, call):
            completed.set()

        def event(self, name, value):
            pass

    worker = IndexWorker(context_factory=background_context)

    def work(cancelled):
        with model_call("synthetic-no-transport", {}, live=False):
            body.set()
        return True

    token = sink.set(Observer())
    try:
        assert worker.submit("one", work)
    finally:
        sink.reset(token)
    try:
        assert attempted.wait(3)
        if not denied:
            assert completed.wait(3)
    finally:
        worker.close()
    assert body.is_set() is not denied
    assert completed.is_set() is not denied


@pytest.mark.parametrize("invalidate", [False, True])
def test_background_context_keeps_origin_and_persistent_budget(tmp_path, invalidate):
    instance = ManagedInstance(tmp_path / "runs", max_calls=1)
    control = Control(instance.directory, instance.token)
    control.allowed.add("one")
    attempted, released, completed = Event(), Event(), Event()
    body = []
    worker = IndexWorker(context_factory=background_context)

    def work(cancelled):
        attempted.set()
        assert released.wait(5)
        try:
            for _ in range(2):
                with model_call("synthetic-no-transport", {}, live=False):
                    body.append("entered")
        finally:
            completed.set()
        return True

    try:
        with control.capture("one", "origin", "第一份合成记录") as origin:
            assert worker.submit("origin", work)
            assert attempted.wait(3)
        if invalidate:
            control.invalidate()
        with control.capture("one", "next", "第二份合成记录") as following:
            released.set()
            assert completed.wait(3)
            assert following["calls"] == []
        assert len(body) == (0 if invalidate else 1)
        assert control.accounting["calls"] == (0 if invalidate else 1)
        if not invalidate:
            assert len(origin["calls"]) == 1
            assert origin["calls"][0]["source"] == "synthetic-no-transport"
    finally:
        released.set()
        worker.close()
        instance.stop()


@pytest.mark.parametrize("position", [0, 1400, 4900])
def test_fresh_long_evidence_checks_literal_offsets_not_the_window_function(memory, position):
    padding = "这些行仅登记平常的整理流程，不提供签收信息。\n"
    filler = (padding * 250)[:position]
    fact = "银杉工单由黎峥签收，封签是青绿色，缺少的卡扣要下周二补齐。"
    source = put(memory, filler + fact + padding * 150)
    item = memory._turn_item(
        TurnSearchCandidate(source),
        RecallRequest(
            user_id="user",
            scope=SCOPE,
            query="银杉工单谁签收，卡扣何时补齐？",
            include_turn_evidence=True,
        ),
        TemporalHint(),
    )
    assert fact in item.evidence_text
    start, end = item.evidence_span
    assert 0 <= start <= len(filler) and len(filler) + len(fact) <= end <= len(source.content)
    assert item.evidence_text == source.content[start:end]
    assert end - start <= 720


@pytest.mark.parametrize("invalidate", ["redact", "forget", "consent"])
def test_background_publication_rechecks_sources_after_encoding(memory, invalidate):
    source = put(memory, "新领的资料箱编号为 QF-268，存入二层库房。")
    memory.embeddings = Encoder()
    encoded, release = Event(), Event()
    original = memory.embeddings.encode

    def blocked(text):
        encoded.set()
        assert release.wait(5)
        return original(text)

    memory.embeddings.encode = blocked
    batch = EmbeddingBackfill(memory, memory.embeddings, "user", SCOPE, datetime.now(UTC), Event())
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(batch.turns)
        try:
            assert encoded.wait(3)
            if invalidate == "redact":
                memory.store.redact_turn(source.id, "user", [(0, 3)])
            elif invalidate == "forget":
                memory.forget_turn(source.id, "user")
            else:
                with memory.store.database.connection() as db:
                    db.execute(
                        "UPDATE conversation_turns SET consent='denied' WHERE id=?", (source.id,)
                    )
        finally:
            release.set()
        pending.result(timeout=5)
    with memory.store.database.connection() as db:
        assert db.execute("SELECT count(*) FROM turn_embeddings").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM turn_embedding_passages").fetchone()[0] == 0
