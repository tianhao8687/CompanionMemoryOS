"""Relationship changes pass through evidence validation and candidate decisions."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from functools import cached_property
from typing import TYPE_CHECKING, Any

from companion_agent.persona.models import RelationshipStage
from companion_agent.relationship.models import (
    CompiledRelationshipContext,
    EvidenceStrength,
    RelationshipAction,
    RelationshipBoundary,
    RelationshipChangeType,
    RelationshipConfig,
    RelationshipDecision,
    RelationshipDynamics,
    RelationshipEvidenceKind,
    RelationshipEvidenceRef,
    RelationshipIdentity,
    RelationshipKey,
    RelationshipMilestone,
    RelationshipModel,
    RelationshipPattern,
    RelationshipPatternStatus,
    RelationshipRevision,
    RelationshipStageState,
    RelationshipThread,
    RelationshipThreadStatus,
    RelationshipUpdateCandidate,
    RelationshipUpdateKind,
    now_utc,
)
from companion_agent.relationship.store import RelationshipConflictError, RelationshipStore
from companion_agent.semantics import RelationshipIdentityType
from companion_memoryos.schemas import (
    ConsentState,
    ConversationRole,
    EvidenceActor,
    ExperienceEvidenceKind,
    ExperienceEvidenceRef,
    MemoryKind,
    MemoryReferenceMode,
    MemoryStatus,
    MemoryUsePlan,
    RealityLayer,
    ResolutionStatus,
    ResponseGoal,
    Sensitivity,
    TurnDeletionState,
)
from companion_memoryos.service import CompanionMemoryService
from companion_memoryos.turn_layers import turn_reality_layer

if TYPE_CHECKING:
    from companion_agent.experience.service import ExperienceService


def candidate_for(
    kind: RelationshipUpdateKind,
    description: str,
    evidence_ids: list[str],
    proposed_change: dict[str, Any],
    created_at: datetime,
    *,
    strength: EvidenceStrength = EvidenceStrength.DIRECT,
    confidence: float = 1.0,
) -> RelationshipUpdateCandidate:
    body = json.dumps(
        {"kind": kind.value, "evidence": sorted(evidence_ids), "change": proposed_change},
        sort_keys=True,
        default=str,
    )
    return RelationshipUpdateCandidate(
        candidate_id=hashlib.sha256(body.encode()).hexdigest(),
        kind=kind,
        description=description,
        confidence=confidence,
        evidence_ids=evidence_ids,
        created_at=created_at,
        strength=strength,
        proposed_change=proposed_change,
    )


class RelationshipService:
    def __init__(
        self, memory: CompanionMemoryService, config: RelationshipConfig | None = None
    ) -> None:
        self.memory = memory
        self.store = RelationshipStore(memory.store.database)
        self.config = config or RelationshipConfig()

    @cached_property
    def experiences(self) -> ExperienceService:
        from companion_agent.experience.service import ExperienceService

        return ExperienceService(self.memory)

    def initialize_identity(
        self,
        key: RelationshipKey,
        identity_type: RelationshipIdentityType,
        *,
        labels: list[str] | None = None,
        description: str | None = None,
    ) -> RelationshipModel:
        """Trusted host records the user's explicit relationship choice at character creation."""
        if identity_type is RelationshipIdentityType.UNDEFINED:
            raise ValueError("choose an explicit identity type")
        data = {
            "type": identity_type.value,
            "labels": labels or [identity_type.value],
            "description": description,
        }
        identifier = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
        with self.store.database.atomic() as connection:
            row = connection.execute(
                "SELECT data_json FROM agent_relationship_identity_configs "
                "WHERE user_id=? AND companion_id=? AND relationship_id=? AND id=?",
                (*key.values, identifier),
            ).fetchone()
            event: dict[str, Any] = (
                json.loads(row["data_json"])
                if row
                else {"identity": data, "created_at": now_utc().isoformat()}
            )
            connection.execute(
                "INSERT OR IGNORE INTO agent_relationship_identity_configs VALUES (?, ?, ?, ?, ?)",
                (*key.values, identifier, json.dumps(event)),
            )
            return self.commit_candidates(
                key,
                [
                    candidate_for(
                        RelationshipUpdateKind.IDENTITY,
                        "用户在角色创建时明确选择关系身份",
                        [f"configuration:{identifier}"],
                        data,
                        datetime.fromisoformat(event["created_at"]),
                    )
                ],
            )

    def _evidence_time(
        self,
        key: RelationshipKey,
        value: str,
        as_of: datetime,
        seen: set[str] | None = None,
        *,
        allow_sensitive: bool = True,
    ) -> datetime:
        seen = set(seen or ())
        if value in seen:
            raise ValueError("cyclic relationship evidence")
        seen.add(value)
        ref = RelationshipEvidenceRef.parse(value)
        if ref.kind is RelationshipEvidenceKind.CONFIGURATION:
            with self.store.database.connection() as connection:
                row = connection.execute(
                    "SELECT data_json FROM agent_relationship_identity_configs "
                    "WHERE user_id=? AND companion_id=? AND relationship_id=? AND id=?",
                    (*key.values, ref.id),
                ).fetchone()
            if row is None:
                raise ValueError("identity configuration evidence is unavailable")
            created = datetime.fromisoformat(json.loads(row["data_json"])["created_at"])
            if created > as_of:
                raise ValueError("future identity configuration")
            return created
        if ref.kind is RelationshipEvidenceKind.EXPERIENCE:
            from companion_agent.experience.models import ExperienceType
            from companion_agent.experience.service import ACTIVE_STATUSES

            experience = self.experiences.get(key, ref.id)
            if (
                experience.type is not ExperienceType.SHARED
                or experience.status not in ACTIVE_STATUSES
            ):
                raise ValueError("relationship requires a validated shared experience")
            for fact in experience.facts:
                self.experiences.facts_for(
                    key, fact.evidence_ref, as_of=as_of, allow_sensitive=allow_sensitive
                )
            return experience.last_event_at
        if ref.kind is RelationshipEvidenceKind.MILESTONE:
            model = self.store.get(key)
            item = next((m for m in model.milestones if m.id == ref.id), None) if model else None
            if item is None or item.status.value != "active":
                raise ValueError("milestone evidence is unavailable")
            return max(
                self._evidence_time(key, evidence, as_of, seen, allow_sensitive=allow_sensitive)
                for evidence in item.evidence_ids
            )
        source: Any
        if ref.kind in {RelationshipEvidenceKind.TURN, RelationshipEvidenceKind.USER_CORRECTION}:
            source = self.memory.store.get_turn(ref.id, key.user_id)
            if (
                source.deletion_state is not TurnDeletionState.ACTIVE
                or source.metadata.get("content_redacted_at")
                or source.role is not ConversationRole.USER
                or source.actor_id != key.user_id
                or turn_reality_layer(
                    source.content,
                    json.dumps(source.metadata),
                    json.dumps([span.model_dump(mode="json") for span in source.speech_spans]),
                )
                != RealityLayer.REAL_WORLD.value
                or not self.memory._direct_user_discourse_text(source).strip()
            ):
                raise ValueError("relationship evidence must be an active direct user turn")
            at = source.occurred_at
        elif ref.kind in {
            RelationshipEvidenceKind.MEMORY,
            RelationshipEvidenceKind.RELATIONSHIP_MEMORY,
        }:
            source = self.memory.store.get(ref.id, key.user_id)
            if (
                source.status is not MemoryStatus.ACTIVE
                or source.reality_layer is not RealityLayer.REAL_WORLD
                or source.source_actor is not EvidenceActor.AUTHENTICATED_USER
                or source.subject_actor_id not in {None, key.user_id}
                or source.quote_depth != 0
                or source.resolution_status is not ResolutionStatus.RESOLVED
                or (source.expires_at and source.expires_at <= as_of)
                or (
                    ref.kind is RelationshipEvidenceKind.RELATIONSHIP_MEMORY
                    and source.kind is not MemoryKind.RELATIONSHIP
                )
            ):
                raise ValueError("memory is not eligible relationship evidence")
            for turn_id in source.evidence_turn_ids:
                self._evidence_time(
                    key, f"turn:{turn_id}", as_of, seen, allow_sensitive=allow_sensitive
                )
            at = source.event_at
        elif ref.kind is RelationshipEvidenceKind.EVENT:
            source = self.memory.store.get_event(ref.id, key.user_id)
            if source.status.value != "active" or source.role is not ConversationRole.USER:
                raise ValueError("event is not active user evidence")
            at = source.occurred_at
        else:
            source = self.memory.store.get_open_loop(ref.id, key.user_id)
            if not source.source_turn_id:
                raise ValueError("open loop requires a source turn")
            source_at = self._evidence_time(
                key, f"turn:{source.source_turn_id}", as_of, seen, allow_sensitive=allow_sensitive
            )
            at = source_at
            update_source = source.metadata.get("last_update_source_turn_id")
            if isinstance(update_source, str) and update_source != source.source_turn_id:
                at = max(
                    at,
                    self._evidence_time(
                        key, f"turn:{update_source}", as_of, seen, allow_sensitive=allow_sensitive
                    ),
                )
        if (
            source.user_id != key.user_id
            or source.scope.companion_id != key.companion_id
            or source.scope.relationship_id != key.relationship_id
            or source.scope.group_id is not None
            or source.consent is not ConsentState.GRANTED
        ):
            raise ValueError("relationship evidence has wrong owner, scope or consent")
        if not allow_sensitive and source.sensitivity is not Sensitivity.NORMAL:
            raise ValueError("sensitive relationship evidence excluded")
        if at > as_of:
            raise ValueError("future relationship evidence cannot affect present state")
        if not isinstance(at, datetime):
            raise ValueError("evidence timestamp is unavailable")
        return at

    def evidence_valid(
        self,
        key: RelationshipKey,
        evidence: str,
        as_of: datetime,
        *,
        allow_sensitive: bool = True,
    ) -> bool:
        try:
            self._evidence_time(key, evidence, as_of, allow_sensitive=allow_sensitive)
            return True
        except (KeyError, ValueError):
            return False

    def get_relationship(
        self, key: RelationshipKey, *, as_of: datetime | None = None
    ) -> RelationshipModel:
        at = as_of or now_utc()
        with self.store.database.atomic():
            model = self.store.get(key) or self.store.create(
                RelationshipModel(
                    **key.model_dump(),
                    started_at=at,
                    updated_at=at,
                    stage_state=RelationshipStageState(entered_at=at),
                    recent_dynamics=RelationshipDynamics(updated_at=at),
                )
            )
            sanitized = self._sanitize(model, max(at, now_utc()))
            if sanitized != model:
                return self.store.save(
                    model,
                    sanitized,
                    RelationshipChangeType.EVIDENCE_INVALIDATED,
                    "已移除失效或撤回证据支持的关系状态",
                    [],
                    at,
                )
            return model

    def _sanitize(self, model: RelationshipModel, at: datetime) -> RelationshipModel:
        clean = model.model_copy(deep=True)

        def valid(values: list[str]) -> bool:
            return bool(values) and all(self.evidence_valid(model.key, item, at) for item in values)

        for field in ("patterns", "milestones", "unresolved_threads", "boundaries"):
            setattr(
                clean, field, [item for item in getattr(model, field) if valid(item.evidence_ids)]
            )
        clean.interactions = {ref: time for ref, time in model.interactions.items() if valid([ref])}
        clean.last_interaction_at = max(clean.interactions.values(), default=None)
        clean.shared_experiences = {
            ref: time for ref, time in model.shared_experiences.items() if valid([ref])
        }
        if model.interactions and not model.started_at_evidence_ids:
            clean.started_at = min(clean.interactions.values(), default=at)
        if model.identity.evidence_ids and not valid(model.identity.evidence_ids):
            clean.identity = RelationshipIdentity()
        if model.recent_dynamics.evidence_ids and not valid(model.recent_dynamics.evidence_ids):
            clean.recent_dynamics = RelationshipDynamics(updated_at=at)
        if model.distance_evidence_ids and not valid(model.distance_evidence_ids):
            clean.distance_ceiling = None
            clean.distance_evidence_ids = []
        if model.started_at_evidence_ids and not valid(model.started_at_evidence_ids):
            clean.started_at = min(clean.interactions.values(), default=at)
            clean.started_at_evidence_ids = []
        if model.stage_state.evidence_ids and not valid(model.stage_state.evidence_ids):
            clean.stage = RelationshipStage.NEW
            clean.stage_state = RelationshipStageState(
                entered_at=at, reasons=["原阶段依据已失效，重新积累有效历史"]
            )
        return clean

    def stage_candidates(
        self, key: RelationshipKey, candidates: list[RelationshipUpdateCandidate]
    ) -> None:
        with self.store.database.atomic():
            for candidate in candidates:
                if candidate.kind in {
                    RelationshipUpdateKind.DISTANCE,
                    RelationshipUpdateKind.TEMPORAL_CORRECTION,
                    RelationshipUpdateKind.INTERACTION,
                } and any(
                    RelationshipEvidenceRef.parse(ref).kind
                    not in {
                        RelationshipEvidenceKind.TURN,
                        RelationshipEvidenceKind.USER_CORRECTION,
                    }
                    for ref in candidate.evidence_ids
                ):
                    raise ValueError(
                        "identity, distance, duration and activity require user turn evidence"
                    )
                if candidate.kind is RelationshipUpdateKind.IDENTITY and any(
                    RelationshipEvidenceRef.parse(ref).kind
                    not in {
                        RelationshipEvidenceKind.TURN,
                        RelationshipEvidenceKind.USER_CORRECTION,
                        RelationshipEvidenceKind.CONFIGURATION,
                    }
                    for ref in candidate.evidence_ids
                ):
                    raise ValueError(
                        "identity requires a direct statement or explicit host configuration"
                    )
                for evidence in candidate.evidence_ids:
                    self._evidence_time(key, evidence, candidate.created_at)
                self.store.stage_candidate(key, candidate)

    def _apply(
        self,
        model: RelationshipModel,
        candidate: RelationshipUpdateCandidate,
    ) -> tuple[RelationshipModel, RelationshipAction, RelationshipChangeType]:
        updated = model.model_copy(deep=True)
        data = dict(candidate.proposed_change)
        refs = candidate.evidence_ids
        at = candidate.created_at
        direct = candidate.strength is EvidenceStrength.DIRECT
        kind = candidate.kind
        action = RelationshipAction.UPDATE
        change = RelationshipChangeType.IDENTITY_UPDATED
        # Weak candidates remain durable proposals; only patterns collect repeat observations.
        if (
            candidate.strength is EvidenceStrength.WEAK
            and kind is not RelationshipUpdateKind.PATTERN
        ):
            return model, RelationshipAction.NO_OP, change
        if kind is RelationshipUpdateKind.INTERACTION:
            for ref in refs:
                updated.interactions.setdefault(ref, self._evidence_time(model.key, ref, at))
            updated.last_interaction_at = max(updated.interactions.values())
            if not updated.started_at_evidence_ids:
                updated.started_at = min(updated.interactions.values())
            change = RelationshipChangeType.INTERACTION_RECORDED
        elif kind is RelationshipUpdateKind.IDENTITY:
            if not direct:
                return model, RelationshipAction.NO_OP, change
            if model.identity.confirmed_at and model.identity.confirmed_at > at:
                return model, RelationshipAction.NO_OP, change
            updated.identity = RelationshipIdentity.model_validate(
                {
                    **data,
                    "confirmed_by_user": True,
                    "confirmed_at": at,
                    "evidence_ids": refs,
                }
            )
        elif kind is RelationshipUpdateKind.EXPERIENCE:
            for ref in refs:
                if (
                    RelationshipEvidenceRef.parse(ref).kind
                    is not RelationshipEvidenceKind.EXPERIENCE
                ):
                    raise ValueError("shared history links require experience evidence")
                updated.shared_experiences[ref] = self._evidence_time(model.key, ref, at)
            change = RelationshipChangeType.EXPERIENCE_LINKED
        elif kind is RelationshipUpdateKind.PATTERN:
            old = next((item for item in model.patterns if item.id == data["id"]), None)
            if old is None:
                signature = (
                    " ".join(data["description"].split()).casefold(),
                    data["category"],
                    sorted(key.casefold() for key in data.get("context_keys", [])),
                )
                old = next(
                    (
                        item
                        for item in model.patterns
                        if (
                            " ".join(item.description.split()).casefold(),
                            item.category.value,
                            sorted(key.casefold() for key in item.context_keys),
                        )
                        == signature
                    ),
                    None,
                )
                if old is not None:
                    data["id"] = old.id
            evidence = list(dict.fromkeys([*(old.evidence_ids if old else []), *refs]))
            if old and set(evidence) == set(old.evidence_ids):
                return model, RelationshipAction.NO_OP, RelationshipChangeType.PATTERN_UPDATED
            observation_times = [self._evidence_time(model.key, ref, at) for ref in evidence]
            first, last = min(observation_times), max(observation_times)
            established = (
                old is not None and old.status is RelationshipPatternStatus.ESTABLISHED
            ) or (
                len(evidence) >= self.config.pattern_observations
                and (last - first).total_seconds() >= self.config.pattern_span_days * 86400
                and candidate.strength is not EvidenceStrength.WEAK
            )
            # Explicit stable preference is actionable immediately, but still isn't closeness.
            explicit_stable = bool(data.pop("explicit_stable", False))
            established = established or (direct and explicit_stable)
            confidence = max(old.confidence if old else 0, candidate.confidence)
            if old:
                confidence = min(0.99, confidence + (1 - confidence) * 0.2)
            pattern = RelationshipPattern.model_validate(
                {
                    **data,
                    "confidence": confidence,
                    "evidence_ids": evidence,
                    "first_observed_at": first,
                    "last_observed_at": last,
                    "observation_count": len(evidence),
                    "status": "established" if established else "candidate",
                }
            )
            updated.patterns = [p for p in model.patterns if p.id != pattern.id] + [pattern]
            action = RelationshipAction.MERGE if old else RelationshipAction.ADD
            change = (
                RelationshipChangeType.PATTERN_UPDATED
                if old
                else RelationshipChangeType.PATTERN_ADDED
            )
        elif kind is RelationshipUpdateKind.MILESTONE:
            milestone = RelationshipMilestone.model_validate({**data, "evidence_ids": refs})
            if milestone.importance < self.config.milestone_min_importance:
                return model, RelationshipAction.NO_OP, RelationshipChangeType.MILESTONE_ADDED
            old_milestone = next((m for m in model.milestones if m.id == milestone.id), None)
            if old_milestone:
                milestone.evidence_ids = list(dict.fromkeys([*old_milestone.evidence_ids, *refs]))
            updated.milestones = [m for m in model.milestones if m.id != milestone.id] + [milestone]
            change = (
                RelationshipChangeType.MILESTONE_UPDATED
                if old_milestone
                else RelationshipChangeType.MILESTONE_ADDED
            )
            action = RelationshipAction.MERGE if old_milestone else RelationshipAction.ADD
        elif kind is RelationshipUpdateKind.THREAD:
            old_thread = next((t for t in model.unresolved_threads if t.id == data["id"]), None)
            if old_thread and old_thread.last_updated_at > at:
                return model, RelationshipAction.NO_OP, RelationshipChangeType.THREAD_UPDATED
            thread = RelationshipThread.model_validate(
                {
                    **(old_thread.model_dump() if old_thread else {}),
                    **data,
                    "opened_at": old_thread.opened_at if old_thread else at,
                    "last_updated_at": at,
                    "evidence_ids": list(
                        dict.fromkeys([*(old_thread.evidence_ids if old_thread else []), *refs])
                    ),
                }
            )
            updated.unresolved_threads = [
                t for t in model.unresolved_threads if t.id != thread.id
            ] + [thread]
            change = (
                RelationshipChangeType.THREAD_UPDATED
                if old_thread
                else RelationshipChangeType.THREAD_OPENED
            )
            action = RelationshipAction.UPDATE if old_thread else RelationshipAction.ADD
            if thread.status is RelationshipThreadStatus.RESOLVED:
                change, action = RelationshipChangeType.THREAD_RESOLVED, RelationshipAction.RESOLVE
        elif kind is RelationshipUpdateKind.BOUNDARY:
            if not direct and len(refs) < self.config.pattern_observations:
                return model, RelationshipAction.NO_OP, RelationshipChangeType.BOUNDARY_UPDATED
            old_boundary = next((b for b in model.boundaries if b.id == data["id"]), None)
            if old_boundary and old_boundary.updated_at > at:
                return model, RelationshipAction.NO_OP, RelationshipChangeType.BOUNDARY_UPDATED
            boundary = RelationshipBoundary.model_validate(
                {
                    **data,
                    "evidence_ids": refs,
                    "confidence": candidate.confidence,
                    "source": "direct_user_statement" if direct else "repeated_feedback",
                    "created_at": old_boundary.created_at if old_boundary else at,
                    "updated_at": at,
                }
            )
            updated.boundaries = [b for b in model.boundaries if b.id != boundary.id] + [boundary]
            change = RelationshipChangeType.BOUNDARY_UPDATED
        elif kind is RelationshipUpdateKind.DYNAMICS:
            if model.recent_dynamics.evidence_ids and at < model.recent_dynamics.updated_at:
                return model, RelationshipAction.NO_OP, RelationshipChangeType.DYNAMICS_UPDATED
            updated.recent_dynamics = RelationshipDynamics.model_validate(
                {**data, "updated_at": at, "evidence_ids": refs}
            )
            change = RelationshipChangeType.DYNAMICS_UPDATED
        elif kind is RelationshipUpdateKind.TEMPORAL_CORRECTION:
            if not direct:
                return model, RelationshipAction.NO_OP, RelationshipChangeType.TEMPORAL_CORRECTED
            corrected = datetime.fromisoformat(data["started_at"])
            if corrected.tzinfo is None or corrected > at:
                raise ValueError("corrected relationship start must be an aware past timestamp")
            updated.started_at = corrected
            updated.started_at_evidence_ids = refs
            change = RelationshipChangeType.TEMPORAL_CORRECTED
        elif kind is RelationshipUpdateKind.DISTANCE:
            if not direct:
                return model, RelationshipAction.NO_OP, RelationshipChangeType.DISTANCE_CHANGED
            updated.distance_ceiling = (
                RelationshipStage(data["ceiling"]) if data["ceiling"] else None
            )
            updated.distance_evidence_ids = refs
            change = RelationshipChangeType.DISTANCE_CHANGED
        if updated == model:
            return model, RelationshipAction.NO_OP, change
        return RelationshipModel.model_validate(updated.model_dump()), action, change

    def preview(
        self,
        key: RelationshipKey,
        candidates: list[RelationshipUpdateCandidate],
        *,
        as_of: datetime | None = None,
    ) -> RelationshipModel:
        from companion_agent.relationship.transitions import STAGES, evaluate_transition

        at = as_of or now_utc()
        model = self.get_relationship(key, as_of=at)
        prior_state = evaluate_transition(model, self.config, at)
        for candidate in candidates:
            for evidence in candidate.evidence_ids:
                self._evidence_time(key, evidence, at)
            model, _, _ = self._apply(model, candidate)
        state = evaluate_transition(model, self.config, at)
        if STAGES.index(prior_state.stage) < STAGES.index(model.stage) and STAGES.index(
            state.stage
        ) > STAGES.index(prior_state.stage):
            state = prior_state
        model.stage, model.stage_state = state.stage, state
        return model

    def commit_candidates(
        self,
        key: RelationshipKey,
        candidates: list[RelationshipUpdateCandidate],
        *,
        expected_revision: int | None = None,
        as_of: datetime | None = None,
    ) -> RelationshipModel:
        from companion_agent.relationship.transitions import STAGES, evaluate_transition

        at = as_of or now_utc()
        with self.store.database.atomic():
            model = self.get_relationship(key, as_of=at)
            prior_state = evaluate_transition(model, self.config, at)
            if expected_revision is not None and model.revision != expected_revision:
                raise RelationshipConflictError("relationship revision changed during generation")
            self.stage_candidates(key, candidates)
            receipts = {c.candidate_id: d for c, d in self.store.candidates(key) if d is not None}
            for candidate in candidates:
                if candidate.candidate_id in receipts:
                    continue
                for evidence in candidate.evidence_ids:
                    self._evidence_time(key, evidence, at)
                updated, action, change = self._apply(model, candidate)
                if action is not RelationshipAction.NO_OP:
                    model = self.store.save(
                        model, updated, change, candidate.description, candidate.evidence_ids, at
                    )
                self.store.acknowledge(
                    key,
                    RelationshipDecision(
                        candidate_id=candidate.candidate_id,
                        action=action,
                        revision=model.revision,
                        reason="candidate_applied"
                        if action is not RelationshipAction.NO_OP
                        else "insufficient_or_duplicate_evidence",
                    ),
                )
            final_state = evaluate_transition(model, self.config, at)
            # A returning message must not erase the gap that preceded it.
            if STAGES.index(prior_state.stage) < STAGES.index(model.stage) and STAGES.index(
                final_state.stage
            ) > STAGES.index(prior_state.stage):
                final_state = prior_state
            if final_state.stage is model.stage:
                return model
            after = model.model_copy(deep=True)
            after.stage, after.stage_state = final_state.stage, final_state
            return self.store.save(
                model,
                after,
                RelationshipChangeType.STAGE_CHANGED,
                "；".join(final_state.reasons),
                final_state.evidence_ids,
                at,
            )

    def evaluate_stage(
        self, key: RelationshipKey, *, as_of: datetime | None = None
    ) -> RelationshipModel:
        from companion_agent.relationship.transitions import evaluate_transition

        at = as_of or now_utc()
        with self.store.database.atomic():
            model = self.get_relationship(key, as_of=at)
            state = evaluate_transition(model, self.config, at)
            if state.stage is model.stage:
                return model
            updated = model.model_copy(deep=True)
            updated.stage, updated.stage_state = state.stage, state
            return self.store.save(
                model,
                updated,
                RelationshipChangeType.STAGE_CHANGED,
                "；".join(state.reasons),
                state.evidence_ids,
                at,
            )

    def _record(
        self,
        key: RelationshipKey,
        kind: RelationshipUpdateKind,
        item: Any,
        strength: EvidenceStrength = EvidenceStrength.DIRECT,
    ) -> RelationshipModel:
        data = item.model_dump(mode="json")
        refs = data.pop("evidence_ids")
        for field in (
            "created_at",
            "updated_at",
            "first_observed_at",
            "last_observed_at",
            "opened_at",
            "last_updated_at",
            "observation_count",
            "confirmed_at",
            "confirmed_by_user",
        ):
            data.pop(field, None)
        data.pop("confidence", None)
        if kind is RelationshipUpdateKind.PATTERN:
            data.pop("status", None)
        if kind is RelationshipUpdateKind.BOUNDARY:
            data.pop("source", None)
        candidate = candidate_for(
            kind,
            getattr(item, "description", None) or getattr(item, "summary", None) or kind.value,
            refs,
            data,
            max(self._evidence_time(key, ref, now_utc()) for ref in refs),
            strength=strength,
            confidence=getattr(item, "confidence", 1.0),
        )
        return self.commit_candidates(key, [candidate])

    def record_pattern(
        self,
        key: RelationshipKey,
        pattern: RelationshipPattern,
        *,
        strength: EvidenceStrength = EvidenceStrength.REPEATED,
    ) -> RelationshipModel:
        return self._record(key, RelationshipUpdateKind.PATTERN, pattern, strength)

    def record_milestone(
        self, key: RelationshipKey, milestone: RelationshipMilestone
    ) -> RelationshipModel:
        return self._record(key, RelationshipUpdateKind.MILESTONE, milestone)

    def open_thread(self, key: RelationshipKey, thread: RelationshipThread) -> RelationshipModel:
        return self._record(key, RelationshipUpdateKind.THREAD, thread)

    def resolve_thread(
        self,
        key: RelationshipKey,
        thread_id: str,
        evidence_ids: list[str],
        *,
        summary: str | None = None,
    ) -> RelationshipModel:
        change: dict[str, Any] = {"id": thread_id, "status": "resolved"}
        if summary:
            change["summary"] = summary
        return self.commit_candidates(
            key,
            [
                candidate_for(
                    RelationshipUpdateKind.THREAD, "关系事项已结束", evidence_ids, change, now_utc()
                )
            ],
        )

    def record_boundary(
        self, key: RelationshipKey, boundary: RelationshipBoundary
    ) -> RelationshipModel:
        strength = (
            EvidenceStrength.DIRECT
            if boundary.source.value == "direct_user_statement"
            else EvidenceStrength.REPEATED
        )
        return self._record(key, RelationshipUpdateKind.BOUNDARY, boundary, strength)

    def confirm_identity(
        self, key: RelationshipKey, identity: RelationshipIdentity
    ) -> RelationshipModel:
        return self._record(key, RelationshipUpdateKind.IDENTITY, identity)

    def update_dynamics(
        self, key: RelationshipKey, dynamics: RelationshipDynamics
    ) -> RelationshipModel:
        return self._record(key, RelationshipUpdateKind.DYNAMICS, dynamics)

    def evidence_roots(
        self, key: RelationshipKey, ref: str, seen: set[str] | None = None
    ) -> set[str]:
        visited = set(seen or ())
        if ref in visited:
            return visited
        visited.add(ref)
        evidence = RelationshipEvidenceRef.parse(ref)
        if evidence.kind is RelationshipEvidenceKind.EXPERIENCE:
            visited.update(self.experiences.roots(self.experiences.get(key, evidence.id)))
            return visited
        children: list[str] = []
        if evidence.kind is RelationshipEvidenceKind.USER_CORRECTION:
            children = [f"turn:{evidence.id}"]
        elif evidence.kind in {
            RelationshipEvidenceKind.MEMORY,
            RelationshipEvidenceKind.RELATIONSHIP_MEMORY,
        }:
            memory = self.memory.store.get(evidence.id, key.user_id)
            children = [f"turn:{identifier}" for identifier in memory.evidence_turn_ids]
            if evidence.kind is RelationshipEvidenceKind.RELATIONSHIP_MEMORY:
                children.append(f"memory:{evidence.id}")
        elif evidence.kind is RelationshipEvidenceKind.OPEN_LOOP:
            loop = self.memory.store.get_open_loop(evidence.id, key.user_id)
            children = [f"turn:{loop.source_turn_id}"] if loop.source_turn_id else []
            if isinstance(loop.metadata.get("last_update_source_turn_id"), str):
                children.append(f"turn:{loop.metadata['last_update_source_turn_id']}")
        elif evidence.kind is RelationshipEvidenceKind.MILESTONE:
            model = self.store.get(key)
            milestone = (
                next((m for m in model.milestones if m.id == evidence.id), None) if model else None
            )
            children = milestone.evidence_ids if milestone else []
        for child in children:
            visited.update(self.evidence_roots(key, child, visited))
        return visited

    def get_relationship_context(
        self,
        key: RelationshipKey,
        response_goal: ResponseGoal,
        current_user_turn: str,
        *,
        model: RelationshipModel | None = None,
        memory_use_plan: MemoryUsePlan | None = None,
        allow_sensitive: bool = False,
        as_of: datetime | None = None,
        dynamics_only: bool = False,
    ) -> CompiledRelationshipContext:
        from companion_agent.evidence_policy import restricted_evidence
        from companion_agent.relationship.compiler import compile_relationship_context

        at = as_of or now_utc()
        current = model if model is not None else self.evaluate_stage(key, as_of=at)
        if current.key != key:
            raise ValueError("relationship context has a different owner")
        all_refs = _all_evidence(current)
        refs = set(current.recent_dynamics.evidence_ids) if dynamics_only else all_refs
        roots = {ref: self.evidence_roots(key, ref) for ref in refs}
        all_roots = set().union(*roots.values()) if roots else set()
        feedback_refs = []
        for root in all_roots:
            reference = RelationshipEvidenceRef.parse(root)
            if reference.kind.value in {kind.value for kind in ExperienceEvidenceKind}:
                feedback_refs.append(
                    ExperienceEvidenceRef(
                        kind=ExperienceEvidenceKind(reference.kind.value), id=reference.id
                    )
                )
        # Historical/event time must not hide restrictions just applied during
        # this request (for example forgetting its source). Revalidate against
        # current policy before generation, as response persistence already does.
        blocked = restricted_evidence(self.memory, key, feedback_refs, max(at, now_utc()))
        modes: dict[str, MemoryReferenceMode] = {}
        for decision in (memory_use_plan or MemoryUsePlan()).decisions:
            ref = f"{decision.evidence.kind.value}:{decision.evidence.id}"
            modes[ref] = decision.mode
            if decision.mode is MemoryReferenceMode.SUPPRESS:
                blocked.add(ref)
        excluded = {
            ref
            for ref in refs
            if blocked.intersection(roots[ref])
            or not self.evidence_valid(key, ref, at, allow_sensitive=allow_sensitive)
        }
        excluded.update(all_refs - refs)
        for ref in refs:
            inherited = {modes[root] for root in roots[ref] if root in modes}
            for restrictive in (
                MemoryReferenceMode.SUPPRESS,
                MemoryReferenceMode.CLARIFY,
                MemoryReferenceMode.SILENT_INFLUENCE,
                MemoryReferenceMode.SOFT_REFERENCE,
                MemoryReferenceMode.EXPLICIT_RECALL,
            ):
                if restrictive in inherited:
                    modes[ref] = restrictive
                    break
        context_model = current.model_copy(deep=True)
        if excluded.intersection(current.recent_dynamics.evidence_ids):
            context_model.recent_dynamics = RelationshipDynamics(
                updated_at=current.recent_dynamics.updated_at
            )
        if excluded.intersection(current.distance_evidence_ids):
            context_model.distance_ceiling = None
        return compile_relationship_context(
            context_model,
            response_goal,
            current_user_turn,
            config=self.config,
            as_of=at,
            max_relationship_tokens=self.config.max_relationship_tokens,
            token_counter=self.memory.token_counter,
            excluded_evidence_ids=excluded,
            evidence_modes=modes,
        )

    def get_history(self, key: RelationshipKey) -> list[RelationshipRevision]:
        at = now_utc()
        history = self.store.history(key)
        for revision in history:
            # Old snapshots may contain facts whose source was subsequently forgotten.
            refs = set(revision.evidence_ids)
            for snapshot in (revision.before, revision.after):
                if snapshot:
                    refs.update(_all_evidence(RelationshipModel.model_validate(snapshot)))
            if any(not self.evidence_valid(key, ref, at) for ref in refs):
                revision.before = revision.after = None
                revision.summary = "此历史版本包含已失效证据，内容已隐藏"
        return history

    def delete_relationship(self, key: RelationshipKey) -> None:
        self.store.delete(key)

    def get_candidates(
        self, key: RelationshipKey
    ) -> list[tuple[RelationshipUpdateCandidate, RelationshipDecision | None]]:
        candidates = self.store.candidates(key)
        for candidate, _ in candidates:
            if any(not self.evidence_valid(key, ref, now_utc()) for ref in candidate.evidence_ids):
                candidate.description = "候选证据已失效，内容已隐藏"
                candidate.proposed_change = {}
        return candidates

    def get_summary(self, key: RelationshipKey) -> str:
        model = self.get_relationship(key)
        labels = (
            "、".join(model.identity.labels)
            if model.identity.confirmed_by_user
            else "尚未明确确认关系定义"
        )
        patterns = [
            item.description
            for item in model.patterns
            if item.status is RelationshipPatternStatus.ESTABLISHED
        ]
        threads = [
            item.topic
            for item in model.unresolved_threads
            if item.status is RelationshipThreadStatus.OPEN
        ]
        return "\n".join(
            [
                f"当前阶段：{model.stage.value}；{labels}。",
                "阶段依据：" + "；".join(model.stage_state.reasons),
                "已形成模式：" + ("；".join(patterns) or "暂无"),
                "未解决事项：" + ("；".join(threads) or "暂无"),
                f"结构化版本：{model.revision}；摘要仅为视图，不作为证据。",
            ]
        )

    def remove_item(
        self, key: RelationshipKey, collection: str, item_id: str, evidence_ids: list[str]
    ) -> RelationshipModel:
        if collection not in {"patterns", "milestones", "unresolved_threads", "boundaries"}:
            raise ValueError("unknown relationship collection")
        with self.store.database.atomic():
            model = self.get_relationship(key)
            for evidence in evidence_ids:
                self._evidence_time(key, evidence, now_utc())
            if not evidence_ids:
                raise ValueError("item removal requires evidence")
            updated = model.model_copy(deep=True)
            setattr(
                updated,
                collection,
                [item for item in getattr(model, collection) if item.id != item_id],
            )
            if updated == model:
                return model
            return self.store.save(
                model,
                updated,
                RelationshipChangeType.ITEM_REMOVED,
                f"移除关系项目 {collection}/{item_id}",
                evidence_ids,
                now_utc(),
            )


def _all_evidence(model: RelationshipModel) -> set[str]:
    refs = (
        set(model.interactions)
        | set(model.identity.evidence_ids)
        | set(model.stage_state.evidence_ids)
    )
    refs.update(model.shared_experiences)
    refs.update(
        model.started_at_evidence_ids
        + model.distance_evidence_ids
        + model.recent_dynamics.evidence_ids
    )
    for collection in (
        model.patterns,
        model.milestones,
        model.unresolved_threads,
        model.boundaries,
    ):
        for item in collection:
            refs.update(item.evidence_ids)
    return refs
