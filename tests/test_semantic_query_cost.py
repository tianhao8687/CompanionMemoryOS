"""Scoped passage lookup must not repeatedly scan a whole embedding space."""

from datetime import UTC, datetime

import pytest

from companion_memoryos.schemas import (
    ConsentState,
    ConversationRole,
    ConversationTurnInput,
    MemoryScope,
    RealityLayer,
)
from companion_memoryos.semantic_index import SemanticDocument, SemanticKind, SemanticQuery


@pytest.mark.parametrize("upgrade_existing", [False, True])
def test_scoped_passage_search_work_grows_linearly(service, upgrade_existing):
    scope = MemoryScope(companion_id="cost", relationship_id="passages", conversation_id="seed")
    index = service.store.semantic_index
    sources = set()

    def seed(start, end):
        with service.store.database.atomic():
            for number in range(start, end):
                turn = service.append_turn(
                    ConversationTurnInput(
                        user_id="cost-user",
                        scope=scope,
                        actor_id="cost-user",
                        role=ConversationRole.USER,
                        content=f"Synthetic passage {number}.",
                        consent=ConsentState.GRANTED,
                    )
                ).turn
                assert turn
                sources.add(turn.id)
                index.upsert_passage(
                    SemanticDocument(
                        SemanticKind.TURN,
                        turn.id,
                        turn.user_id,
                        scope,
                        "cost-space",
                        [1.0, 0.0],
                        source_hash=turn.content_hash,
                    ),
                    0,
                    len(turn.content),
                )

    def measure():
        steps = 0

        def progress():
            nonlocal steps
            steps += 100
            return 0

        query = SemanticQuery(
            kind=SemanticKind.TURN,
            user_id="cost-user",
            scope=scope.model_copy(update={"conversation_id": "query"}),
            space="cost-space",
            vector=[1.0, 0.0],
            as_of=datetime.now(UTC),
            limit=8,
            minimum_similarity=0.5,
            reality_layer=RealityLayer.REAL_WORLD,
            include_relationship_turns=True,
            exclude_ids=["current-message"],
        )
        with service.store.database.connection() as db:
            db.set_progress_handler(progress, 100)
            try:
                hits = index.search(query)
            finally:
                db.set_progress_handler(None, 0)
        assert len(hits) == 8
        assert [hit.id for hit in hits] == sorted(sources)[:8]
        assert all(hit.similarity == 1.0 for hit in hits)
        return steps

    seed(0, 200)
    if upgrade_existing:
        # Simulate the preceding release's derived index on a populated database.
        with service.store.database.connection() as db:
            db.execute("DROP INDEX idx_turn_passages_lookup")
            db.execute(
                "CREATE INDEX idx_turn_passages_space ON turn_embedding_passages(space,dimensions)"
            )
        service.store.database.initialize()
    small = measure()
    seed(200, 400)
    large = measure()
    # VM instructions measure database work, not machine-specific wall time.
    assert small > 0 and large <= small * 2.6, (small, large)
