"""Reuse MemoryOS episode membership; local fallback only links clear, unambiguous topics."""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from typing import TYPE_CHECKING

from companion_agent.experience.models import (
    ExperienceAction,
    ExperienceCandidate,
    ExperienceEvidenceKind,
    ExperienceEvidenceRef,
    ExperienceStatus,
    ExperienceType,
)
from companion_agent.relationship.models import RelationshipKey
from companion_memoryos.schemas import (
    ConversationRole,
    ConversationTurnRecord,
    EpisodeAttachRequest,
    EpisodeInput,
    MemoryScope,
)

if TYPE_CHECKING:
    from companion_agent.experience.service import ExperienceService

TOPICS: dict[str, tuple[str, tuple[str, ...]]] = {
    "employment_decision": (
        "用户考虑离职",
        ("辞职", "离职", "换工作", "老板又找我谈", "再待一个月", "决定留任"),
    ),
    "technical_choice": ("一起讨论电脑配置", ("显卡", "电脑配置", "rtx", "装机")),
    "relationship_conflict": (
        "双方的分歧与修复",
        ("争吵", "生你的气", "我们吵架", "说开了", "和解"),
    ),
    "emotional_support": ("围绕用户状态的陪伴交流", ("低谷", "压力", "难过", "哭了", "加班")),
    "shared_task": ("一起推进任务", ("一起完成", "一起写", "报告终于", "我们做完", "一起做项目")),
    "inside_joke": ("共同使用的内部梗", ("我们的梗", "这个梗", "暗号")),
}


def topic_for(text: str) -> tuple[str | None, str | None]:
    matches = [
        (key, title)
        for key, (title, words) in TOPICS.items()
        if any(word in text.casefold() for word in words)
    ]
    if len(matches) > 1:
        matches = [match for match in matches if match[0] != "emotional_support"]
    return matches[0] if len(matches) == 1 else (None, None)


def is_recall_question(text: str) -> bool:
    return any(
        phrase in text for phrase in ("还记得", "记不记得", "记得我之前", "记得我们", "回忆一下")
    )


class LocalExperienceEvaluator:
    def evaluate_episode(
        self,
        service: ExperienceService,
        key: RelationshipKey,
        episode_id: str,
        *,
        only_since: ConversationTurnRecord | None = None,
        anchor_id: str | None = None,
    ) -> list[ExperienceCandidate]:
        from companion_memoryos.episode_store import EpisodeStore

        episode = EpisodeStore(service.memory.store).get(episode_id, key.user_id)
        service._scope(key, episode)
        references = []
        facts = []
        for turn in service.memory.episode_turns(episode_id, key.user_id, episode.scope):
            if only_since and turn.server_sequence < only_since.server_sequence:
                continue
            if turn.role is ConversationRole.USER and is_recall_question(turn.content):
                continue
            ref = ExperienceEvidenceRef(
                kind=ExperienceEvidenceKind.TURN, id=turn.id, episode_id=episode_id
            )
            try:
                values = service.facts_for(key, ref)
            except ValueError:
                continue
            references.append(ref)
            facts.extend(values)
        users = [fact for fact in facts if not fact.is_assistant_action]
        if not users:
            return []
        anchor = anchor_id or f"episode:{episode.id}"
        keys = episode.topic_keys
        semantic_topic, _ = topic_for(" ".join(f.text for f in users))
        if semantic_topic:
            keys = list(dict.fromkeys([semantic_topic, *keys]))
        closed = any(
            phrase in users[-1].text
            for phrase in (
                "我决定再待一个月",
                "我决定再观察一个月",
                "已经决定留任",
                "决定留下",
                "已经辞职了",
                "报告终于完成",
                "我们做完了",
                "争吵已经说开了",
                "争吵说开了",
                "不再生你的气",
            )
        )
        source_ids = {fact.evidence_ref.id for fact in users}
        for loop in service.memory.list_open_loops(key.user_id):
            if loop.source_turn_id not in source_ids:
                continue
            ref = ExperienceEvidenceRef(kind=ExperienceEvidenceKind.OPEN_LOOP, id=loop.id)
            try:
                service.facts_for(key, ref)
            except ValueError:
                continue
            references.append(ref)
            closed = closed or loop.status.value == "resolved"
        candidates = []
        for kind in ExperienceType:
            body = {
                "anchor": anchor,
                "type": kind.value,
                "refs": [r.model_dump() for r in references],
                "close": closed,
            }
            identifier = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
            candidates.append(
                ExperienceCandidate(
                    **key.model_dump(),
                    candidate_id=identifier,
                    type=kind,
                    title=episode.title,
                    topic_keys=keys,
                    evidence_refs=references,
                    anchor_id=anchor,
                    target_id=None,
                    # Evidence snapshots are idempotent; host edits use explicit revisions.
                    requested_action=ExperienceAction.CLOSE if closed else ExperienceAction.CREATE,
                    created_at=max(f.occurred_at for f in facts),
                )
            )
        return candidates

    def observe(
        self,
        service: ExperienceService,
        user_turn: ConversationTurnRecord,
        assistant_turn: ConversationTurnRecord,
    ) -> list[ExperienceCandidate]:
        key = RelationshipKey(
            user_id=user_turn.user_id,
            companion_id=user_turn.scope.companion_id or "",
            relationship_id=user_turn.scope.relationship_id or "",
        )
        if is_recall_question(user_turn.content):
            return []
        try:
            user_fact = service.facts_for(
                key, ExperienceEvidenceRef(kind=ExperienceEvidenceKind.TURN, id=user_turn.id)
            )[0]
            service.facts_for(
                key, ExperienceEvidenceRef(kind=ExperienceEvidenceKind.TURN, id=assistant_turn.id)
            )
        except ValueError:
            return []
        topic, title = topic_for(user_fact.text)
        new_occasion = any(
            word in user_fact.text
            for word in ("另一次", "另一个", "重新考虑", "这次又想", "又想辞职")
        )
        existing = service.list_experiences(key, include_candidates=True)
        deictic_review = any(
            word in user_fact.text for word in ("这段讨论", "这几天的交流", "这次聊天")
        )
        if topic is None and deictic_review:
            recent = [
                item
                for item in existing
                if item.type is ExperienceType.SHARED
                and timedelta(0) <= user_turn.occurred_at - item.last_event_at <= timedelta(days=7)
            ]
            if len(recent) == 1:
                topic = next((word for word in recent[0].topic_keys if word in TOPICS), None)
                title = recent[0].title
        linked = [
            item
            for item in existing
            if item.type is ExperienceType.SHARED
            and (
                item.status
                in {ExperienceStatus.OPEN, ExperienceStatus.DORMANT, ExperienceStatus.CANDIDATE}
                or (deictic_review and item.status is ExperienceStatus.CLOSED)
            )
            and topic
            and topic in item.topic_keys
            and timedelta(0)
            <= user_turn.occurred_at - item.last_event_at
            <= timedelta(days=service.config.merge_gap_days)
        ]
        episode_id = user_turn.episode_id
        anchor = None
        if episode_id is None:
            if not topic:
                return []
            if len(linked) > 1 and not new_occasion:
                return []  # ambiguous continuity is a host/interpretation decision
            if len(linked) == 1 and not new_occasion:
                previous = linked[0]
                anchor = previous.anchor_id
                old_episodes = {ref.episode_id for ref in previous.evidence_refs if ref.episode_id}
                if len(old_episodes) == 1:
                    from companion_memoryos.episode_store import EpisodeStore

                    episode = EpisodeStore(service.memory.store).get(
                        next(iter(old_episodes)), key.user_id
                    )
                    if (
                        EpisodeStore.scope_allows(episode.scope, user_turn.scope)
                        and episode.status.value == "open"
                    ):
                        episode_id = episode.id
            if episode_id is None:
                episode = service.memory.create_episode(
                    EpisodeInput(
                        user_id=key.user_id,
                        scope=MemoryScope(
                            companion_id=key.companion_id, relationship_id=key.relationship_id
                        ),
                        title=title or topic,
                        topic_keys=[topic, *TOPICS[topic][1]],
                        participant_actor_ids=[key.user_id, key.companion_id],
                        started_at=user_turn.occurred_at,
                    )
                )
                episode_id = episode.id
            service.memory.attach_episode_turn(
                episode_id,
                EpisodeAttachRequest(
                    user_id=key.user_id, scope=user_turn.scope, turn_id=user_turn.id
                ),
            )
        if assistant_turn.episode_id is None:
            service.memory.attach_episode_turn(
                episode_id,
                EpisodeAttachRequest(
                    user_id=key.user_id, scope=assistant_turn.scope, turn_id=assistant_turn.id
                ),
            )
        # Upstream membership is authoritative; an explicitly new occurrence only takes this pair.
        if new_occasion:
            anchor = f"occurrence:{user_turn.id}"
        return self.evaluate_episode(
            service, key, episode_id, only_since=user_turn, anchor_id=anchor
        )
