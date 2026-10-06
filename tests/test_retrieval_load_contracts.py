"""Source recall under competing lexical and semantic evidence, with real storage."""

from __future__ import annotations

import math
import time

import pytest

from companion_agent.testing.memory_load import Workload, make_memory
from companion_memoryos.schemas import ConversationTurnInput, MemoryScope, RecallRequest
from companion_memoryos.turn_layers import turn_reality_layer


def test_complementary_cue_cannot_displace_more_complete_literal_evidence():
    from companion_memoryos.config import load_config
    from companion_memoryos.scoring import complementary_evidence_order

    assert complementary_evidence_order(
        "alpha beta gamma storage location?",
        [
            "alpha beta gamma storage: first account",
            "alpha beta gamma storage: another independent account",
            "unrelated location mention",
        ],
        load_config(),
    ) == [0, 1, 2]


def test_hash_channel_cannot_drown_out_multiple_exact_source_matches(tmp_path):
    workload = Workload(tmp_path, 20261003, time.monotonic() + 60)
    try:
        workload.seed_to(1000)
        summary = workload.read_phase(32, 1, "hash")
        assert summary["errors"] == 0
        assert summary["wrong_scope"] == 0
        assert summary["quality"]["multi"]["all_evidence_at_6"] == 1.0
        assert summary["quality"]["single"]["all_evidence_at_6"] == 1.0
    finally:
        workload.memory.close_indexer()


@pytest.mark.parametrize("mode", ["fts", "hash"])
def test_realm_filter_does_not_decode_every_stored_turn_for_each_read(tmp_path, mode):
    workload = Workload(tmp_path, 7719, time.monotonic() + 60)
    try:
        workload.seed_to(1000)
        calls = 0

        def counted_layer(content, metadata, spans):
            nonlocal calls
            calls += 1
            return turn_reality_layer(content, metadata, spans)

        with workload.database.connection() as connection:
            connection.create_function(
                "companion_turn_reality", 3, counted_layer, deterministic=True
            )
            result = workload.query([0], mode)
        assert result["status"] == "completed"
        assert result["answer_spans_complete"]
        # Candidate revalidation is allowed; a whole-history Python/JSON scan is not.
        assert calls < 3 * workload.memory.config.retrieval.turn_candidate_pool
    finally:
        workload.memory.close_indexer()


def test_scoped_fts_uses_index_order_instead_of_sorting_all_matching_history(tmp_path):
    workload = Workload(tmp_path, 1945, time.monotonic() + 60)
    try:
        workload.seed_to(100)
        sql = []
        with workload.database.connection() as connection:
            connection.set_trace_callback(sql.append)
            result = workload.query([0], "fts")
            connection.set_trace_callback(None)
            queries = [statement for statement in sql if "AND turn_fts MATCH" in statement]
            assert queries
            for statement in queries:
                plan = connection.execute("EXPLAIN QUERY PLAN " + statement).fetchall()
                assert not any("TEMP B-TREE FOR ORDER BY" in row[3] for row in plan)
        assert result["answer_spans_complete"]
        assert not result["wrong_scope"]
    finally:
        workload.memory.close_indexer()


@pytest.mark.parametrize("long_similarity", [0.65, 0.05])
def test_lexical_candidates_outside_vector_top_k_keep_their_actual_similarity(
    tmp_path, long_similarity
):
    memory = make_memory(tmp_path)
    scope = MemoryScope(companion_id="guide", relationship_id="one", conversation_id="c")
    gold = {}
    try:
        with memory.store.database.session():
            for key in ("alpha", "beta", "gamma", "delta"):
                text = f"The storage location for {key} is cabinet {key}-43."
                if key == "delta":
                    text = "Ordinary archive housekeeping log. " * 20 + text
                similarity = long_similarity if key == "delta" else 0.65
                turn = memory.append_turn(
                    ConversationTurnInput(
                        user_id="owner",
                        actor_id="owner",
                        role="user",
                        scope=scope,
                        content=text,
                        consent="granted",
                        embedding=[similarity, math.sqrt(1 - similarity**2)],
                        embedding_space="controlled-cosine",
                    )
                ).turn
                gold[turn.id] = similarity if similarity >= 0.2 else 0.0
            for number in range(80):
                memory.append_turn(
                    ConversationTurnInput(
                        user_id="owner",
                        actor_id="owner",
                        role="user",
                        scope=scope,
                        content=f"General storage housekeeping record {number}.",
                        consent="granted",
                        embedding=[0.8, 0.6],
                        embedding_space="controlled-cosine",
                    )
                )
            context = memory.recall(
                RecallRequest(
                    user_id="owner",
                    scope=scope,
                    query="alpha beta gamma delta storage locations?",
                    query_embedding=[1.0, 0.0],
                    embedding_space="controlled-cosine",
                    include_turn_evidence=True,
                    answer_cardinality="open",
                    turn_limit=6,
                )
            )
        by_id = {item.turn.id: item for item in context.turn_fallback}
        assert gold.keys() <= by_id.keys()
        assert all(
            by_id[identifier].semantic == pytest.approx(score) for identifier, score in gold.items()
        )
        assert all(
            item.recall_confidence == max(item.lexical, item.semantic, item.temporal)
            for item in by_id.values()
        )
    finally:
        memory.close_indexer()
