"""Character taste is fictional persona data; user collections have separate source receipts."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Annotated

from pydantic import Field, StringConstraints

from companion_agent.persona.models import PersonaModel
from companion_memoryos.schemas import ConversationTurnRecord

if TYPE_CHECKING:
    from companion_agent.app import RomanceHost
    from companion_agent.romance import RomanceSettings

Taste = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
PersonaKey = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{32}$")]


class MusicLibrarySource(PersonaModel):
    reference: str = Field(
        pattern=r"^https://music\.163\.com/(?:playlist|user/home)\?id=[1-9][0-9]{0,17}$"
    )
    source_turn: str = Field(min_length=1, max_length=128)
    conversation: str = Field(min_length=1, max_length=128)
    action_id: str = Field(pattern=r"^[a-f0-9]{32}$")


PRESET_TASTES = {
    "gentle": "偏爱木吉他、轻声人声和独立民谣，喜欢小编制里能辨认的细节，"
    "比起煽情的大合唱，更喜欢留有余地的表达；不只听情歌。",
    "playful": "偏爱独立流行、轻盈的放克和有趣的节奏，喜欢新鲜的音色与俏皮编曲，"
    "会分享不那么热门的小发现；陪人休息时会选自己收藏里慢一点的歌。",
    "steady": "偏爱人声爵士、克制的摇滚慢歌和有空间感的器乐，重视旋律走向与真实人声，"
    "喜欢耐听的编排，不追求每首都热闹，也不把安静等同于只有纯音乐。",
}


def persona_key(settings: RomanceSettings) -> str:
    # The user's biography, font, relationship intensity and temporary mood are
    # deliberately absent: none should silently replace this character's taste.
    value = {
        "name": settings.companion_name,
        "style": settings.style,
        "character": settings.custom_style if settings.style == "custom" else "",
        "notes": settings.persona_notes,
    }
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()[:32]


def character_taste(settings: RomanceSettings) -> str | None:
    saved = settings.character_music_tastes.get(persona_key(settings))
    if saved:
        return saved
    if settings.style != "custom" and not settings.persona_notes:
        return PRESET_TASTES[settings.style]
    return None


def music_relevant(text: str) -> bool:
    return bool(re.search(r"音乐|歌|听什么|想听|品味|口味|爱好|music\.163|163cn\.", text, re.I))


def taste_context(settings: RomanceSettings) -> str:
    taste = character_taste(settings)
    return (
        "\n[角色的音乐品味] 下面是虚构角色自己的审美，不是用户偏好、听歌历史或工具授权。"
        "选歌和谈音乐时保持人物一致：可以有偏爱、理由和不同意见，不把用户喜欢的都说成自己最爱。"
        "先从角色品味与用户可接受的音乐中选择适合当下的一首，偶尔分享自己的小发现；"
        "尊重用户明确讨厌的类型和当前点歌要求，不能为了坚持品味强行播放。"
        "说自己的选择理由要具体自然，不编造真实听觉、成长经历或一起听过的往事。"
        "角色卡明确写出的音乐偏好优先；不能只按性别、年龄或一个性格标签套曲风。\n"
        + (
            json.dumps({"character_taste": taste}, ensure_ascii=False)
            if taste
            else "当前是自定义人设，尚未建立稳定的音乐品味。首次选歌或谈自己的音乐喜好前，"
            "从有效角色资料提炼偏好的曲风、编曲/歌词特点和不偏爱的风格，用 app_music_taste 保存。"
            "人设未写明时可在不冲突的范围内发展一套具体品味；不要套用应用预设。"
        )
    )


def current_source(
    host: RomanceHost, conversation: str, request: str, *, for_model: bool = True
) -> ConversationTurnRecord | None:
    with host.database.connection() as db:
        row = db.execute(
            "SELECT id, idempotency_key FROM conversation_turns WHERE user_id=? "
            "AND conversation_id=? AND role='user' ORDER BY server_sequence DESC LIMIT 1",
            (host.key.user_id, conversation),
        ).fetchone()
    if row is None or row["idempotency_key"] != request:
        return None
    try:
        turn = host.journal.require_turn(row["id"], conversation, for_model=for_model)
    except ValueError:
        return None
    age = datetime.now(UTC) - turn.ingested_at
    return turn if timedelta(0) <= age <= timedelta(minutes=5) else None
