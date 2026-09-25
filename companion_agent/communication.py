"""Validated projections of communication preferences from the existing memory store.

Scope/quotation/negation use the shared discourse parser. A small compositional
operator/object grammar maps direct requests to a closed set of behavior settings;
unrecognized language stays evidence for the main model, never arbitrary instructions.
There is no second preference database and no extra model call.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from companion_agent.evidence_policy import restricted_evidence
from companion_memoryos.discourse import NONASSERTIVE, direct_clauses
from companion_memoryos.schemas import (
    ExperienceEvidenceKind,
    ExperienceEvidenceRef,
    MemoryKind,
    MemoryScope,
    MemoryStatus,
    RealityLayer,
)

if TYPE_CHECKING:
    from companion_agent.relationship import RelationshipKey, RelationshipService
    from companion_memoryos.service import CompanionMemoryService


@dataclass(frozen=True)
class CommunicationPreference:
    original: str
    dimension: str
    value: str
    lifetime: str = "durable"

    def valid_until(self, at: datetime, timezone: str) -> datetime | None:
        if self.lifetime == "today":
            return (
                (at.astimezone(ZoneInfo(timezone)) + timedelta(days=1))
                .replace(hour=0, minute=0, second=0, microsecond=0)
                .astimezone(UTC)
            )
        if self.lifetime in {"conversation", "turn"}:
            return at + timedelta(hours=8)
        return None


OBJECTS = {
    "psychological_analysis": re.compile(
        r"(?:被)?(?:心理分析|情绪分析|分析|解读|揣测|剖析|猜测)"
        r"(?:我(?:的)?(?:情绪|心理|内心|心思|想法)?|用户的情绪)?"
    ),
    "questions": re.compile(r"(?:被)?(?:反问|追问|问|提问)(?:我|问题|我的感受)?"),
    "advice": re.compile(r"(?:给我|给|提|提供)?(?:建议|方案|说教)(?:我)?"),
}
PREFIX = re.compile(
    r"^(?:(?:从现在起|以后|今后|平时|一直|今天|今日|这次|这一轮|暂时|现在|先|请你|请|"
    r"我希望你|我想让你|我希望|希望你|麻烦你|并且|而且|也|还|你|我)\s*)+"
)
MODIFIERS = re.compile(r"^(?:(?:主动|总是|总|一直|老是|老|动不动|一开口就|再|随便|马上|急着)\s*)+")
OPERATOR = re.compile(
    r"^(不喜欢|不爱|讨厌|不想要|不想被|不想|不需要|不要|不用|别|少|可以|允许|多)(.+)$"
)


def communication_preferences(text: str) -> list[CommunicationPreference]:
    preferences: list[CommunicationPreference] = []
    cursor = 0
    previous: CommunicationPreference | None = None
    for accepted in direct_clauses(text):
        clause = accepted.rstrip("？?").strip()
        start = text.find(clause, cursor)
        joined = bool(
            previous
            and start >= cursor
            and re.fullmatch(r"\s*[,，]\s*", text[cursor:start])
            and re.match(r"也|并且|而且|还", clause)
        )
        inherited_lifetime = previous.lifetime if joined and previous else "durable"
        # A local pause governs the following request even when the first clause
        # describes a short pause rather than a preference.
        sentence_prefix = re.split(r"[。！!?？；;\n]", text[: max(0, start)])[-1]
        if re.search(
            r"(?:先|现在|想).{0,12}(?:静|缓|歇|待).{0,5}(?:几分钟|[一二三四五六七八九十\d]+分钟|一会儿)",
            sentence_prefix,
        ):
            inherited_lifetime = "turn"
        cursor = start + len(clause) if start >= 0 else cursor
        previous = None
        if (
            NONASSERTIVE.search(clause)
            or re.search(r"曾经|以前|过去|小时候|上周|他说|她说|你说|我说过", clause)
            or re.search(r"不是不|并非不|不能不|没说|没有说", clause)
            or re.search(re.escape(clause) + r"[？?]", text)
            or clause.endswith(("吗", "么"))
        ):
            continue
        lifetime = (
            "today"
            if re.search(r"今天|今日", clause)
            else "turn"
            if re.search(r"这次|这一轮", clause)
            else "conversation"
            if re.search(r"暂时|先", clause)
            else inherited_lifetime
        )
        body = PREFIX.sub("", clause)
        if re.search(r"以后|今后|从现在起", clause):
            lifetime = "durable"
            if re.fullmatch(r"听我(?:说|讲)(?:完)?", body):
                preferences.append(CommunicationPreference(clause, "advice", "reduce", lifetime))
                previous = preferences[-1]
                continue
        if re.fullmatch(r"(?:回复|回答|说话)(?:请)?(?:短|简短|简洁)(?:点|一点|一些)?", body):
            preferences.append(CommunicationPreference(clause, "length", "concise", lifetime))
            previous = preferences[-1]
            continue
        match = OPERATOR.fullmatch(body)
        if not match:
            continue
        operator, target = match.groups()
        target = MODIFIERS.sub("", target)
        target = re.sub(r"(?:了|一点|一些|个不停)$", "", target)
        if operator == "不想被":
            target = "被" + target
        for dimension, pattern in OBJECTS.items():
            if pattern.fullmatch(target):
                value = "allow" if operator in {"可以", "允许", "多"} else "reduce"
                preferences.append(CommunicationPreference(clause, dimension, value, lifetime))
                previous = preferences[-1]
                break
    return preferences


GUIDANCE = {
    ("psychological_analysis", "reduce"): "避免主动解读用户的心理、情绪或深层动机；"
    "本轮明确请求心理分析时可按请求分析，分析报告等其他任务正常完成。",
    ("psychological_analysis", "allow"): "用户允许心理分析；仍需根据当前请求与证据，保留不确定性。",
    (
        "questions",
        "reduce",
    ): "减少无必要的追问，自然接话；合适的好奇、必要澄清和用户要求的访谈仍可提问，"
    "避免每轮固定用问题收尾。",
    ("questions", "allow"): "用户允许较多互动提问；按当前话题需要决定，不机械连续发问。",
    ("advice", "reduce"): "减少主动建议，先参与用户分享；贴合语境的轻量关心可以自然表达，"
    "用户本轮明确求方案或建议时，完成其任务。",
    ("advice", "allow"): "用户愿意听建议，结合当前请求提供实际帮助。",
    ("length", "concise"): "日常聊天倾向简洁；认真任务按需要给足内容。",
}


def preference_rules(entries: list[dict[str, Any]]) -> str:
    rules = list(
        dict.fromkeys(
            GUIDANCE[(entry["dimension"], entry["value"])]
            for entry in entries
            if (entry["dimension"], entry["value"]) in GUIDANCE
        )
    )
    if not rules:
        return ""
    return (
        "\n[VALIDATED COMMUNICATION SETTINGS]\n"
        "这些是交流倾向，结合当下语境灵活执行；明确拒绝、隐私和同意边界仍须尊重。\n"
        + "\n".join(rules)
    )


def project_preferences(
    memory: CompanionMemoryService,
    relationships: RelationshipService,
    key: RelationshipKey,
    scope: MemoryScope,
    at: datetime,
    *,
    current_turn_id: str | None = None,
    current_text: str = "",
    allow_sensitive: bool = False,
) -> list[dict[str, Any]]:
    records = memory.store.list_memories(key.user_id, {MemoryStatus.ACTIVE}, scope=scope)
    records = [
        r
        for r in records
        if r.kind in {MemoryKind.PREFERENCE, MemoryKind.SUPPORT_STRATEGY}
        and r.reality_layer is RealityLayer.REAL_WORLD
        and r.evidence_turn_ids
        and r.scope.companion_id == scope.companion_id
        and r.scope.relationship_id == scope.relationship_id
        and r.scope.group_id == scope.group_id
        and r.scope.conversation_id in {None, scope.conversation_id}
    ]
    refs = [ExperienceEvidenceRef(kind=ExperienceEvidenceKind.MEMORY, id=r.id) for r in records]
    refs += [
        ExperienceEvidenceRef(kind=ExperienceEvidenceKind.TURN, id=t)
        for r in records
        for t in r.evidence_turn_ids
    ]
    blocked = restricted_evidence(memory, key, refs, at, conversation_id=scope.conversation_id)
    chosen: dict[str, dict[str, Any]] = {}
    for record in sorted(records, key=lambda r: (r.event_at, r.created_at)):
        if (
            f"memory:{record.id}" in blocked
            or any(f"turn:{t}" in blocked for t in record.evidence_turn_ids)
            or not relationships.evidence_valid(
                key, f"memory:{record.id}", at, allow_sensitive=allow_sensitive
            )
            or record.valid_time_start > at
            or (record.valid_time_end is not None and record.valid_time_end <= at)
        ):
            continue
        source_texts = [
            memory._direct_user_discourse_text(memory.store.get_turn(t, key.user_id))
            for t in record.evidence_turn_ids
        ]
        source_settings = [s for text in source_texts for s in communication_preferences(text)]
        for stored in communication_preferences(record.content):
            # Reparse the full source so a joined clause keeps its inherited time scope.
            setting = next(
                (
                    s
                    for s in source_settings
                    if (s.original, s.dimension, s.value)
                    == (stored.original, stored.dimension, stored.value)
                ),
                None,
            )
            if setting is None:
                continue
            if setting.lifetime == "turn" and current_turn_id not in record.evidence_turn_ids:
                continue
            if (
                setting.lifetime == "conversation"
                and record.scope.conversation_id != scope.conversation_id
            ):
                continue
            chosen[setting.dimension] = {
                **asdict(setting),
                "memory_id": record.id,
                "source_turn_ids": record.evidence_turn_ids,
                "scope": record.scope.model_dump(mode="json"),
                "valid_until": record.valid_time_end.isoformat() if record.valid_time_end else None,
                "supersedes_id": record.supersedes_id,
            }
    # Current explicit restrictions apply even when long-term extraction is disabled.
    for setting in communication_preferences(current_text):
        existing = chosen.get(setting.dimension)
        if (
            existing
            and current_turn_id in existing["source_turn_ids"]
            and existing["original"] == setting.original
        ):
            existing["authority"] = "current_turn_and_stored_preference"
            continue
        chosen[setting.dimension] = {
            **asdict(setting),
            "memory_id": None,
            "source_turn_ids": [current_turn_id] if current_turn_id else [],
            "scope": scope.model_dump(mode="json"),
            "valid_until": None,
            "authority": "current_turn",
        }
    return list(chosen.values())


def preference_evidence(entries: list[dict[str, Any]]) -> str:
    return "[COMMUNICATION EVIDENCE]\n" + json.dumps(
        entries, ensure_ascii=False, separators=(",", ":")
    )
