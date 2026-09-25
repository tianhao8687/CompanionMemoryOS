"""Complete a bounded retrieval with version, person and actual dialogue evidence.

All additions are original ledger turns. They pass the caller's ordinary source,
scope, privacy and token-budget checks; model proposals never become facts here.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from companion_agent.memory_lifecycle import is_conversation_task, topics_overlap
from companion_memoryos.discourse import NONASSERTIVE, direct_clauses, negated_predicate
from companion_memoryos.entity_resolution import entity_catalog
from companion_memoryos.schemas import (
    ConsentState,
    ConversationRole,
    MemoryKind,
    MemoryStatus,
    RecallRequest,
    Sensitivity,
    TurnDeletionState,
    TurnRecallItem,
)
from companion_memoryos.scoring import build_fts_query, lexical_similarity, query_tokens, tokenize
from companion_memoryos.store import TurnSearchCandidate
from companion_memoryos.temporal import TemporalHint
from companion_memoryos.turn_layers import turn_reality_layer

if TYPE_CHECKING:
    from companion_agent.cognition import ApplicationMemory


UPDATE = re.compile(
    r"改成|改为|改到|换成|换到|搬到|移到|收紧|作废|取消|去掉|删掉|撤掉|只留|不再|不做|不加|取代|更正"
)
MEAL_QUERY = re.compile(r"吃|喝|点餐|早餐|口味|忌口|菜单|餐厅|店家.*备注")
FOOD_FACT = re.compile(r"不吃|不碰|忌口|过敏|爱吃|爱喝|喜欢|讨厌|不能少")
GENERIC_CUES = set(
    [
        "我们",
        "一个",
        "现在",
        "还是",
        "今天",
        "这个",
        "那个",
        "一件",
        "怎么",
        "什么",
        "帮我",
        "你说",
        "我说",
        "可以",
        "不要",
        "取消",
        "改成",
        "改为",
        "以后",
        "之前",
        "当时",
        "这次",
        "那次",
        "已经",
        "时间",
        "安排",
        "地点",
        "消息",
        "准备",
        "记得",
        "确定",
        "写一",
        "备注",
        "后来",
        "自己",
        "现在的",
        "你觉得",
    ]
)
PAST_REPLY = re.compile(
    r"(?:以前|之前|上次|当时|那天|已经).{0,30}(?:写|算|答|说|给)|"
    r"你.{0,8}(?:写过|算过|说过|给过)|(?:那句|那段|那版|那份).{0,12}(?:文案|话|稿|说明)|"
    r"(?:封底|扉页).{0,8}(?:那句|文案|说过)"
)


def specific_overlap(left: str, right: str, memory: ApplicationMemory) -> bool:
    shared = query_tokens(left, memory.config) & tokenize(right, memory.config)
    return any(len(word) >= 2 and word not in GENERIC_CUES for word in shared)


def explicit_update(text: str) -> bool:
    return any(
        (change := UPDATE.search(clause))
        and not NONASSERTIVE.search(clause)
        and not re.search(r"[?？]|(?:吗|么)$", clause)
        and not negated_predicate(clause, change.start())
        for clause in direct_clauses(text)
    )


def complete_candidates(
    memory: ApplicationMemory,
    request: RecallRequest,
    hint: TemporalHint,
    items: list[TurnRecallItem],
) -> list[TurnRecallItem]:
    # These enrichments are for ordinary evidence collection, not a replacement
    # for explicit time/state/actor queries implemented by MemoryOS.
    if not request.include_turn_evidence or request.state_predicate:
        return items
    records = memory.store.list_memories(
        request.user_id,
        {MemoryStatus.ACTIVE, MemoryStatus.CANDIDATE},
        scope=request.scope.model_copy(update={"conversation_id": None})
        if request.include_relationship_turns
        else request.scope,
    )
    priority: dict[str, tuple[str, float]] = {}
    # Raw evidence remains useful when extraction made no approved memory card.
    # Prefer an explicit related update before older proposals and generic matches.
    updates = [
        item
        for item in items
        if item.turn.role is ConversationRole.USER
        and explicit_update(memory._direct_user_discourse_text(item.turn))
        and specific_overlap(request.query, item.evidence_text, memory)
    ]
    for update in sorted(updates, key=lambda i: i.turn.server_sequence, reverse=True)[:3]:
        priority[update.turn.id] = (
            "latest_related_raw_statement",
            max(update.recall_confidence, 0.9),
        )
    related_text = request.query + "\n" + "\n".join(item.evidence_text for item in items[:3])
    # A selected historical fact must travel with an explicit newer statement,
    # even when the newer wording ranks poorly in the broad vector query.
    for item in sorted(records, key=lambda r: r.event_at, reverse=True):
        if (
            item.status is MemoryStatus.ACTIVE
            and item.consent is ConsentState.GRANTED
            and item.sensitivity is Sensitivity.NORMAL
            and item.reality_layer is request.state_reality_layer
            and item.event_at <= request.as_of
            and (item.expires_at is None or item.expires_at > request.as_of)
            and (item.metadata.get("direct_user_correction") or UPDATE.search(item.content))
            and topics_overlap([item.title, item.predicate or ""], related_text)
        ):
            for source in item.evidence_turn_ids:
                priority.setdefault(source, ("latest_related_statement", item.confidence))
    for loop in memory.list_open_loops(request.user_id):
        update_source = loop.metadata.get("last_update_source_turn_id")
        if (
            isinstance(update_source, str)
            and loop.scope.companion_id == request.scope.companion_id
            and loop.scope.relationship_id == request.scope.relationship_id
            and loop.scope.group_id == request.scope.group_id
            and loop.updated_at <= request.as_of
            and topics_overlap(loop.topic_keys, related_text)
        ):
            priority.setdefault(update_source, ("latest_related_event_status", 1.0))
    entities, _ = entity_catalog(
        memory.store,
        request.user_id,
        request.scope,
        request.state_reality_layer,
        request.as_of,
        8,
        text=request.query,
        allow_sensitive=False,
    )
    for entity in entities:
        if max(map(len, [entity.name, *entity.aliases])) < 2:
            continue
        facts = [
            r
            for r in records
            if r.subject_actor_id == entity.id
            and r.consent is ConsentState.GRANTED
            and r.sensitivity is Sensitivity.NORMAL
            and r.reality_layer is request.state_reality_layer
            and r.event_at <= request.as_of
            and (r.expires_at is None or r.expires_at > request.as_of)
        ]
        facts.sort(
            key=lambda r: (
                bool(
                    MEAL_QUERY.search(request.query)
                    and FOOD_FACT.search(r.content)
                    and r.kind is MemoryKind.PREFERENCE
                ),
                lexical_similarity(request.query, r.content, memory.config),
                r.event_at,
            ),
            reverse=True,
        )
        # Search each named person's original utterances even if an extractor
        # deferred their preference's subject. No candidate claim is promoted.
        spellings = [s for s in [entity.name, *entity.aliases] if len(s) >= 2]
        pool = memory.store.turn_pool(
            request.user_id,
            request.scope,
            build_fts_query(" ".join(spellings), memory.config),
            32,
            request.as_of,
            semantic_pool_size=0,
            minimum_semantic_similarity=1.0,
            actor_id=request.user_id,
            exclude_turn_ids=request.exclude_turn_ids,
            event_after=request.event_after,
            event_before=request.event_before,
            reality_layer=request.state_reality_layer,
            include_relationship_turns=request.include_relationship_turns,
        )
        originals = [
            candidate.turn
            for candidate in pool
            if candidate.turn.role is ConversationRole.USER
            and candidate.turn.consent is ConsentState.GRANTED
            and candidate.turn.sensitivity is Sensitivity.NORMAL
            and any(s in candidate.turn.content for s in spellings)
            and not re.search(r"[?？]|(?:吗|么)[。！!]*$", candidate.turn.content)
            and (
                bool(FOOD_FACT.search(candidate.turn.content))
                if MEAL_QUERY.search(request.query)
                else specific_overlap(request.query, candidate.turn.content, memory)
            )
        ]
        originals.sort(
            key=lambda t: (
                lexical_similarity(request.query, t.content, memory.config),
                t.server_sequence,
            ),
            reverse=True,
        )
        for original in originals[:1]:
            priority.setdefault(original.id, ("named_person_original_statement", 0.9))
        if MEAL_QUERY.search(request.query):
            facts = [fact for fact in facts if FOOD_FACT.search(fact.content)]
        for fact in facts[:1]:
            for source in fact.evidence_turn_ids:
                priority.setdefault(source, ("named_person_source_coverage", fact.confidence))

    added: list[TurnRecallItem] = []
    for identifier, (reason, confidence) in list(priority.items())[:12]:
        if identifier in request.exclude_turn_ids:
            continue
        try:
            turn = memory.store.get_turn(identifier, request.user_id)
        except KeyError:
            continue
        if (
            turn.role is not ConversationRole.USER
            or turn.actor_id != request.user_id
            or turn.deletion_state is not TurnDeletionState.ACTIVE
            or turn.consent is not ConsentState.GRANTED
            or turn.sensitivity is not Sensitivity.NORMAL
            or turn.occurred_at > request.as_of
            or turn.scope.companion_id != request.scope.companion_id
            or turn.scope.relationship_id != request.scope.relationship_id
            or turn.scope.group_id != request.scope.group_id
            or (not request.include_relationship_turns and turn.scope != request.scope)
            or (request.event_after and turn.occurred_at < request.event_after)
            or (request.event_before and turn.occurred_at >= request.event_before)
            or turn_reality_layer(
                turn.content,
                json.dumps(turn.metadata),
                json.dumps([s.model_dump(mode="json") for s in turn.speech_spans]),
            )
            != request.state_reality_layer.value
        ):
            continue
        recalled = memory._turn_item(TurnSearchCandidate(turn=turn), request, hint)
        recalled.recall_confidence = max(recalled.recall_confidence, confidence)
        recalled.use_mode = memory._use_mode(recalled.recall_confidence)
        recalled.reasons.append(reason)
        added.append(recalled)
    ids = {item.turn.id for item in added}
    return [*added, *(item for item in items if item.turn.id not in ids)]


def dialogue_replies(
    memory: ApplicationMemory,
    request: RecallRequest,
    hint: TemporalHint,
    selected: list[TurnRecallItem],
) -> list[TurnRecallItem]:
    """An earlier writing/calculation request may already have a saved reply."""
    if not PAST_REPLY.search(request.query):
        return []
    output: list[TurnRecallItem] = []
    for item in selected:
        if not is_conversation_task(item.evidence_text) or not specific_overlap(
            request.query, item.evidence_text, memory
        ):
            continue
        with memory.store.database.connection() as db:
            row = db.execute(
                "SELECT * FROM conversation_turns WHERE user_id=? AND reply_to_turn_id=? "
                "AND role='assistant' AND deletion_state='active' AND consent='granted' "
                "AND sensitivity='normal' AND occurred_at<=? ORDER BY server_sequence DESC LIMIT 1",
                (request.user_id, item.turn.id, request.as_of.isoformat()),
            ).fetchone()
        if row is not None:
            turn = memory.store._row_to_turn(row)
            if turn.scope != item.turn.scope:
                continue
            reply = memory._turn_item(TurnSearchCandidate(turn=turn), request, hint)
            reply.recall_confidence = item.recall_confidence
            reply.use_mode = item.use_mode
            reply.reasons.append("associated_dialogue_reply_not_user_fact")
            output.append(reply)
        if len(output) == 2:
            break
    return output
