"""20 synthetic Chinese conversations, 32 messages each; no external LLM judge.

Each replay checks the final answer's evidence contract, attribution and unknown-state
handling. Canned model proposals exercise the bridge, not model extraction accuracy.
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from companion_memoryos.schemas import (
    AnswerCardinality,
    AnswerSemantics,
    ConsentState,
    ConversationRole,
    ConversationTurnInput,
    MemoryCandidate,
    MemoryKind,
    MemoryScope,
    RecallRequest,
    ResolutionStatus,
    TurnInterpretation,
    TurnInterpretationRequest,
)
from companion_memoryos.service import CompanionMemoryService


@dataclass(frozen=True)
class Scene:
    name: str
    dialogue: str
    target: str
    query: str


SCENES = [
    Scene(
        name=raw["name"], dialogue="|".join(raw["turns"]), target=raw["target"], query=raw["query"]
    )
    for raw in json.loads(
        (Path(__file__).parent / "fixtures" / "conversation_replays_0_7.json").read_text(
            encoding="utf-8"
        )
    )
]


@pytest.mark.parametrize("scene", SCENES, ids=lambda scene: scene.name)
def test_chat_replay_final_evidence_and_attribution(
    service: CompanionMemoryService, scene: Scene
) -> None:
    messages = scene.dialogue.split("|")
    assert len(messages) == 16
    scope = MemoryScope(
        companion_id="companion", relationship_id=scene.name, conversation_id="daily-chat"
    )
    started = datetime.now(UTC) - timedelta(days=180)
    target = None
    assistant_target = None
    for index, content in enumerate(messages):
        at = started + timedelta(days=index * 7)
        user = service.append_turn(
            ConversationTurnInput(
                user_id="user",
                actor_id="user",
                scope=scope,
                role=ConversationRole.USER,
                consent=ConsentState.GRANTED,
                content=content,
                occurred_at=at,
                idempotency_key=f"user-{index}",
            )
        ).turn
        assert user is not None
        if content == scene.target:
            target = user
            if scene.name != "small_unextracted_event":
                record = service.apply_turn_interpretation(
                    user.id,
                    TurnInterpretationRequest(
                        user_id="user",
                        scope=scope,
                        idempotency_key="canned-model-output",
                        model_fingerprint="replay-fixture-not-a-real-model",
                        model_output=TurnInterpretation(
                            topics=[scene.query],
                            memory_candidates=[
                                MemoryCandidate(
                                    kind=MemoryKind.SHARED_MOMENT,
                                    title=scene.name,
                                    content=scene.target,
                                ),
                            ],
                        ),
                    ),
                )
                assert service.store.get(record.memory_ids[0], "user").evidence_turn_ids == [
                    target.id
                ]
        assistant = service.append_turn(
            ConversationTurnInput(
                user_id="user",
                actor_id="companion",
                scope=scope,
                role=ConversationRole.ASSISTANT,
                consent=ConsentState.GRANTED,
                content=f"你说：{content}。我先听着。",
                occurred_at=at + timedelta(minutes=1),
                idempotency_key=f"assistant-{index}",
            )
        ).turn
        if content == scene.target:
            assistant_target = assistant
    assert target is not None and assistant_target is not None
    assert len(service.list_turns("user", scope)) == 32
    context = service.recall(
        RecallRequest(
            user_id="user",
            scope=scope,
            query=scene.query,
            turn_limit=6,
            answer_semantics=AnswerSemantics.UTTERANCE_HISTORY,
            answer_cardinality=AnswerCardinality.MULTI,
            utterance_actor_id="user",
        )
    )
    evidence = {item.turn.id: item.evidence_text for item in context.turn_fallback}
    assert target.id in evidence
    assert scene.target in evidence[target.id]
    assert scene.target in context.prompt_text
    assert assistant_target.id not in evidence
    assert all(item.turn.actor_id == "user" for item in context.turn_fallback)
    assert context.rendered_tokens <= context.token_budget
    unknown = service.recall(
        RecallRequest(
            user_id="user",
            scope=scope,
            query="我内心真正的感情是什么？",
            answer_semantics=AnswerSemantics.STATE_AT_VALID_TIME,
            state_predicate="unreported_inner_feeling",
        )
    )
    assert unknown.state_result is not None
    assert unknown.state_result.resolution_status is ResolutionStatus.UNKNOWN
    assert unknown.state_result.memories == []
