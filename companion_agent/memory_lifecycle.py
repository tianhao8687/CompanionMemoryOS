"""Apply explicit event updates to the existing OpenLoop lifecycle."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from companion_memoryos.discourse import NONASSERTIVE, direct_clauses, negated_predicate
from companion_memoryos.schemas import (
    ConsentState,
    ConversationTurnRecord,
    MemoryCorrectionRequest,
    MemoryKind,
    MemoryStatus,
    OpenLoopStatus,
    OpenLoopTransition,
    OpenLoopUpdateRequest,
    Sensitivity,
)

if TYPE_CHECKING:
    from companion_agent.cognition import ApplicationMemory

CHANGE = re.compile(r"取消(?:了)?|不去了|不参加了|作废了|改到|改为|推迟到|提前到|延期到")
FINISH = re.compile(r"结束了|完成了|办完了|已经.{0,5}做完了")
GENERIC_TOPICS = {
    "周末",
    "今天",
    "明天",
    "计划",
    "安排",
    "活动",
    "时间",
    "日程",
    "心情",
    "游戏",
    "地点",
    "场地",
    "通知",
    "变动",
}
DATE_TOPIC = re.compile(r"^[\d零一二三四五六七八九十年月日号周星期天上下午夜点时分半:：./-]+$")
LOCATION_TOPIC = re.compile(r"(?:馆|厅|楼|站|室|中心|店|园|广场)$")


def topic_keys(keys: list[str]) -> list[str]:
    """Strip lifecycle suffixes, so an event keeps its identity after rescheduling."""
    output = []
    for key in keys:
        key = re.sub(r"(?:改期|取消|变更|安排|计划|调整|通知)+$", "", key).strip()
        if len(key) >= 2 and key not in GENERIC_TOPICS and not DATE_TOPIC.fullmatch(key):
            output.append(key)
    return list(dict.fromkeys(output))


def topics_overlap(keys: list[str], text: str) -> bool:
    for key in topic_keys(keys):
        if key in text:
            return True
        # A shortened noun (e.g. an event name without its modifier) is a search
        # cue only. It never authorizes a destructive lifecycle transition.
        if any(
            key[index : index + 2] in text and key[index : index + 2] not in GENERIC_TOPICS
            for index in range(len(key) - 1)
        ):
            return True
    return False


def same_event_topics(keys: list[str], text: str) -> bool:
    normalized = topic_keys(keys)
    if any(key in text and not LOCATION_TOPIC.search(key) for key in normalized):
        return True
    # A split name needs two distinct anchors, e.g. venue + activity. One
    # shared word such as a venue alone cannot cancel a different event there.
    matches = {
        key[start:end]
        for key in normalized
        for start in range(len(key))
        for end in range(start + 2, min(len(key), start + 8) + 1)
        if key[start:end] in text and key[start:end] not in GENERIC_TOPICS
    }
    maximal = [
        word for word in matches if not any(word != other and word in other for other in matches)
    ]
    ranges: list[tuple[int, int]] = []
    for word in sorted(maximal, key=len, reverse=True):
        start = text.find(word)
        end = start + len(word)
        if all(end <= a or start >= b for a, b in ranges):
            ranges.append((start, end))
    return len(ranges) >= 2 and sum(b - a for a, b in ranges) >= 4


def is_conversation_task(text: str) -> bool:
    return not has_dated_plan(text) and any(
        not NONASSERTIVE.search(clause)
        and bool(
            re.search(
                r"(?:帮我|替我|给我|你(?:来|先|再|试着|试试)?)(?:.{0,8}?)(?:写|算|翻译|解释|拟|起.{0,3}名|编|讲)|你问我|"
                r"^(?:给|替)(?!自己)[^，。]{1,12}?(?:写|算|翻译|拟|解释)",
                clause,
            )
        )
        for clause in direct_clauses(text)
    )


def reconcile_preference_correction(
    memory: ApplicationMemory, turn: ConversationTurnRecord, text: str
) -> int:
    """Keep a version chain when an explicit correction names the old preference.

    The old value must identify one existing self preference. Do not merge
    different people or guess identity from an embedding/model predicate.
    """
    clauses = [c for c in direct_clauses(text) if not NONASSERTIVE.search(c)]
    replacements = [
        c
        for c in clauses
        if (change := re.search(r"改成|改为|换成", c))
        and re.search(r"最(?:喜欢|爱)", c[: change.start()])
        and not negated_predicate(c, change.start())
    ]
    old_values = [
        match[1]
        for clause in clauses
        if (match := re.fullmatch(r"(.{2,24}?)是(?:我)?(?:之前|以前|原来)的(?:偏好|选择)", clause))
    ]
    if len(replacements) != 1 or len(old_values) != 1:
        return 0
    prior = [
        item
        for item in memory.store.list_memories(turn.user_id, {MemoryStatus.ACTIVE})
        if item.kind is MemoryKind.PREFERENCE
        and item.stable_key
        and item.subject_actor_id in {None, turn.user_id}
        and item.scope.companion_id == turn.scope.companion_id
        and item.scope.relationship_id == turn.scope.relationship_id
        and item.scope.group_id == turn.scope.group_id
        and item.scope.conversation_id in {None, turn.scope.conversation_id}
        and item.reality_layer.value == "real_world"
        and item.consent is ConsentState.GRANTED
        and item.sensitivity is Sensitivity.NORMAL
        and item.event_at < turn.occurred_at
        and old_values[0] in item.content
    ]
    if len(prior) != 1:
        return 0

    def context_prefix(clause: str) -> str:
        prefix = re.split(r"最(?:喜欢|爱)|喜欢|偏爱", clause, maxsplit=1)[0]
        return re.sub(r"^(?:以后|今后|从现在起|目前|现在|最近|平时|我|用户|的)+", "", prefix)

    # A shared old value alone is not identity: another person or activity may
    # also like it. Require the same literal context in the original statement.
    contexts: list[str] = []
    for source_id in prior[0].evidence_turn_ids:
        try:
            source = memory.store.get_turn(source_id, turn.user_id)
        except KeyError:
            continue
        contexts.extend(
            context_prefix(c)
            for c in direct_clauses(memory._direct_user_discourse_text(source))
            if old_values[0] in c and re.search(r"最(?:喜欢|爱)|喜欢|偏爱", c)
        )
    if context_prefix(replacements[0]) not in contexts:
        return 0
    result = memory.correct(
        prior[0].id,
        MemoryCorrectionRequest(
            user_id=turn.user_id,
            content=replacements[0],
            title=replacements[0][:240],
            event_at=turn.occurred_at,
            source_ref=f"turn:{turn.id}",
            source_excerpt=replacements[0],
            evidence_turn_ids=[turn.id],
        ),
    )
    return int(result.memory is not None)


def is_planning_overview(text: str) -> bool:
    return any(
        not NONASSERTIVE.search(clause)
        and re.search(r"安排|行程|日程|规划|说好|顺顺|排一排", clause)
        and re.search(r"帮我|我们|一起|怎么|如何|给我|替我", clause)
        for clause in direct_clauses(text)
    )


def has_dated_plan(text: str) -> bool:
    return any(
        not NONASSERTIVE.search(clause)
        and not re.search(r"不想|不要|不打算|不用|[?？]", clause)
        and re.search(
            r"周[一二三四五六日天末]|明天|后天|下周|下个月|\d+月|[一二三四五六七八九十]+月", clause
        )
        and re.search(r"约|见|去|参加|课|改到|改为|取消|电影|书店|聚餐|出发", clause)
        for clause in direct_clauses(text)
    )


def reconcile_open_loops(memory: ApplicationMemory, turn: ConversationTurnRecord, text: str) -> int:
    if turn.consent is not ConsentState.GRANTED or turn.sensitivity is not Sensitivity.NORMAL:
        return 0
    changed = 0
    for loop in memory.list_open_loops(turn.user_id):
        if (
            loop.scope.companion_id != turn.scope.companion_id
            or loop.scope.relationship_id != turn.scope.relationship_id
            or loop.scope.group_id != turn.scope.group_id
            or loop.consent is not ConsentState.GRANTED
            or loop.status
            not in {OpenLoopStatus.OPEN, OpenLoopStatus.WAITING_FOR_REPLY, OpenLoopStatus.SNOOZED}
        ):
            continue
        # An app-owned, user-grounded ongoing event belongs to this relationship,
        # allowing the next conversation to update it with its own evidence.
        if loop.source_turn_id == turn.id:
            with memory.store.database.connection() as db:
                db.execute(
                    "UPDATE open_loops SET conversation_id=NULL WHERE id=? AND user_id=?",
                    (loop.id, turn.user_id),
                )
            cancelled = any(
                (match := re.search(r"取消|作废", clause)) is not None
                and not negated_predicate(clause, match.start())
                and not NONASSERTIVE.search(clause)
                for clause in direct_clauses(text)
            ) and bool(re.search(r"取消|作废", loop.summary))
            immediate_task = is_conversation_task(text)
            rescheduled = any(
                re.search(r"改期|改到|改为|推迟到|提前到|延期到", c) for c in direct_clauses(text)
            )
            cancelled = cancelled and not (rescheduled and has_dated_plan(text))
            if loop.metadata.get("candidate_only") and (cancelled or immediate_task):
                memory.update_open_loop(
                    loop.id,
                    OpenLoopUpdateRequest(
                        user_id=turn.user_id,
                        transition=OpenLoopTransition.CANCEL,
                        source_turn_id=turn.id,
                        expected_revision=loop.revision,
                        resolution_summary="用户已取消事项"
                        if cancelled
                        else "当前对话请求，不是跨回合待办",
                        as_of=turn.occurred_at,
                    ),
                )
                changed += 1
            continue
        keys = topic_keys(loop.topic_keys)
        if loop.metadata.get("candidate_only") and loop.source_turn_id:
            try:
                source = memory.store.get_turn(loop.source_turn_id, turn.user_id)
            except KeyError:
                source = None
            if source is not None and is_conversation_task(
                memory._direct_user_discourse_text(source)
            ):
                memory.update_open_loop(
                    loop.id,
                    OpenLoopUpdateRequest(
                        user_id=turn.user_id,
                        transition=OpenLoopTransition.CANCEL,
                        source_turn_id=source.id,
                        expected_revision=loop.revision,
                        resolution_summary="当前对话请求，不是跨回合待办",
                        as_of=turn.occurred_at,
                    ),
                )
                changed += 1
                continue
        for clause in direct_clauses(text):
            if NONASSERTIVE.search(clause) or clause.endswith(("吗", "么")):
                continue
            if not same_event_topics(keys, clause):
                continue
            match = CHANGE.search(clause) or FINISH.search(clause)
            if match is None or negated_predicate(clause, match.start()):
                continue
            transition = (
                OpenLoopTransition.CANCEL if CHANGE.search(clause) else OpenLoopTransition.RESOLVE
            )
            # Older application versions left these events conversation-scoped.
            # Only widen the conversation dimension inside the already checked domain.
            with memory.store.database.connection() as db:
                db.execute(
                    "UPDATE open_loops SET conversation_id=NULL WHERE id=? AND user_id=?",
                    (loop.id, turn.user_id),
                )
            memory.update_open_loop(
                loop.id,
                OpenLoopUpdateRequest(
                    user_id=turn.user_id,
                    transition=transition,
                    source_turn_id=turn.id,
                    resolution_summary=clause,
                    expected_revision=loop.revision,
                    as_of=turn.occurred_at,
                ),
            )
            changed += 1
            break
    return changed
