from datetime import UTC, datetime
from pathlib import Path

from companion_memoryos.config import CompanionConfig
from companion_memoryos.constants import DATABASE_SCHEMA_VERSION
from companion_memoryos.database import Database
from companion_memoryos.schemas import (
    ConsentState,
    ConversationRole,
    ConversationTurnInput,
    MemoryInput,
    MemoryKind,
    MemoryReferenceMode,
    MemoryScope,
    MemoryUseInput,
    MemoryUseType,
    RecallRequest,
    RecallUseMode,
    ResponseBeatSentRequest,
    ResponseGoal,
    ResponsePlanRequest,
)
from companion_memoryos.semantic_index import (
    SemanticDocument,
    SemanticHit,
    SemanticKind,
    SemanticQuery,
    SQLiteSemanticIndex,
)
from companion_memoryos.service import CompanionMemoryService
from companion_memoryos.store import MemoryStore

SCOPE = MemoryScope(companion_id="ai", relationship_id="relationship", conversation_id="chat")


class CharacterCounter:
    def __init__(self) -> None:
        self.calls = 0

    def count(self, text: str) -> int:
        self.calls += 1
        return len(text)


class RecordingSemanticIndex:
    def __init__(self, database: Database) -> None:
        self.backend = SQLiteSemanticIndex(database)
        self.writes: list[SemanticDocument] = []
        self.queries: list[SemanticQuery] = []
        self.deletes: list[str] = []

    def upsert(self, document: SemanticDocument) -> None:
        self.writes.append(document)
        self.backend.upsert(document)

    def delete(self, kind: SemanticKind, record_id: str, user_id: str) -> None:
        self.deletes.append(record_id)
        self.backend.delete(kind, record_id, user_id)

    def search(self, query: SemanticQuery) -> list[SemanticHit]:
        self.queries.append(query)
        return self.backend.search(query)


def memory(service: CompanionMemoryService):
    result = service.remember(
        MemoryInput(
            user_id="user",
            scope=SCOPE,
            kind=MemoryKind.SHARED_MOMENT,
            title="雨中的晚霞",
            content="那天下雨后看到了粉色晚霞",
            consent=ConsentState.GRANTED,
            explicit_user_request=True,
            embedding=[1.0, 0.0],
            embedding_space="fixture-v1",
        )
    )
    assert result.memory is not None
    return result.memory


def test_host_counter_is_used_and_named_in_context(service: CompanionMemoryService) -> None:
    counter = CharacterCounter()
    hosted = CompanionMemoryService(service.store, service.config, token_counter=counter)
    context = hosted.recall(
        RecallRequest(user_id="user", query="", max_tokens=service.config.retrieval.max_tokens)
    )
    assert counter.calls > 0
    assert context.rendered_tokens == len(context.prompt_text)
    assert context.tokenizer == "CharacterCounter"


def test_semantic_interface_is_used_for_write_search_delete(
    tmp_path: Path, config: CompanionConfig
) -> None:
    database = Database(tmp_path, config)
    database.initialize()
    index = RecordingSemanticIndex(database)
    service = CompanionMemoryService(MemoryStore(database, semantic_index=index), config)
    stored = memory(service)
    result = service.recall(
        RecallRequest(
            user_id="user",
            scope=SCOPE,
            query="日落时那片天空",
            query_embedding=[1.0, 0.0],
            embedding_space="fixture-v1",
        )
    )
    assert index.writes[0].id == stored.id
    assert index.writes[0].scope == SCOPE
    assert any(
        item.memory.id == stored.id for section in result.sections.values() for item in section
    )
    assert index.queries and index.queries[0].user_id == "user"
    query = SemanticQuery(
        kind=SemanticKind.MEMORY,
        user_id="user",
        scope=SCOPE,
        space="other-model",
        vector=[1.0, 0.0],
        as_of=datetime.now(UTC),
        limit=4,
        minimum_similarity=0,
    )
    assert index.search(query) == []
    service.purge(stored.id, "user")
    assert index.deletes == [stored.id]


def test_silent_influence_records_only_after_delivery_without_output_or_downweight(
    service: CompanionMemoryService,
) -> None:
    stored = memory(service)
    turn = service.append_turn(
        ConversationTurnInput(
            user_id="user",
            scope=SCOPE,
            actor_id="user",
            role=ConversationRole.USER,
            consent=ConsentState.GRANTED,
            content="今天也下雨了，我有点累",
        )
    ).turn
    assert turn is not None
    plan = service.plan_response(
        ResponsePlanRequest(
            user_id="user",
            scope=SCOPE,
            trigger_turn_id=turn.id,
            goal=ResponseGoal.COMFORT,
            recall_request=RecallRequest(user_id="user", scope=SCOPE, query="雨后的晚霞"),
            allow_follow_up=False,
            channel_supports_multiple_beats=False,
        )
    )
    decision = next(
        item for item in plan.memory_use_plan.decisions if item.evidence.id == stored.id
    )
    assert decision.mode is MemoryReferenceMode.SILENT_INFLUENCE
    assert service.list_memory_uses("user") == []
    receipt = ResponseBeatSentRequest(
        user_id="user",
        rendered_text="那就先歇一会儿，我听你说。",
        task_policy_version=plan.policy_version,
        silently_used_memory_ids=[stored.id],
    )
    service.mark_response_beat_sent(plan.id, plan.beats[0].id, receipt)
    service.mark_response_beat_sent(plan.id, plan.beats[0].id, receipt)
    uses = service.list_memory_uses("user")
    assert len(uses) == 1
    assert uses[0].use_type is MemoryUseType.SILENT_INFLUENCE
    assert uses[0].output_hash is None
    assert (
        service.store.used_memory_ids_since("user", SCOPE, [stored.id], None, datetime.now(UTC))
        == set()
    )
    assert service.store.memory_use_summaries("user", [stored.id])[0].use_count == 1


def test_legacy_use_types_and_v7_migration_preserve_data(service: CompanionMemoryService) -> None:
    stored = memory(service)
    use = service.record_memory_use(
        MemoryUseInput(
            user_id="user",
            scope=SCOPE,
            memory_id=stored.id,
            response_group_id="reply",
            use_mode=RecallUseMode.HEDGE,
            purpose="soft-context",
            rendered_excerpt="好像说起过晚霞",
        )
    )
    assert use.use_type is MemoryUseType.SOFT_REFERENCE
    database = service.store.database
    with database.connection() as connection:
        connection.executescript(
            "ALTER TABLE memory_use_events DROP COLUMN use_type; "
            "DROP TABLE turn_interpretations; DROP TABLE episodes; PRAGMA user_version = 7;"
        )
    database.initialize()
    database.initialize()
    assert service.store.get(stored.id, "user").content == stored.content
    migrated = service.list_memory_uses("user")[0]
    assert migrated.id == use.id
    assert migrated.use_type is MemoryUseType.SOFT_REFERENCE
    with database.connection() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == DATABASE_SCHEMA_VERSION
    database.integrity_check()
