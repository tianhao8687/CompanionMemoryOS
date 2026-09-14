"""Sourced experience projection and lifecycle. No generated narrative is accepted as fact."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any

from companion_agent.experience.models import (
    ExperienceAction,
    ExperienceCandidate,
    ExperienceConfig,
    ExperienceDecision,
    ExperienceEvidenceKind,
    ExperienceEvidenceRef,
    ExperienceFact,
    ExperienceRecallItem,
    ExperienceRecord,
    ExperienceStatus,
    ExperienceType,
)
from companion_agent.experience.store import ExperienceStore
from companion_agent.relationship.models import RelationshipKey, now_utc
from companion_agent.relationship.store import RelationshipConflictError
from companion_memoryos.episode_store import EpisodeStore
from companion_memoryos.experience import SUPPRESSING_FEEDBACK
from companion_memoryos.schemas import (
    ConsentState,
    ConversationRole,
    EvidenceActor,
    MemoryReferenceMode,
    MemoryScope,
    MemoryStatus,
    MemoryUsePlan,
    RealityLayer,
    ResolutionStatus,
    Sensitivity,
    TurnDeletionState,
)
from companion_memoryos.schemas import (
    ExperienceEvidenceKind as MemoryEvidenceKind,
)
from companion_memoryos.schemas import (
    ExperienceEvidenceRef as MemoryEvidenceRef,
)
from companion_memoryos.service import CompanionMemoryService
from companion_memoryos.turn_layers import turn_reality_layer

ACTIVE_STATUSES = {ExperienceStatus.OPEN, ExperienceStatus.CLOSED, ExperienceStatus.DORMANT}


class ExperienceService:
    def __init__(
        self, memory: CompanionMemoryService, config: ExperienceConfig | None = None
    ) -> None:
        self.memory = memory
        self.config = config or ExperienceConfig()
        self.store = ExperienceStore(memory.store.database)

    def ingest_episode(self, key: RelationshipKey, episode_id: str) -> list[ExperienceDecision]:
        from companion_agent.experience.evaluator import LocalExperienceEvaluator

        with self.store.database.atomic():
            candidates = LocalExperienceEvaluator().evaluate_episode(self, key, episode_id)
            return [self.commit(candidate) for candidate in candidates]

    def observe(self, user_turn: Any, assistant_turn: Any) -> list[ExperienceDecision]:
        from companion_agent.experience.evaluator import LocalExperienceEvaluator

        with self.store.database.atomic():
            user_turn = self.memory.store.get_turn(user_turn.id, user_turn.user_id)
            assistant_turn = self.memory.store.get_turn(assistant_turn.id, assistant_turn.user_id)
            candidates = LocalExperienceEvaluator().observe(self, user_turn, assistant_turn)
            return [self.commit(candidate) for candidate in candidates]

    def relationship_candidates(self, key: RelationshipKey) -> list[Any]:
        from companion_agent.relationship.models import RelationshipUpdateKind
        from companion_agent.relationship.service import candidate_for

        candidates = []
        for experience in self.list_experiences(key):
            if experience.type is not ExperienceType.SHARED:
                continue
            reference = f"experience:{experience.experience_id}"
            candidates.append(
                candidate_for(
                    RelationshipUpdateKind.EXPERIENCE,
                    "记录有原始证据的共同经历",
                    [reference],
                    {"experience_id": experience.experience_id, "revision": experience.revision},
                    experience.last_event_at,
                )
            )
            users = [fact for fact in experience.facts if not fact.is_assistant_action]
            if (
                len(users) >= self.config.milestone_user_turns
                and len({fact.occurred_at.date() for fact in users})
                >= self.config.milestone_active_days
                and experience.importance >= self.config.milestone_importance
                and experience.relationship_significance
                >= self.config.milestone_relationship_significance
            ):
                candidates.append(
                    candidate_for(
                        RelationshipUpdateKind.MILESTONE,
                        "共同经历晋升为关系里程碑",
                        [reference],
                        {
                            "id": f"experience-{experience.experience_id}",
                            "title": experience.title,
                            "summary": experience.summary,
                            "occurred_at": experience.started_at.isoformat(),
                            "importance": experience.importance,
                            "topic_keys": experience.topic_keys,
                        },
                        experience.last_event_at,
                    )
                )
        return candidates

    def _scope(self, key: RelationshipKey, source: Any) -> None:
        if (
            source.user_id != key.user_id
            or source.scope.companion_id != key.companion_id
            or source.scope.relationship_id != key.relationship_id
            or source.scope.group_id is not None
        ):
            raise ValueError("experience evidence belongs to another scope")

    def facts_for(
        self,
        key: RelationshipKey,
        reference: ExperienceEvidenceRef,
        *,
        as_of: datetime | None = None,
        allow_sensitive: bool = True,
    ) -> list[ExperienceFact]:
        at = as_of or now_utc()
        kind = reference.kind
        if kind is ExperienceEvidenceKind.EPISODE:
            episode = EpisodeStore(self.memory.store).get(reference.id, key.user_id)
            self._scope(key, episode)
            if (
                episode.status.value in {"merged", "empty"}
                or episode.reality_layer is not RealityLayer.REAL_WORLD
            ):
                raise ValueError("episode is no longer valid experience evidence")
            # Membership alone does not authorize all its contents; validate every raw source.
            result: list[ExperienceFact] = []
            for turn in self.memory.episode_turns(episode.id, key.user_id, episode.scope):
                try:
                    result.extend(
                        self.facts_for(
                            key,
                            ExperienceEvidenceRef(
                                kind=ExperienceEvidenceKind.TURN, id=turn.id, episode_id=episode.id
                            ),
                            as_of=at,
                            allow_sensitive=allow_sensitive,
                        )
                    )
                except ValueError:
                    continue
            return result
        if kind is ExperienceEvidenceKind.OPEN_LOOP:
            loop = self.memory.store.get_open_loop(reference.id, key.user_id)
            self._scope(key, loop)
            if loop.consent is not ConsentState.GRANTED or not loop.source_turn_id:
                raise ValueError("open loop lacks consented source evidence")
            return self.facts_for(
                key,
                ExperienceEvidenceRef(kind=ExperienceEvidenceKind.TURN, id=loop.source_turn_id),
                as_of=at,
                allow_sensitive=allow_sensitive,
            )
        source: Any
        if kind is ExperienceEvidenceKind.TURN:
            source = self.memory.store.get_turn(reference.id, key.user_id)
            self._scope(key, source)
            if (
                source.deletion_state is not TurnDeletionState.ACTIVE
                or source.role not in {ConversationRole.USER, ConversationRole.ASSISTANT}
                or source.actor_id
                != (key.user_id if source.role is ConversationRole.USER else key.companion_id)
                or (reference.episode_id is not None and source.episode_id != reference.episode_id)
                or turn_reality_layer(
                    source.content,
                    json.dumps(source.metadata),
                    json.dumps([span.model_dump(mode="json") for span in source.speech_spans]),
                )
                != "real_world"
            ):
                raise ValueError("turn is not eligible lived experience evidence")
            assistant = source.role is ConversationRole.ASSISTANT
            content = (
                "角色对用户本轮内容作出了回应"
                if assistant
                else self.memory._direct_user_discourse_text(source).strip()
            )
            occurred = source.occurred_at
            actor = source.actor_id
        else:
            source = self.memory.store.get(reference.id, key.user_id)
            self._scope(key, source)
            if (
                source.status is not MemoryStatus.ACTIVE
                or source.reality_layer is not RealityLayer.REAL_WORLD
                or source.source_actor is not EvidenceActor.AUTHENTICATED_USER
                or source.quote_depth
                or source.resolution_status is not ResolutionStatus.RESOLVED
                or source.subject_actor_id not in {None, key.user_id}
                or (source.expires_at and source.expires_at <= at)
            ):
                raise ValueError("memory is not eligible user experience evidence")
            for turn_id in source.evidence_turn_ids:
                self.facts_for(
                    key,
                    ExperienceEvidenceRef(kind=ExperienceEvidenceKind.TURN, id=turn_id),
                    as_of=at,
                    allow_sensitive=allow_sensitive,
                )
            content, occurred, actor, assistant = (
                source.content,
                source.event_at,
                key.user_id,
                False,
            )
        if (
            source.consent is not ConsentState.GRANTED
            or occurred > at
            or not content
            or (not allow_sensitive and source.sensitivity is not Sensitivity.NORMAL)
        ):
            raise ValueError("experience source unavailable, future or sensitive")
        return [
            ExperienceFact(
                actor_id=actor,
                text=content,
                occurred_at=occurred,
                evidence_ref=reference,
                is_assistant_action=assistant,
            )
        ]

    def _materialize(
        self, candidate: ExperienceCandidate, before: ExperienceRecord | None
    ) -> ExperienceRecord:
        refs = [*(before.evidence_refs if before else []), *candidate.evidence_refs]
        unique: dict[str, ExperienceEvidenceRef] = {}
        for reference in refs:
            unique[reference.key] = reference
        facts: dict[str, ExperienceFact] = {}
        for reference in unique.values():
            for fact in self.facts_for(candidate.key, reference):
                existing_fact = facts.get(fact.evidence_ref.key)
                if existing_fact is None or fact.evidence_ref.episode_id is not None:
                    facts[fact.evidence_ref.key] = fact
        ordered = sorted(facts.values(), key=lambda fact: (fact.occurred_at, fact.evidence_ref.key))
        user_facts = [f for f in ordered if not f.is_assistant_action]
        user_turn_facts = [
            f for f in user_facts if f.evidence_ref.kind is ExperienceEvidenceKind.TURN
        ]
        assistant_facts = [f for f in ordered if f.is_assistant_action]
        if not user_facts:
            raise ValueError("experience requires actual user evidence")
        # A shared/character lived experience must contain actual reciprocal conversation.
        if candidate.type is not ExperienceType.USER and not assistant_facts:
            active = False
        else:
            active = (
                candidate.type is not ExperienceType.SHARED
                or len(user_turn_facts) >= self.config.shared_user_turns
            )
        explicit = any(
            any(word in fact.text for word in ("对我很重要", "对我们很重要", "对我真的很重要"))
            for fact in user_facts
        )
        emotional = any(
            any(word in fact.text for word in ("难过", "哭", "低谷", "争吵", "生你的气", "压力"))
            for fact in user_facts
        )
        days = len({fact.occurred_at.date() for fact in user_facts})
        sustained = days >= 3 and len(user_turn_facts) >= 6
        importance = min(
            0.95,
            0.25
            + 0.25 * explicit
            + 0.15 * emotional
            + 0.1 * (days >= 2)
            + 0.15 * (len(user_facts) >= 3)
            + 0.15 * sustained,
        )
        relationship_significance = min(
            0.95, 0.25 + 0.3 * explicit + 0.15 * emotional + 0.15 * (days >= 2) + 0.15 * sustained
        )
        status = ExperienceStatus.OPEN if active else ExperienceStatus.CANDIDATE
        completed_loop = any(
            reference.kind is ExperienceEvidenceKind.OPEN_LOOP
            and self.memory.store.get_open_loop(reference.id, candidate.user_id).status.value
            == "resolved"
            for reference in unique.values()
        )
        if (
            (candidate.requested_action is ExperienceAction.CLOSE or completed_loop) and active
        ) or (before and before.status is ExperienceStatus.CLOSED):
            status = ExperienceStatus.CLOSED
        participants = (
            [candidate.user_id]
            if candidate.type is ExperienceType.USER
            else (
                [candidate.companion_id]
                if candidate.type is ExperienceType.CHARACTER
                else [candidate.user_id, candidate.companion_id]
            )
        )
        selected = (
            user_facts if len(user_facts) <= 3 else [user_facts[0], user_facts[-2], user_facts[-1]]
        )
        excerpts = [
            f"{fact.occurred_at.date().isoformat()} 用户表示："
            + (fact.text if len(fact.text) <= 350 else "（长消息，详情见原始证据）")
            for fact in selected
        ]
        if candidate.type is ExperienceType.CHARACTER:
            summary = (
                f"角色参与了关于「{candidate.title}」的对话，"
                f"留下 {len(assistant_facts)} 次可核查回应。"
            )
        else:
            prefix = (
                "双方围绕此事进行了交流。"
                if candidate.type is ExperienceType.SHARED
                else "用户叙述的经历；不代表角色亲历用户生活。"
            )
            summary = prefix + "\n" + "\n".join(excerpts)
        identifier = (
            before.experience_id
            if before
            else hashlib.sha256(
                (
                    "\0".join(
                        [
                            *candidate.key.values,
                            candidate.anchor_id,
                            candidate.type.value,
                            candidate.candidate_id,
                        ]
                    )
                ).encode()
            ).hexdigest()
        )
        return ExperienceRecord(
            **candidate.key.model_dump(),
            experience_id=identifier,
            type=candidate.type,
            title=candidate.title,
            summary=summary,
            participants=participants,
            started_at=ordered[0].occurred_at,
            ended_at=ordered[-1].occurred_at if status is ExperienceStatus.CLOSED else None,
            last_event_at=ordered[-1].occurred_at,
            topic_keys=list(
                dict.fromkeys([*(before.topic_keys if before else []), *candidate.topic_keys])
            ),
            evidence_refs=list(unique.values()),
            facts=ordered,
            importance=importance,
            emotional_significance=0.75 if emotional else 0.1,
            relationship_significance=relationship_significance,
            explicit_user_importance=explicit,
            status=status,
            anchor_id=candidate.anchor_id,
            revision=before.revision if before else 0,
        )

    def commit(self, candidate: ExperienceCandidate) -> ExperienceDecision:
        with self.store.database.atomic():
            prior = self.store.stage(candidate)
            if prior is not None:
                return prior
            before = (
                self.store.get(candidate.key, candidate.target_id)
                if candidate.target_id
                else next(
                    (
                        item
                        for item in self.store.list_experiences(candidate.key)
                        if item.anchor_id == candidate.anchor_id
                        and item.type is candidate.type
                        and item.status is not ExperienceStatus.SUPERSEDED
                    ),
                    None,
                )
            )
            if before and (
                before.type is not candidate.type or before.status is ExperienceStatus.SUPERSEDED
            ):
                raise ValueError("cannot change experience owner, type or superseded record")
            if candidate.expected_revision is not None and (
                before is None or before.revision != candidate.expected_revision
            ):
                raise RelationshipConflictError("experience candidate targets a stale revision")
            record = self._materialize(candidate, before)
            comparison = {"revision", "updated_at"}
            action = ExperienceAction.CREATE if before is None else ExperienceAction.MERGE
            if before and before.model_dump(exclude=comparison) == record.model_dump(
                exclude=comparison
            ):
                action = ExperienceAction.NO_OP
                record = before
            else:
                if (
                    before
                    and before.status is ExperienceStatus.CANDIDATE
                    and record.status in ACTIVE_STATUSES
                ):
                    action = ExperienceAction.PROMOTE
                elif record.status is ExperienceStatus.CLOSED:
                    action = ExperienceAction.CLOSE
                record = self.store.save(record, before, action.value)
            decision = ExperienceDecision(
                candidate_id=candidate.candidate_id,
                action=action,
                experience_id=record.experience_id,
                revision=record.revision,
                reason="validated_source_projection",
            )
            self.store.acknowledge(candidate.key, decision)
            return decision

    def get(
        self, key: RelationshipKey, experience_id: str, *, as_of: datetime | None = None
    ) -> ExperienceRecord:
        at = as_of or now_utc()
        with self.store.database.atomic():
            record = self.store.get(key, experience_id)
            if record.status is ExperienceStatus.SUPERSEDED:
                return record
            valid = True
            # Verify captured evidence; never silently substitute changed content.
            for fact in record.facts:
                try:
                    current = self.facts_for(key, fact.evidence_ref, as_of=at)
                    valid = valid and current == [fact]
                except (KeyError, ValueError):
                    valid = False
            if not valid:
                invalidated = record.model_copy(deep=True)
                invalidated.status = ExperienceStatus.SUPERSEDED
                invalidated.title = "已失效经历"
                invalidated.summary = "经历的原始证据已变化或失效，停止使用旧摘要。"
                invalidated.facts = []
                return self.store.save(invalidated, record, "evidence_invalidated")
            if record.status is ExperienceStatus.OPEN and at - record.last_event_at >= timedelta(
                days=self.config.dormant_after_days
            ):
                dormant = record.model_copy(deep=True)
                dormant.status = ExperienceStatus.DORMANT
                return self.store.save(dormant, record, "dormant")
            return record

    def list_experiences(
        self, key: RelationshipKey, *, include_candidates: bool = False
    ) -> list[ExperienceRecord]:
        values = [self.get(key, item.experience_id) for item in self.store.list_experiences(key)]
        return [
            item
            for item in values
            if item.status in ACTIVE_STATUSES
            or (include_candidates and item.status is ExperienceStatus.CANDIDATE)
        ]

    def candidates(self, key: RelationshipKey) -> list[dict[str, Any]]:
        rows = self.store.candidates(key)
        for row in rows:
            proposal = ExperienceCandidate.model_validate(row["candidate"])
            try:
                for reference in proposal.evidence_refs:
                    self.facts_for(key, reference)
            except (KeyError, ValueError):
                row["candidate"]["title"] = "证据已失效的经历候选"
                row["candidate"]["topic_keys"] = []
        return rows

    def roots(self, record: ExperienceRecord) -> set[str]:
        roots = {ref.key for ref in record.evidence_refs}
        roots.update(fact.evidence_ref.key for fact in record.facts)
        for ref in record.evidence_refs:
            if ref.kind is ExperienceEvidenceKind.MEMORY:
                roots.update(
                    f"turn:{identifier}"
                    for identifier in self.memory.store.get(
                        ref.id, record.user_id
                    ).evidence_turn_ids
                )
            elif ref.kind is ExperienceEvidenceKind.OPEN_LOOP:
                loop = self.memory.store.get_open_loop(ref.id, record.user_id)
                if loop.source_turn_id:
                    roots.add(f"turn:{loop.source_turn_id}")
        return roots

    def recall(
        self,
        key: RelationshipKey,
        query: str,
        *,
        memory_use_plan: MemoryUsePlan | None = None,
        allow_sensitive: bool = False,
        explicit_recall: bool = False,
        calendar_timezone: str = "UTC",
        as_of: datetime | None = None,
    ) -> list[ExperienceRecallItem]:
        from companion_agent.experience.evaluator import topic_for
        from companion_memoryos.temporal import extract_temporal_hint

        modes = {
            f"{d.evidence.kind.value}:{d.evidence.id}": d.mode
            for d in (memory_use_plan or MemoryUsePlan()).decisions
        }
        query_topic, _ = topic_for(query)
        temporal = extract_temporal_hint(query, as_of or now_utc(), calendar_timezone)
        matches: list[ExperienceRecallItem] = []
        for record in self.list_experiences(key):
            if (
                explicit_recall
                and temporal.has_window
                and not any(
                    (temporal.start is None or fact.occurred_at >= temporal.start)
                    and (temporal.end is None or fact.occurred_at < temporal.end)
                    for fact in record.facts
                )
            ):
                continue
            relevant = sum(topic.casefold() in query.casefold() for topic in record.topic_keys)
            if query_topic and query_topic in record.topic_keys:
                relevant += 2
            if not relevant:
                continue
            try:
                for fact in record.facts:
                    self.facts_for(key, fact.evidence_ref, allow_sensitive=allow_sensitive)
                roots = self.roots(record)
            except (KeyError, ValueError):
                continue
            references = [
                MemoryEvidenceRef(
                    kind=MemoryEvidenceKind(ref.split(":", 1)[0]), id=ref.split(":", 1)[1]
                )
                for ref in roots
                if ref.split(":", 1)[0] in {kind.value for kind in MemoryEvidenceKind}
            ]
            feedback = self.memory.store.latest_reference_feedback(
                key.user_id,
                MemoryScope(companion_id=key.companion_id, relationship_id=key.relationship_id),
                references,
                now_utc(),
            )
            if any(item.kind in SUPPRESSING_FEEDBACK for item in feedback.values()):
                continue
            inherited = {modes[ref] for ref in roots if ref in modes}
            if MemoryReferenceMode.SUPPRESS in inherited:
                continue
            mode = (
                MemoryReferenceMode.EXPLICIT_RECALL
                if explicit_recall
                else MemoryReferenceMode.SILENT_INFLUENCE
            )
            for restriction in (
                MemoryReferenceMode.CLARIFY,
                MemoryReferenceMode.SILENT_INFLUENCE,
                MemoryReferenceMode.SOFT_REFERENCE,
            ):
                if restriction in inherited:
                    mode = restriction
                    break
            matches.append(
                ExperienceRecallItem(
                    experience=record, score=float(relevant) + record.importance, use_mode=mode
                )
            )
        matches.sort(
            key=lambda item: (
                item.experience.type is not ExperienceType.SHARED,
                -item.score,
                -item.experience.last_event_at.timestamp(),
            )
        )
        # User/character/shared are correlated views, not three independent historical events.
        selected: list[ExperienceRecallItem] = []
        anchors: set[str] = set()
        covered_facts: set[str] = set()
        for item in matches:
            fact_ids = {fact.evidence_ref.key for fact in item.experience.facts}
            if item.experience.anchor_id not in anchors and not fact_ids.issubset(covered_facts):
                selected.append(item)
                anchors.add(item.experience.anchor_id)
                covered_facts.update(fact_ids)
        return selected[: self.config.recall_limit]

    def trace(self, key: RelationshipKey, experience_id: str) -> list[ExperienceFact]:
        record = self.get(key, experience_id)
        return record.facts if record.status is not ExperienceStatus.SUPERSEDED else []

    def set_status(
        self,
        key: RelationshipKey,
        experience_id: str,
        status: ExperienceStatus,
        *,
        expected_revision: int,
        evidence_refs: list[ExperienceEvidenceRef],
    ) -> ExperienceRecord:
        if status is ExperienceStatus.CANDIDATE or not evidence_refs:
            raise ValueError("lifecycle change requires evidence and a supported target status")
        with self.store.database.atomic():
            before = self.get(key, experience_id)
            if before.revision != expected_revision or before.status is ExperienceStatus.SUPERSEDED:
                raise RelationshipConflictError("experience lifecycle revision is stale")
            for reference in evidence_refs:
                self.facts_for(key, reference)
            proposal = ExperienceCandidate(
                **key.model_dump(),
                candidate_id=f"lifecycle-{experience_id}-{expected_revision}",
                type=before.type,
                title=before.title,
                topic_keys=before.topic_keys,
                anchor_id=before.anchor_id,
                evidence_refs=evidence_refs,
                requested_action=ExperienceAction.CLOSE
                if status is ExperienceStatus.CLOSED
                else ExperienceAction.UPDATE,
            )
            after = self._materialize(proposal, before)
            if after.status is ExperienceStatus.CANDIDATE and status in ACTIVE_STATUSES:
                raise ValueError("insufficient evidence to activate this experience")
            after.status = status
            after.ended_at = after.last_event_at if status is ExperienceStatus.CLOSED else None
            return self.store.save(after, before, status.value)

    def merge(
        self, key: RelationshipKey, target_id: str, source_id: str, *, expected_revision: int
    ) -> ExperienceRecord:
        if target_id == source_id:
            raise ValueError("cannot merge experience into itself")
        with self.store.database.atomic():
            target, source = self.get(key, target_id), self.get(key, source_id)
            if target.type is not source.type or source.status is ExperienceStatus.SUPERSEDED:
                raise ValueError("experience merge requires matching types and active sources")
            candidate = ExperienceCandidate(
                **key.model_dump(),
                candidate_id=hashlib.sha256(
                    f"merge:{target_id}:{source_id}:{source.revision}".encode()
                ).hexdigest(),
                type=target.type,
                title=target.title,
                topic_keys=source.topic_keys,
                anchor_id=target.anchor_id,
                target_id=target_id,
                expected_revision=expected_revision,
                evidence_refs=source.evidence_refs,
                requested_action=ExperienceAction.MERGE,
            )
            self.commit(candidate)
            merged = self.get(key, target_id)
            if (
                source.status in {ExperienceStatus.OPEN, ExperienceStatus.DORMANT}
                and merged.status is ExperienceStatus.CLOSED
            ):
                reopened = merged.model_copy(deep=True)
                reopened.status, reopened.ended_at = ExperienceStatus.OPEN, None
                self.store.save(reopened, merged, "reopened_by_merge")
            superseded = source.model_copy(deep=True)
            superseded.status, superseded.superseded_by = ExperienceStatus.SUPERSEDED, target_id
            self.store.save(superseded, source, "merged_into")
            return self.get(key, target_id)

    def history(self, key: RelationshipKey, experience_id: str) -> list[dict[str, Any]]:
        revisions = self.store.history(key, experience_id)
        for revision in revisions:
            for field in ("before", "after"):
                snapshot = revision[field]
                if not snapshot:
                    continue
                old = ExperienceRecord.model_validate(snapshot)
                try:
                    for fact in old.facts:
                        if self.facts_for(key, fact.evidence_ref) != [fact]:
                            raise ValueError("changed source")
                except (KeyError, ValueError):
                    revision[field] = None
                    revision["redacted"] = True
        return revisions
