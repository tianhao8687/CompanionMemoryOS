from __future__ import annotations

from companion_memoryos.schemas import (
    ConsentState,
    EmotionSignal,
    MemoryInput,
    MemoryKind,
    RecallIntent,
    RecallRequest,
)
from companion_memoryos.service import CompanionMemoryService


def activate(
    service: CompanionMemoryService,
    kind: MemoryKind,
    title: str,
    content: str,
    **extra: object,
) -> None:
    service.remember(
        MemoryInput.model_validate(
            {
                "user_id": "alice",
                "kind": kind,
                "title": title,
                "content": content,
                "consent": ConsentState.GRANTED,
                "explicit_user_request": True,
                **extra,
            }
        )
    )


def test_boundary_is_pinned_even_when_character_budget_is_tiny(
    service: CompanionMemoryService,
) -> None:
    activate(service, MemoryKind.BOUNDARY, "边界", "不要用宝贝称呼我")
    activate(service, MemoryKind.SHARED_MOMENT, "散步", "我们聊过雨后的公园")
    context = service.recall(RecallRequest(user_id="alice", query="公园", max_characters=1))
    boundary = context.sections["boundaries"][0]
    assert boundary.pinned is True
    assert context.safety_budget_exceeded is True


def test_emotion_match_is_explained(service: CompanionMemoryService) -> None:
    emotion = EmotionSignal(label="焦虑", intensity=0.8, valence=-0.6, arousal=0.8)
    activate(
        service,
        MemoryKind.EMOTION_EPISODE,
        "演讲前",
        "演讲前会紧张，先陪我做呼吸练习",
        emotions=[emotion.model_dump()],
    )
    context = service.recall(
        RecallRequest(
            user_id="alice",
            intent=RecallIntent.COMFORT,
            emotions=[emotion],
        )
    )
    recalled = context.sections["emotional_context"][0]
    assert recalled.score.emotion > 0
    assert "emotion_match" in recalled.reasons


def test_recall_never_crosses_user_scope(service: CompanionMemoryService) -> None:
    activate(service, MemoryKind.IDENTITY, "城市", "我住在杭州")
    context = service.recall(RecallRequest(user_id="bob", query="杭州"))
    assert context.sections == {}


def test_old_boundary_survives_a_current_time_phrase(
    service: CompanionMemoryService,
) -> None:
    activate(service, MemoryKind.BOUNDARY, "安慰边界", "难过时不要立刻给建议")

    context = service.recall(RecallRequest(user_id="alice", query="今天有点难过"))

    assert context.sections["boundaries"][0].memory.content == "难过时不要立刻给建议"
