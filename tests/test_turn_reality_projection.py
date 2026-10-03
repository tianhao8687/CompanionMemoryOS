"""The indexed reality projection follows its authoritative source transaction."""

import json
import sqlite3

import pytest

from companion_memoryos.database import Database
from companion_memoryos.schemas import (
    ConversationTurnInput,
    MemoryScope,
    RealityLayer,
    RecallRequest,
)
from companion_memoryos.turn_layers import turn_reality_layer


def source(service, **changes):
    return service.append_turn(
        ConversationTurnInput.model_validate(
            {
                "user_id": "owner",
                "actor_id": "owner",
                "scope": MemoryScope(
                    companion_id="guide", relationship_id="one", conversation_id="c"
                ),
                "role": "user",
                "content": "图书馆的蓝色藏书柜",
                "consent": "granted",
                **changes,
            }
        )
    ).turn


def check_projection(service, turn):
    with service.store.database.connection() as connection:
        row = connection.execute(
            "SELECT * FROM conversation_turns WHERE id=?", (turn.id,)
        ).fetchone()
    expected = turn_reality_layer(row["content"], row["metadata_json"], row["speech_spans_json"])
    assert row["reality_layer"] == expected
    for layer in (RealityLayer.REAL_WORLD, RealityLayer.FICTION):
        result = service.recall(
            RecallRequest(
                user_id="owner", scope=turn.scope, query="蓝色藏书柜", state_reality_layer=layer
            )
        )
        assert (turn.id in {item.turn.id for item in result.turn_fallback}) == (
            layer.value == expected
        )


@pytest.mark.parametrize("layer", ["real_world", "fiction", "quote", "roleplay"])
def test_declared_projection_is_initialized_with_source(service, layer):
    turn = source(service, metadata={"process_reality_layer": layer})
    check_projection(service, turn)


def test_projection_changes_with_metadata_and_rolls_back_together(service):
    turn = source(service)
    with service.store.database.atomic() as connection:
        connection.execute(
            "UPDATE conversation_turns SET metadata_json=? WHERE id=?",
            (json.dumps({"process_reality_layer": "fiction"}), turn.id),
        )
    check_projection(service, turn)
    with (
        pytest.raises(RuntimeError, match="abort"),
        service.store.database.atomic() as connection,
    ):
        connection.execute(
            "UPDATE conversation_turns SET metadata_json='{}' WHERE id=?", (turn.id,)
        )
        check_projection(service, turn)
        raise RuntimeError("abort")
    check_projection(service, turn)
    assert service.store.get_turn(turn.id, "owner").metadata["process_reality_layer"] == "fiction"


def test_projection_changes_when_full_span_becomes_partial_and_after_redaction(service):
    content = "图书馆的蓝色藏书柜"
    turn = source(
        service,
        speech_spans=[
            {
                "start_offset": 0,
                "end_offset": len(content),
                "reality_layer": "fiction",
                "machine_generated": False,
            }
        ],
    )
    check_projection(service, turn)
    with service.store.database.atomic() as connection:
        connection.execute(
            "UPDATE conversation_turns SET content=? WHERE id=?",
            (content + "。现实补充。", turn.id),
        )
    check_projection(service, turn)
    service.store.redact_turn(turn.id, "owner", [(len(content), len(content) + 6)])
    check_projection(service, turn)


def remove_projection(database):
    with database.connection() as connection:
        connection.executescript("""
            DROP TRIGGER turns_reality_insert;
            DROP TRIGGER turns_reality_update;
            DROP INDEX idx_turns_reality_scope;
            ALTER TABLE conversation_turns DROP COLUMN reality_layer;
            PRAGMA user_version=8;
        """)


def test_v8_migration_backfills_source_layers_and_survives_reopen(service):
    real = source(service)
    fictional = source(service, metadata={"process_reality_layer": "fiction"})
    database = service.store.database
    remove_projection(database)
    reopened = Database(database.data_dir, service.config)
    reopened.initialize()
    check_projection(service, real)
    check_projection(service, fictional)
    reopened.initialize()
    check_projection(service, fictional)
    reopened.integrity_check()


def test_interrupted_projection_backfill_retries_before_advancing_schema(service, monkeypatch):
    fictional = source(service, metadata={"process_reality_layer": "fiction"})
    database = service.store.database
    remove_projection(database)
    original = database._open_connection

    def faulty_connection():
        connection = original()

        def fail(*args):
            raise RuntimeError("injected interrupted projection migration")

        connection.create_function("companion_turn_reality", 3, fail, deterministic=True)
        return connection

    with monkeypatch.context() as patch:
        patch.setattr(database, "_open_connection", faulty_connection)
        with pytest.raises(sqlite3.OperationalError):
            database.initialize()
    with database.connection() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 8
    database.initialize()
    check_projection(service, fictional)
