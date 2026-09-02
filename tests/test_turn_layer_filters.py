import json
from datetime import UTC, datetime

from companion_memoryos.schemas import (
    ConversationTurnInput,
    MemoryScope,
    RealityLayer,
    RecallRequest,
    SpeechSpan,
)
from companion_memoryos.semantic_index import SemanticKind, SemanticQuery, SQLiteSemanticIndex
from companion_memoryos.turn_layers import turn_reality_layer


def test_full_span_coverage_not_first_span_determines_legacy_turn_layer():
    spans = [
        {"start_offset": 0, "end_offset": 2, "reality_layer": "roleplay"},
        {"start_offset": 2, "end_offset": 4, "reality_layer": "roleplay"},
    ]
    assert turn_reality_layer("剧情台词", "{}", json.dumps(spans)) == "roleplay"
    spans[1]["start_offset"] = 3
    assert turn_reality_layer("剧情台词", "{}", json.dumps(spans)) == "real_world"
    assert turn_reality_layer("剧情台词", '{"process_reality_layer":"fiction"}', "[]") == "fiction"
    assert turn_reality_layer("剧情台词", "{}", "[]") == "real_world"
    spans[0]["reality_layer"] = "real_world"
    assert turn_reality_layer("剧情台词", "{}", json.dumps(spans)) == "real_world"


def test_sqlite_semantic_filter_matches_lexical_realm_filter(service):
    scope = MemoryScope(companion_id="ai", relationship_id="rel", conversation_id="chat")
    real = service.append_turn(
        ConversationTurnInput(
            user_id="user",
            scope=scope,
            actor_id="user",
            role="user",
            content="现实里的蓝色杯子",
            consent="granted",
            embedding=[1.0, 0.0],
            embedding_space="fixture",
        )
    ).turn
    content = "剧情里的蓝色杯子"
    imaginary = service.append_turn(
        ConversationTurnInput(
            user_id="user",
            scope=scope,
            actor_id="user",
            role="user",
            content=content,
            consent="granted",
            embedding=[1.0, 0.0],
            embedding_space="fixture",
            speech_spans=[
                SpeechSpan(
                    start_offset=0,
                    end_offset=len(content),
                    reality_layer=RealityLayer.ROLEPLAY,
                    machine_generated=False,
                )
            ],
        )
    ).turn
    index = SQLiteSemanticIndex(service.store.database)
    for layer, expected in [(RealityLayer.REAL_WORLD, real), (RealityLayer.ROLEPLAY, imaginary)]:
        hits = index.search(
            SemanticQuery(
                kind=SemanticKind.TURN,
                user_id="user",
                scope=scope,
                vector=[1.0, 0.0],
                space="fixture",
                as_of=datetime.now(UTC),
                limit=10,
                minimum_similarity=0,
                reality_layer=layer,
            )
        )
        assert {hit.id for hit in hits} == {expected.id}
        recalled = service.recall(
            RecallRequest(
                user_id="user",
                scope=scope,
                query="蓝色杯子",
                state_reality_layer=layer,
            )
        )
        assert {item.turn.id for item in recalled.turn_fallback} == {expected.id}
