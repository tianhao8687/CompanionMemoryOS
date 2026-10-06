"""Storage contracts under real SQLite contention, with independent read-back.

The trace hook only schedules competing operations at their first write attempt.
It does not replace storage, retrieval, policy, or the transaction implementation.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event

import pytest

from companion_memoryos.database import Database
from companion_memoryos.schemas import (
    ConsentState,
    ConversationRole,
    ConversationTurnInput,
    MemoryCorrectionRequest,
    MemoryInput,
    MemoryKind,
    MemoryScope,
    MemoryStatus,
    RecallRequest,
    StateQuery,
    StorageAction,
)
from companion_memoryos.service import CompanionMemoryService
from companion_memoryos.store import MemoryStore


def fact(content="星港设备存放在蓝柜。", **changes):
    return MemoryInput.model_validate(
        dict(
            user_id="owner",
            kind=MemoryKind.PREFERENCE,
            title="设备存放",
            content=content,
            consent=ConsentState.GRANTED,
            explicit_user_request=True,
        )
        | changes
    )


def competing(service, work, reached):
    # A separate connection in each worker still uses the production transaction
    # manager. The parent temporarily holds the SQLite writer slot, not a mock lock.
    with service.store.database.connection() as connection:

        def observe(sql):
            command = sql.lstrip().upper()
            if command.startswith(("BEGIN", "INSERT", "UPDATE", "DELETE")):
                reached.set()

        connection.set_trace_callback(observe)
        try:
            return work()
        finally:
            connection.set_trace_callback(None)


@pytest.mark.parametrize("explicit", [True, False], ids=["active", "candidate"])
def test_concurrent_identical_writes_return_one_durable_record(service, explicit):
    item = fact(explicit_user_request=explicit)
    reached = [Event(), Event()]
    with ThreadPoolExecutor(max_workers=2) as pool:
        with service.store.database.atomic():
            futures = [
                pool.submit(competing, service, lambda: service.remember(item), signal)
                for signal in reached
            ]
            assert all(signal.wait(5) for signal in reached)
        results = [future.result(timeout=10) for future in futures]
    assert len({result.memory.id for result in results}) == 1
    assert len(service.list_memories("owner")) == 1
    assert sum(result.duplicate_of is not None for result in results) == 1
    with service.store.database.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 1


@pytest.mark.parametrize("has_previous", [False, True], ids=["empty-slot", "existing-slot"])
def test_concurrent_revisions_have_one_current_value_and_a_complete_chain(service, has_previous):
    previous = service.remember(fact(stable_key="storage")).memory if has_previous else None
    reached = [Event(), Event()]
    with ThreadPoolExecutor(max_workers=2) as pool:
        with service.store.database.atomic():
            futures = [
                pool.submit(
                    competing,
                    service,
                    lambda content=content: service.remember(fact(content, stable_key="storage")),
                    signal,
                )
                for content, signal in zip(
                    ["星港设备存放在红柜。", "星港设备存放在黄柜。"], reached, strict=True
                )
            ]
            assert all(signal.wait(5) for signal in reached)
        created = [future.result(timeout=10).memory for future in futures]
    records = {record.id: record for record in service.list_memories("owner")}
    active = [record for record in records.values() if record.status is MemoryStatus.ACTIVE]
    assert len(active) == 1
    visited = set()
    current = active[0]
    while current:
        assert current.id not in visited, "version chain contains a cycle"
        visited.add(current.id)
        parent = records.get(current.supersedes_id)
        if parent:
            assert parent.status is MemoryStatus.SUPERSEDED
            assert parent.valid_to == current.valid_from
            assert parent.valid_from <= parent.valid_to
        current = parent
    assert visited == {record.id for record in created} | ({previous.id} if previous else set())
    recalled = service.recall(RecallRequest(user_id="owner", query="星港设备存放"))
    assert {item.memory.id for items in recalled.sections.values() for item in items} == {
        active[0].id
    }


@pytest.mark.parametrize("operation", ["forget_turn", "purge_turn"])
def test_source_removal_cannot_race_a_new_derived_memory(service, operation):
    scope = MemoryScope(companion_id="guide", relationship_id="lab", conversation_id="one")
    source = service.append_turn(
        ConversationTurnInput(
            user_id="owner",
            scope=scope,
            role=ConversationRole.USER,
            actor_id="owner",
            content="星港设备存放在蓝柜。",
            consent=ConsentState.GRANTED,
        )
    ).turn
    item = fact(scope=scope, evidence_turn_ids=[source.id])
    reached = Event()
    with ThreadPoolExecutor(max_workers=1) as pool:
        with service.store.database.atomic():
            future = pool.submit(competing, service, lambda: service.remember(item), reached)
            assert reached.wait(5)
            getattr(service, operation)(source.id, "owner")
        with pytest.raises(ValueError):
            future.result(timeout=10)
    assert not service.list_memories("owner")


def test_forgotten_memory_cannot_be_resurrected_by_an_inflight_correction(service):
    old = service.remember(fact(stable_key="storage")).memory
    reached = Event()
    with ThreadPoolExecutor(max_workers=1) as pool:
        with service.store.database.atomic():
            future = pool.submit(
                competing,
                service,
                lambda: service.correct(
                    old.id, MemoryCorrectionRequest(user_id="owner", content="星港设备在黄柜。")
                ),
                reached,
            )
            assert reached.wait(5)
            service.forget(old.id, "owner")
        with pytest.raises(ValueError, match="only active"):
            future.result(timeout=10)
    assert all(record.status is MemoryStatus.FORGOTTEN for record in service.list_memories("owner"))


def test_review_cannot_resurrect_a_candidate_removed_while_waiting_for_writer(service):
    candidate = service.remember(fact(explicit_user_request=False)).memory
    reached = Event()
    with ThreadPoolExecutor(max_workers=1) as pool:
        with service.store.database.atomic():
            future = pool.submit(
                competing,
                service,
                lambda: service.store.review(candidate.id, "owner", True),
                reached,
            )
            assert reached.wait(5)
            service.forget(candidate.id, "owner")
        with pytest.raises(ValueError, match="only candidate"):
            future.result(timeout=10)
    assert service.store.get(candidate.id, "owner").status is MemoryStatus.FORGOTTEN


@pytest.mark.parametrize("expired_status", [MemoryStatus.ACTIVE, MemoryStatus.CANDIDATE])
def test_fresh_statement_does_not_deduplicate_against_expired_evidence(service, expired_status):
    item = fact(explicit_user_request=expired_status is MemoryStatus.ACTIVE)
    old = service.remember(item).memory
    with service.store.database.connection() as connection:
        connection.execute(
            "UPDATE memories SET expires_at=? WHERE id=?",
            ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(), old.id),
        )
    new = service.remember(fact())
    assert new.action is StorageAction.ACTIVATE
    assert new.memory.id != old.id
    assert new.duplicate_of is None
    context = service.recall(RecallRequest(user_id="owner", query="星港设备存放"))
    assert new.memory.id in {
        item.memory.id for items in context.sections.values() for item in items
    }
    assert service.store.get(old.id, "owner").status is MemoryStatus.EXPIRED


@pytest.mark.parametrize("consent", [ConsentState.DENIED, ConsentState.UNKNOWN])
def test_revoked_source_cannot_authorize_a_new_derived_memory(service, consent):
    scope = MemoryScope(companion_id="guide", relationship_id="lab", conversation_id="one")
    source = service.append_turn(
        ConversationTurnInput(
            user_id="owner",
            scope=scope,
            actor_id="owner",
            role=ConversationRole.USER,
            content="星港设备存放在蓝柜。",
            consent=ConsentState.GRANTED,
        )
    ).turn
    with service.store.database.connection() as connection:
        connection.execute(
            "UPDATE conversation_turns SET consent=? WHERE id=?", (consent.value, source.id)
        )
    with pytest.raises(ValueError, match="consent"):
        service.remember(fact(scope=scope, evidence_turn_ids=[source.id]))
    assert not service.list_memories("owner")


def test_contended_revision_chain_survives_reopening_and_forgetting(service):
    workers, revisions = 8, 16

    def writer(worker):
        return [
            service.remember(
                fact(
                    f"设备存放批次 {worker:02d}-{revision:02d}",
                    stable_key="shared-storage",
                )
            ).memory.id
            for revision in range(revisions)
        ]

    with ThreadPoolExecutor(max_workers=workers) as pool:
        written = {
            identifier for result in pool.map(writer, range(workers)) for identifier in result
        }
    database = Database(service.store.database.data_dir, service.config)
    database.initialize()
    reopened = CompanionMemoryService(MemoryStore(database), service.config)
    records = {r.id: r for r in reopened.list_memories("owner")}
    assert len(records) == len(written) == workers * revisions
    active = [r for r in records.values() if r.status is MemoryStatus.ACTIVE]
    assert len(active) == 1
    visited = set()
    current = active[0]
    while current:
        assert current.id not in visited
        visited.add(current.id)
        parent = records.get(current.supersedes_id)
        if parent:
            assert parent.valid_to == current.valid_from
            assert parent.valid_from <= parent.valid_to
        current = parent
    assert visited == written
    recalled = reopened.recall(RecallRequest(user_id="owner", query="设备存放批次"))
    assert {item.memory.id for values in recalled.sections.values() for item in values} == {
        active[0].id
    }
    reopened.forget(active[0].id, "owner")
    assert not reopened.recall(RecallRequest(user_id="owner", query="设备存放批次")).sections
    with database.connection() as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()


def test_failed_index_write_rolls_back_revision_evidence_and_fts(service, monkeypatch):
    old = service.remember(fact(stable_key="storage")).memory

    def fail(document):
        raise RuntimeError("injected index publication failure")

    monkeypatch.setattr(service.store.semantic_index, "upsert", fail)
    with pytest.raises(RuntimeError, match="injected"):
        service.remember(
            fact(
                "星港设备存放在黄柜。",
                stable_key="storage",
                embedding=[1.0, 0.0],
                embedding_space="rollback-test",
            )
        )
    assert [r.id for r in service.list_memories("owner")] == [old.id]
    assert service.store.get(old.id, "owner").status is MemoryStatus.ACTIVE
    with service.store.database.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM memory_fts").fetchone()[0] == 1


@pytest.mark.parametrize("reader", ["recall", "state", "profile"])
@pytest.mark.parametrize("invalidation", ["expired", "source-consent"])
def test_all_fact_reads_observe_retention_and_source_consent(service, reader, invalidation):
    scope = MemoryScope(companion_id="guide", relationship_id="lab", conversation_id="one")
    source = service.append_turn(
        ConversationTurnInput(
            user_id="owner",
            scope=scope,
            actor_id="owner",
            role=ConversationRole.USER,
            content="星港设备存放在蓝柜。",
            consent=ConsentState.GRANTED,
        )
    ).turn
    stored = service.remember(
        fact(
            scope=scope,
            predicate="storage.location",
            evidence_turn_ids=[source.id],
        )
    ).memory
    with service.store.database.connection() as connection:
        if invalidation == "expired":
            connection.execute(
                "UPDATE memories SET expires_at=? WHERE id=?",
                ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(), stored.id),
            )
        else:
            connection.execute(
                "UPDATE conversation_turns SET consent='denied' WHERE id=?", (source.id,)
            )
    if reader == "recall":
        context = service.recall(RecallRequest(user_id="owner", scope=scope, query="星港设备存放"))
        actual = [item.memory for values in context.sections.values() for item in values]
    elif reader == "state":
        actual = service.query_state(
            StateQuery(
                user_id="owner",
                scope=scope,
                predicate="storage.location",
            )
        ).memories
    else:
        actual = service.profile("owner", scope).preferences
    assert not actual


def test_new_authorized_statement_does_not_reuse_a_revoked_source(service):
    scope = MemoryScope(companion_id="guide", relationship_id="lab", conversation_id="one")

    def source():
        return service.append_turn(
            ConversationTurnInput(
                user_id="owner",
                scope=scope,
                actor_id="owner",
                role=ConversationRole.USER,
                content="星港设备存放在蓝柜。",
                consent=ConsentState.GRANTED,
            )
        ).turn

    first = source()
    old = service.remember(fact(scope=scope, evidence_turn_ids=[first.id])).memory
    with service.store.database.connection() as connection:
        connection.execute("UPDATE conversation_turns SET consent='denied' WHERE id=?", (first.id,))
    second = source()
    new = service.remember(fact(scope=scope, evidence_turn_ids=[second.id]))
    assert new.duplicate_of is None
    assert new.memory.id != old.id
    assert new.memory.evidence_turn_ids == [second.id]
    context = service.recall(RecallRequest(user_id="owner", scope=scope, query="星港设备存放"))
    assert [item.memory.id for values in context.sections.values() for item in values] == [
        new.memory.id
    ]
