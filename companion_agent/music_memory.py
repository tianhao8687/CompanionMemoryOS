"""Grounded listening moments use the existing memory and source lifecycle."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from companion_agent.memory_language import SENSITIVE, forget_target, memory_note
from companion_memoryos.discourse import NONASSERTIVE, OTHER_SUBJECT, direct_clauses
from companion_memoryos.schemas import (
    ConsentState,
    ConversationRole,
    ConversationTurnRecord,
    MemoryCorrectionRequest,
    MemoryInput,
    MemoryKind,
    MemoryStatus,
    RealityLayer,
    Sensitivity,
    TurnDeletionState,
)

if TYPE_CHECKING:
    from companion_agent.cognition import ApplicationMemory


MUSIC_REFERENCE = re.compile(r"这首(?:歌|曲子)?(?!诗)|这支歌|这歌|这段(?:旋律|音乐)")
NO_MEMORY = re.compile(r"(?:别|不要|不用|不必).{0,12}(?:记住|记下|记录|保存)")
REQUEST = re.compile(r"帮我|替我|找一下|搜一下|搜索|播放|切歌|下一首|上一首|暂停")
CORRECTION = re.compile(r"刚才(?:我)?(?:说错|记错)了|更正一下|纠正一下")


def listening_share(text: str, title: str) -> bool:
    """Only a literal remark tied to this song; no inference from playing or lyrics."""
    if (
        len(text) > 2000
        or SENSITIVE.search(text)
        or NO_MEMORY.search(text)
        or forget_target(text)
        or re.search(r"[?？]", text)
    ):
        return False
    for clause in direct_clauses(text):
        if (
            "[引用]" in clause
            or NONASSERTIVE.search(clause)
            or OTHER_SUBJECT.search(clause)
            or clause.startswith("你")
            or re.search(r"[?？]|(?:吗|么|呢)$", clause)
            or REQUEST.search(clause)
            or re.search(r"歌词(?:是|写|说|里)|台词|小说|扮演|假装|不是这首|另一首", clause)
        ):
            continue
        named = f"《{title}》" in clause or (
            title in clause and re.search(r"听|歌|唱|版本", clause)
        )
        if (MUSIC_REFERENCE.search(clause) or named) and re.search(
            r"我|喜欢|不喜欢|好听|难听|想起|记得|回忆|听过|记住|记下", clause
        ):
            return True
    return False


def remember_listening(
    memory: ApplicationMemory, turn: ConversationTurnRecord, track: dict[str, str]
) -> bool:
    if (
        turn.role is not ConversationRole.USER
        or turn.actor_id != turn.user_id
        or turn.metadata.get("process_reality_layer", "real_world") != RealityLayer.REAL_WORLD.value
        or turn.consent is not ConsentState.GRANTED
        or turn.sensitivity is not Sensitivity.NORMAL
        or turn.deletion_state is not TurnDeletionState.ACTIVE
    ):
        return False
    direct = memory._direct_user_discourse_text(turn).strip()
    if not listening_share(direct, track["title"]):
        return False
    # The content remains the original utterance. Player metadata is separately
    # attributed and never rewritten into something the user supposedly said.
    records = memory.store.list_memories(turn.user_id, {MemoryStatus.ACTIVE}, scope=turn.scope)
    if any(
        turn.id in item.evidence_turn_ids and item.metadata.get("shared_listening")
        for item in records
    ):
        return True
    if CORRECTION.search(direct):
        previous = [
            item
            for item in records
            if isinstance(item.metadata.get("shared_listening"), dict)
            and item.metadata["shared_listening"].get("session_id") == track["session_id"]
            and item.metadata["shared_listening"].get("track_key") == track["track_key"]
        ]
        previous.sort(key=lambda item: item.event_at, reverse=True)
        if previous:
            correction = memory.correct(
                previous[0].id,
                MemoryCorrectionRequest(
                    user_id=turn.user_id,
                    content=turn.content,
                    event_at=turn.occurred_at,
                    source_ref=f"turn:{turn.id}",
                    source_excerpt=turn.content,
                    evidence_turn_ids=[turn.id],
                ),
            )
            return correction.memory is not None
    result = memory.remember(
        MemoryInput(
            user_id=turn.user_id,
            scope=turn.scope.model_copy(update={"conversation_id": None}),
            kind=MemoryKind.SHARED_MOMENT,
            title=f"一起听《{track['title']}》·{track['artist']}时的分享"[:240],
            content=turn.content,
            stable_key=f"listening:{turn.id}",
            consent=turn.consent,
            sensitivity=turn.sensitivity,
            explicit_user_request=memory_note(direct) is not None,
            salience=0.6,
            event_at=turn.occurred_at,
            evidence_turn_ids=[turn.id],
            source_ref=f"turn:{turn.id}",
            source_excerpt=turn.content,
            metadata={"shared_listening": track, "quoted_material_reference": True},
        )
    )
    if result.memory is None:
        return False
    if result.memory.status is MemoryStatus.CANDIDATE:
        memory._adopt(result.memory, "attributed_listening_share")
    return True
