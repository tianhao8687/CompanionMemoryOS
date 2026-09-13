"""Conservative local evidence-to-candidate adapter; never invents milestones from volume."""

from __future__ import annotations

import calendar
import hashlib
import re
from datetime import datetime
from typing import Protocol

from companion_agent.relationship.models import (
    EvidenceStrength,
    RelationshipModel,
    RelationshipUpdateCandidate,
    RelationshipUpdateKind,
)
from companion_agent.relationship.service import RelationshipService, candidate_for
from companion_memoryos.schemas import MemoryKind, ProcessTurnResult

TECH_TOPICS = ["技术", "电脑", "显卡", "代码", "硬件", "rtx", "python", "方案"]


class RelationshipEvaluator(Protocol):
    def evaluate(
        self, result: ProcessTurnResult, model: RelationshipModel, service: RelationshipService
    ) -> list[RelationshipUpdateCandidate]: ...


def _months_before(at: datetime, months: int) -> datetime:
    year, month_index = divmod(at.year * 12 + at.month - 1 - months, 12)
    month = month_index + 1
    return at.replace(year=year, month=month, day=min(at.day, calendar.monthrange(year, month)[1]))


class LocalRelationshipEvaluator:
    def evaluate(
        self, result: ProcessTurnResult, model: RelationshipModel, service: RelationshipService
    ) -> list[RelationshipUpdateCandidate]:
        turn = result.storage.turn
        if turn is None or result.response_stale:
            return []
        ref = f"turn:{turn.id}"
        if not service.evidence_valid(model.key, ref, turn.occurred_at):
            return []
        # Only direct spans can issue relationship directives. Full-match clauses prevent
        # reported speech such as “她说我们是恋人” from becoming a relationship definition.
        text = service.memory._direct_user_discourse_text(turn).strip()
        clauses = [
            clause.strip() for clause in re.split(r"[。！？!?；;\n]", text) if clause.strip()
        ]
        candidates = [
            candidate_for(
                RelationshipUpdateKind.INTERACTION,
                "新增一次用户主动互动",
                [ref],
                {},
                turn.occurred_at,
            )
        ]

        def add(
            kind: RelationshipUpdateKind,
            description: str,
            change: dict[str, object],
            *,
            strength: EvidenceStrength = EvidenceStrength.DIRECT,
            confidence: float = 1.0,
            refs: list[str] | None = None,
        ) -> None:
            candidates.append(
                candidate_for(
                    kind,
                    description,
                    refs or [ref],
                    change,
                    turn.occurred_at,
                    strength=strength,
                    confidence=confidence,
                )
            )

        for clause in clauses:
            if re.fullmatch(r"我们(?:并)?不是恋人[，,]?(?:我们只是朋友)?", clause):
                correction = [f"user_correction:{turn.id}"]
                add(
                    RelationshipUpdateKind.IDENTITY,
                    "用户明确纠正：双方不是恋人",
                    {
                        "labels": ["朋友"] if "朋友" in clause else [],
                        "romantic": False,
                        "description": "用户明确表示双方不是恋人",
                    },
                    refs=correction,
                )
                add(
                    RelationshipUpdateKind.BOUNDARY,
                    "不得把双方称作恋人",
                    {
                        "id": "relationship-not-romantic",
                        "description": "双方不是恋人，不使用恋爱关系的称呼或承诺",
                    },
                    refs=correction,
                )
            elif re.fullmatch(r"我们(?:就是|是|算是|已经是)(?:好)?朋友(?:了)?", clause):
                add(
                    RelationshipUpdateKind.IDENTITY,
                    "用户明确确认朋友关系",
                    {"labels": ["朋友"], "description": "用户明确确认双方是朋友"},
                )
            elif re.fullmatch(r"我们是恋人(?:了)?", clause):
                add(
                    RelationshipUpdateKind.IDENTITY,
                    "用户明确表达恋人关系定义",
                    {
                        "labels": ["恋人"],
                        "romantic": True,
                        "description": "用户明确表达恋人关系定义",
                    },
                )
                add(
                    RelationshipUpdateKind.BOUNDARY,
                    "用户更新了先前的非恋爱边界",
                    {
                        "id": "relationship-not-romantic",
                        "description": "用户已更新关系定义",
                        "active": False,
                    },
                )
            if re.fullmatch(r"(?:我们|咱们)(?:其实)?(?:已经)?认识(?:有)?半年了", clause):
                add(
                    RelationshipUpdateKind.TEMPORAL_CORRECTION,
                    "用户纠正认识时间为半年",
                    {"started_at": _months_before(turn.occurred_at, 6).isoformat()},
                    refs=[f"user_correction:{turn.id}"],
                )
            duration = re.fullmatch(
                r"(?:我们|咱们)(?:其实)?(?:已经)?认识(?:有)?(\d{1,3})个月了", clause
            )
            if duration and int(duration[1]) > 0:
                add(
                    RelationshipUpdateKind.TEMPORAL_CORRECTION,
                    "用户纠正关系持续时间",
                    {"started_at": _months_before(turn.occurred_at, int(duration[1])).isoformat()},
                    refs=[f"user_correction:{turn.id}"],
                )
            if re.fullmatch(
                r"(?:以后)?(?:我们)?(?:保持一点距离|保持距离|别这么亲密)(?:吧)?", clause
            ):
                add(RelationshipUpdateKind.DISTANCE, "用户要求降低互动距离", {"ceiling": "new"})
                add(
                    RelationshipUpdateKind.BOUNDARY,
                    "尊重用户要求的距离",
                    {"id": "distance", "description": "保持适当距离，不主动使用亲密表达"},
                )
            if re.fullmatch(r"我们(?:先)?(?:只做|做回)普通朋友(?:吧)?", clause):
                add(
                    RelationshipUpdateKind.DISTANCE, "用户希望做回普通朋友", {"ceiling": "familiar"}
                )
                add(
                    RelationshipUpdateKind.IDENTITY,
                    "用户将关系重新定义为普通朋友",
                    {
                        "labels": ["普通朋友"],
                        "romantic": False,
                        "description": "用户要求做回普通朋友",
                    },
                )
            if re.fullmatch(r"(?:不用|不必)再刻意保持距离(?:了)?", clause):
                add(RelationshipUpdateKind.DISTANCE, "用户撤销保持距离要求", {"ceiling": None})
                add(
                    RelationshipUpdateKind.BOUNDARY,
                    "撤销保持距离边界",
                    {
                        "id": "distance",
                        "description": "用户撤销刻意保持距离的要求",
                        "active": False,
                    },
                )
            if re.fullmatch(
                r"(?:你)?(?:不用|不要|不必)什么都顺着我|我不需要你无条件附和我", clause
            ):
                add(
                    RelationshipUpdateKind.BOUNDARY,
                    "用户要求保留独立判断",
                    {
                        "id": "independent-judgment",
                        "description": "用户希望角色保留独立判断，不无条件附和",
                    },
                )
            if re.fullmatch(r"我不喜欢你这么叫我|(?:以后)?不要这么叫我", clause):
                add(
                    RelationshipUpdateKind.BOUNDARY,
                    "用户拒绝刚才的称呼",
                    {
                        "id": "rejected-address",
                        "description": "不要再使用用户刚拒绝的称呼；不清楚具体称呼时先澄清",
                    },
                )
            if re.fullmatch(r"我不喜欢空泛安慰|不要用空泛的安慰(?:来安慰我)?", clause):
                add(
                    RelationshipUpdateKind.BOUNDARY,
                    "用户不喜欢空泛安慰",
                    {"id": "no-empty-comfort", "description": "不使用空泛安慰或模板鼓励"},
                )
            if re.fullmatch(r"我不喜欢你说[“\"「]?永远不会离开你[”\"」]?(?:这种话)?", clause):
                add(
                    RelationshipUpdateKind.BOUNDARY,
                    "用户拒绝永远陪伴类承诺",
                    {"id": "no-forever-promise", "description": "不使用永远不会离开你之类的承诺"},
                )
            if re.fullmatch(
                r"(?:今天|现在)(?:我)?不想听方案[，,]?(?:就|只)想吐槽|今天先听我说(?:就好)?", clause
            ):
                add(
                    RelationshipUpdateKind.DYNAMICS,
                    "本轮用户只想倾诉，是场景例外",
                    {"active_topics": ["本轮倾诉"], "summary": "本轮先听用户倾诉，不给解决方案"},
                )
            if re.fullmatch(
                r"(?:讨论|聊)(?:技术|技术问题)时[，,]?(?:我更喜欢|请|我希望你)(?:直接回答|直接给结论|直接判断)",
                clause,
            ):
                add(
                    RelationshipUpdateKind.PATTERN,
                    "用户明确偏好技术讨论直接给结论",
                    {
                        "id": "technical-directness",
                        "description": "技术讨论优先直接结论和判断",
                        "category": "communication",
                        "context_keys": TECH_TOPICS,
                        "explicit_stable": True,
                    },
                )
            elif re.fullmatch(r"(?:请)?直接告诉我哪个好|(?:请)?直接给结论", clause):
                add(
                    RelationshipUpdateKind.PATTERN,
                    "再次观察到直接判断需求",
                    {
                        "id": "direct-judgment",
                        "description": "比较和决策时偏好直接判断",
                        "category": "decision_making",
                        "context_keys": ["哪个好", "比较", "选择", "哪个好用"],
                    },
                    strength=EvidenceStrength.REPEATED,
                    confidence=0.65,
                )
            if re.fullmatch(
                r"(?:我难过|我情绪低落)的时候[，,]?(?:我)?(?:更希望|希望|喜欢)你先听(?:我说)?(?:而不是给建议)?",
                clause,
            ):
                add(
                    RelationshipUpdateKind.PATTERN,
                    "用户明确情绪支持偏好",
                    {
                        "id": "listen-when-distressed",
                        "description": "用户情绪低落时更希望先被倾听",
                        "category": "support",
                        "context_keys": ["难过", "压力", "工作", "情绪"],
                        "explicit_stable": True,
                    },
                )
            if re.fullmatch(r"哈哈[，,]?你嘴真毒", clause):
                add(
                    RelationshipUpdateKind.PATTERN,
                    "一次调侃反馈，暂不视为稳定幽默偏好",
                    {
                        "id": "teasing-feedback",
                        "description": "用户曾对轻微吐槽作出回应",
                        "category": "humor",
                        "context_keys": ["吐槽", "玩笑"],
                    },
                    strength=EvidenceStrength.WEAK,
                    confidence=0.35,
                )
            if re.fullmatch(r"(?:我觉得)?(?:我们)?上次(?:的)?争吵还没解决|我还在生你的气", clause):
                add(
                    RelationshipUpdateKind.THREAD,
                    "双方的冲突仍未解决",
                    {
                        "id": "relationship-conflict",
                        "topic": "未解决的争吵",
                        "summary": "用户明确表示双方的争吵仍未解决",
                        "topic_keys": ["争吵", "生气", "我们", "关系"],
                        "follow_up_mode": "user_led",
                    },
                )
                add(
                    RelationshipUpdateKind.DYNAMICS,
                    "用户直接表达关系紧张",
                    {
                        "interaction_tone": "tense",
                        "recent_closeness_change": "decreasing",
                        "recent_conflict_level": 0.85,
                        "active_topics": ["关系", "争吵"],
                        "summary": "用户仍对角色生气；先尊重距离，避免玩笑",
                    },
                )
            if re.fullmatch(r"上次(?:的)?争吵(?:已经)?说开了|我不再生你的气了", clause):
                if any(thread.id == "relationship-conflict" for thread in model.unresolved_threads):
                    add(
                        RelationshipUpdateKind.THREAD,
                        "用户明确表示上次冲突已经解决",
                        {
                            "id": "relationship-conflict",
                            "status": "resolved",
                            "summary": "用户确认冲突已说开",
                        },
                    )
                add(
                    RelationshipUpdateKind.DYNAMICS,
                    "关系进入修复状态",
                    {
                        "interaction_tone": "repairing",
                        "recent_conflict_level": 0,
                        "recent_closeness_change": "increasing",
                        "active_topics": ["关系"],
                        "summary": "用户表示冲突已说开，关系正在恢复",
                    },
                )
            important = re.fullmatch(
                r"(?:这次|上次)(?:和你)?(?:的)?(.{2,80}?)(?:对我|对我们)(?:真的)?很重要", clause
            )
            if important:
                title = important[1]
                item_id = "explicit-" + hashlib.sha256(title.encode()).hexdigest()[:20]
                add(
                    RelationshipUpdateKind.MILESTONE,
                    "用户明确标记有意义的共同经历",
                    {
                        "id": item_id,
                        "title": title,
                        "summary": clause,
                        "occurred_at": None,
                        "importance": 0.9,
                        "topic_keys": [title, "关系"],
                    },
                )

        # Reuse accepted MemoryOS facts, not unactivated model suggestions.
        if result.interpretation:
            for memory_id in result.interpretation.memory_ids:
                memory_ref = f"memory:{memory_id}"
                if not service.evidence_valid(model.key, memory_ref, turn.occurred_at):
                    continue
                memory = service.memory.store.get(memory_id, model.user_id)
                if memory.kind is MemoryKind.BOUNDARY:
                    add(
                        RelationshipUpdateKind.BOUNDARY,
                        "复用 MemoryOS 的已确认边界",
                        {"id": f"memory-{memory.id}", "description": memory.content},
                        refs=[memory_ref],
                    )
                elif memory.kind in {MemoryKind.RITUAL, MemoryKind.SUPPORT_STRATEGY}:
                    add(
                        RelationshipUpdateKind.PATTERN,
                        "复用 MemoryOS 已确认互动偏好",
                        {
                            "id": f"memory-{memory.stable_key or memory.id}",
                            "description": memory.content,
                            "category": "ritual" if memory.kind is MemoryKind.RITUAL else "support",
                            "context_keys": result.interpretation.model_output.topics,
                        },
                        strength=EvidenceStrength.REPEATED,
                        confidence=memory.confidence,
                        refs=[memory_ref],
                    )
        # Existing OpenLoop is authoritative for its lifecycle; no second scheduler is created.
        for loop in service.memory.list_open_loops(model.user_id):
            loop_ref = f"open_loop:{loop.id}"
            if not service.evidence_valid(model.key, loop_ref, turn.occurred_at):
                continue
            existing = next(
                (thread for thread in model.unresolved_threads if thread.open_loop_id == loop.id),
                None,
            )
            if not existing and loop.source_turn_id != turn.id:
                continue
            status = {"resolved": "resolved", "cancelled": "cancelled", "snoozed": "dormant"}.get(
                loop.status.value, "open"
            )
            if existing and existing.status.value == status:
                continue
            add(
                RelationshipUpdateKind.THREAD,
                "同步 MemoryOS 未完成事项状态",
                {
                    "id": f"loop-{loop.id}",
                    "topic": loop.summary,
                    "summary": loop.summary,
                    "topic_keys": loop.topic_keys,
                    "open_loop_id": loop.id,
                    "status": status,
                    "follow_up_mode": "never"
                    if loop.follow_up_mode.value == "never"
                    else "when_relevant",
                },
                refs=[loop_ref, ref],
            )
        return candidates
