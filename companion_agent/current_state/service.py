"""Persist user overlays once, with semantic expiry and evidence-aware effective reads."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from companion_agent.current_state.evaluator import analyze_current_turn
from companion_agent.current_state.models import (
    CurrentStateAnalysis,
    CurrentStateConfig,
    CurrentStateRecord,
    StateKind,
    StateObservation,
    StatePreparation,
    StateStatus,
)
from companion_agent.evidence_policy import restricted_evidence
from companion_agent.relationship import RelationshipKey, RelationshipService
from companion_agent.relationship.evaluator import interaction_candidates
from companion_agent.relationship.models import RelationshipUpdateKind, now_utc
from companion_agent.relationship.service import candidate_for
from companion_memoryos.schemas import (
    ExperienceEvidenceKind,
    ExperienceEvidenceRef,
    MemoryReferenceMode,
    MemoryUsePlan,
    OpenLoopStatus,
    OpenLoopTransition,
    OpenLoopUpdateRequest,
    ProcessTurnRequest,
    ProcessTurnResult,
    ResponseGoal,
)
from companion_memoryos.service import CompanionMemoryService

DOMAIN = "user_id=? AND companion_id=? AND relationship_id=?"


class CurrentStateService:
    def __init__(
        self,
        memory: CompanionMemoryService,
        relationships: RelationshipService,
        config: CurrentStateConfig | None = None,
        *,
        clock: Callable[[], datetime] = now_utc,
    ) -> None:
        self.memory = memory
        self.relationships = relationships
        self.config = config or CurrentStateConfig()
        self.clock = clock
        with memory.store.database.atomic() as connection:
            row = connection.execute(
                "SELECT version FROM agent_schema_versions WHERE component='current_state'"
            ).fetchone()
            if row and row["version"] > 1:
                raise ValueError("current state schema is newer than this runtime")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS agent_current_states ("
                "user_id TEXT NOT NULL, companion_id TEXT NOT NULL, relationship_id TEXT NOT NULL, "
                "conversation_id TEXT NOT NULL, slot TEXT NOT NULL, data_json TEXT NOT NULL, "
                "PRIMARY KEY(user_id,companion_id,relationship_id,conversation_id,slot))"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS agent_current_state_receipts ("
                "user_id TEXT NOT NULL, companion_id TEXT NOT NULL, relationship_id TEXT NOT NULL, "
                "turn_id TEXT NOT NULL, PRIMARY KEY(user_id,companion_id,relationship_id,turn_id))"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS agent_current_state_events ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, "
                "companion_id TEXT NOT NULL, relationship_id TEXT NOT NULL, "
                "state_id TEXT NOT NULL, "
                "revision INTEGER NOT NULL, data_json TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_current_state_events_scope ON "
                "agent_current_state_events(user_id,companion_id,relationship_id,id)"
            )
            connection.execute(
                "INSERT OR IGNORE INTO agent_schema_versions VALUES ('current_state',1)"
            )

    def _raw(self, key: RelationshipKey, conversation_id: str) -> list[CurrentStateRecord]:
        with self.memory.store.database.connection() as connection:
            rows = connection.execute(
                f"SELECT data_json FROM agent_current_states WHERE {DOMAIN} "
                "AND conversation_id IN ('', ?)",
                (*key.values, conversation_id),
            ).fetchall()
        records = [CurrentStateRecord.model_validate_json(row["data_json"]) for row in rows]
        if any(
            (record.user_id, record.companion_id, record.relationship_id) != key.values
            for record in records
        ):
            raise ValueError("current state payload has a different owner")
        # Choose the latest statement before filtering. Expiry/deletion of an override
        # must not resurrect an older, contradicted request from another scope.
        latest: dict[str, CurrentStateRecord] = {}
        for record in sorted(records, key=lambda r: (r.observed_at, r.source_sequence)):
            latest[record.slot] = record
        return list(latest.values())

    def snapshot(
        self,
        key: RelationshipKey,
        conversation_id: str,
        *,
        as_of: datetime | None = None,
        memory_use_plan: MemoryUsePlan | None = None,
        allow_sensitive: bool = False,
        include_inactive: bool = False,
    ) -> list[CurrentStateRecord]:
        at = as_of or self.clock()
        records = self._raw(key, conversation_id)
        refs = [
            ExperienceEvidenceRef(kind=ExperienceEvidenceKind.TURN, id=record.source_turn_id)
            for record in records
        ]
        blocked = {
            ref.split(":", 1)[1]
            for ref in restricted_evidence(
                self.memory, key, refs, at, conversation_id=conversation_id
            )
        }
        blocked.update(
            d.evidence.id
            for d in (memory_use_plan or MemoryUsePlan()).decisions
            if d.evidence.kind is ExperienceEvidenceKind.TURN
            and d.mode in {MemoryReferenceMode.SUPPRESS, MemoryReferenceMode.CLARIFY}
        )
        selected = []
        for stored in records:
            record = stored.model_copy(deep=True)
            if record.observed_at > at:
                continue
            if not self.relationships.evidence_valid(
                key, f"turn:{record.source_turn_id}", at, allow_sensitive=allow_sensitive
            ):
                record.status, record.reason = StateStatus.INVALIDATED, "source_unavailable"
            elif record.source_turn_id in blocked:
                record.status, record.reason = StateStatus.SUPPRESSED, "source_use_restricted"
            elif record.status is StateStatus.ACTIVE and record.expires_at <= at:
                record.status, record.reason = StateStatus.EXPIRED, "expired_is_not_recovery"
            elif record.status is StateStatus.ACTIVE and record.open_loop_id:
                try:
                    loop = self.memory.store.get_open_loop(record.open_loop_id, key.user_id)
                    if loop.status is OpenLoopStatus.RESOLVED:
                        record.status, record.reason = (
                            StateStatus.ENDED,
                            "linked_open_loop_resolved",
                        )
                except KeyError:
                    record.status, record.reason = (
                        StateStatus.INVALIDATED,
                        "linked_source_unavailable",
                    )
            if include_inactive or record.status is StateStatus.ACTIVE:
                selected.append(record)
        return selected

    def _record(
        self, request: ProcessTurnRequest, result: ProcessTurnResult, observation: StateObservation
    ) -> CurrentStateRecord:
        turn = result.storage.turn
        assert turn is not None
        key = RelationshipKey(
            user_id=turn.user_id,
            companion_id=turn.scope.companion_id or "",
            relationship_id=turn.scope.relationship_id or "",
        )
        shared = observation.kind is StateKind.CONDITION or observation.applies_today
        conversation = None if shared else turn.scope.conversation_id
        hours = self.config.communication_hours
        if observation.kind is StateKind.CONDITION:
            hours = (
                self.config.fatigue_hours
                if observation.value in {"fatigue", "sleep_loss"}
                else (
                    self.config.pressure_hours
                    if observation.value == "pressure"
                    else self.config.emotion_hours
                )
            )
        expires = turn.occurred_at + timedelta(hours=hours)
        if observation.applies_today:
            local = turn.occurred_at.astimezone(ZoneInfo(request.calendar_timezone))
            expires = (
                (local + timedelta(days=1))
                .replace(hour=0, minute=0, second=0, microsecond=0)
                .astimezone(UTC)
            )
        slot = f"{observation.kind.value}:{observation.slot}"
        old = next(
            (r for r in self._raw(key, turn.scope.conversation_id or "") if r.slot == slot), None
        )
        loops = [
            loop
            for loop in self.memory.list_open_loops(key.user_id)
            if observation.topic
            and observation.topic in " ".join([*loop.topic_keys, loop.summary])
            and loop.scope.companion_id == key.companion_id
            and loop.scope.relationship_id == key.relationship_id
            and loop.status
            in {OpenLoopStatus.OPEN, OpenLoopStatus.WAITING_FOR_REPLY, OpenLoopStatus.SNOOZED}
            and self.relationships.evidence_valid(key, f"open_loop:{loop.id}", self.clock())
        ]
        return CurrentStateRecord(
            **key.model_dump(),
            state_id=hashlib.sha256(
                "\0".join([*key.values, conversation or "", slot]).encode()
            ).hexdigest(),
            kind=observation.kind,
            slot=slot,
            value=observation.value,
            topic=observation.topic,
            conversation_id=conversation,
            actor_id=turn.user_id,
            source_turn_id=turn.id,
            source_sequence=turn.server_sequence,
            observed_at=turn.occurred_at,
            expires_at=expires,
            status=observation.status,
            reason=observation.reason,
            revision=(old.revision + 1 if old else 1),
            open_loop_id=loops[0].id
            if len(loops) == 1 and observation.kind is StateKind.CONDITION
            else None,
        )

    def process(self, request: ProcessTurnRequest, result: ProcessTurnResult) -> StatePreparation:
        turn = result.storage.turn
        if turn is None:
            return StatePreparation(analysis=CurrentStateAnalysis())
        key = RelationshipKey(
            user_id=turn.user_id,
            companion_id=turn.scope.companion_id or "",
            relationship_id=turn.scope.relationship_id or "",
        )
        if not self.relationships.evidence_valid(key, f"turn:{turn.id}", self.clock()):
            return StatePreparation(analysis=CurrentStateAnalysis())
        text = self.memory._direct_user_discourse_text(turn)
        analysis = analyze_current_turn(text, result)
        with self.memory.store.database.atomic() as connection:
            prior = connection.execute(
                f"SELECT 1 FROM agent_current_state_receipts WHERE {DOMAIN} AND turn_id=?",
                (*key.values, turn.id),
            ).fetchone()
            if not prior:
                current = self._raw(key, turn.scope.conversation_id or "")
                observations = list(analysis.observations)
                fresh = {
                    f"{obs.kind.value}:{obs.slot}"
                    for obs in observations
                    if obs.status is StateStatus.ACTIVE
                }
                for record in current:
                    if (
                        record.kind is StateKind.CONDITION
                        and record.topic in analysis.completed_topics
                        and record.slot not in fresh
                    ):
                        observations.append(
                            StateObservation(
                                kind=record.kind,
                                slot=record.slot.split(":", 1)[1],
                                value=record.value,
                                topic=record.topic,
                                status=StateStatus.ENDED,
                                reason="explicit_topic_outcome",
                            )
                        )
                # Resolve an implicit pause target only when existing current evidence is unique.
                active = self.snapshot(key, turn.scope.conversation_id or "")
                topics = {r.topic for r in active if r.kind is StateKind.CONDITION and r.topic}
                for observation in observations:
                    if observation.slot == "reference" and len(topics) == 1:
                        observation.topic = next(iter(topics))
                        observation.slot = f"reference:{observation.topic}"
                holds = [r for r in active if r.slot.startswith("style:reference")]
                for record in holds:
                    if record.topic in analysis.reopened_topics or (
                        analysis.reopen_unscoped and len(holds) == 1
                    ):
                        observations.append(
                            StateObservation(
                                kind=StateKind.STYLE,
                                slot=record.slot.split(":", 1)[1],
                                value="normal",
                                topic=record.topic,
                                status=StateStatus.ENDED,
                                reason="user_reopened_topic",
                            )
                        )
                if (
                    analysis.topic_switch or analysis.concrete_task
                ) and analysis.explicit_goal is None:
                    observations.append(
                        StateObservation(
                            kind=StateKind.COMMUNICATION,
                            slot="need",
                            value="none",
                            status=StateStatus.ENDED,
                            reason="current_task_or_scene_changed",
                        )
                    )
                for observation in observations:
                    record = self._record(request, result, observation)
                    previous = next(
                        (
                            r
                            for r in self._raw(key, turn.scope.conversation_id or "")
                            if r.slot == record.slot
                        ),
                        None,
                    )
                    if previous and (previous.observed_at, previous.source_sequence) > (
                        record.observed_at,
                        record.source_sequence,
                    ):
                        continue
                    if not request.apply_low_risk_actions:
                        continue
                    connection.execute(
                        "INSERT INTO agent_current_states VALUES(?,?,?,?,?,?) "
                        "ON CONFLICT(user_id,companion_id,relationship_id,conversation_id,slot) "
                        "DO UPDATE SET data_json=excluded.data_json",
                        (
                            *key.values,
                            record.conversation_id or "",
                            record.slot,
                            record.model_dump_json(),
                        ),
                    )
                    connection.execute(
                        "INSERT INTO agent_current_state_events"
                        "(user_id,companion_id,relationship_id,state_id,revision,data_json) "
                        "VALUES(?,?,?,?,?,?)",
                        (*key.values, record.state_id, record.revision, record.model_dump_json()),
                    )
                if request.apply_low_risk_actions:
                    self._update_existing_truth(key, analysis, turn.id, turn.occurred_at)
                    connection.execute(
                        "INSERT INTO agent_current_state_receipts VALUES(?,?,?,?)",
                        (*key.values, turn.id),
                    )
        return self.refresh(
            key,
            turn.scope.conversation_id or "",
            StatePreparation(analysis=analysis),
            allow_sensitive=request.allow_sensitive_model_input,
        )

    def refresh(
        self,
        key: RelationshipKey,
        conversation_id: str,
        preparation: StatePreparation,
        *,
        memory_use_plan: MemoryUsePlan | None = None,
        allow_sensitive: bool = False,
    ) -> StatePreparation:
        output = preparation.model_copy(deep=True)
        output.records = self.snapshot(
            key, conversation_id, memory_use_plan=memory_use_plan, allow_sensitive=allow_sensitive
        )
        model = self.relationships.get_relationship(key)
        # This is a projection of the existing relationship truth, not another conflict record.
        if model.recent_dynamics.active_topics != ["本轮倾诉"]:
            context = self.relationships.get_relationship_context(
                key,
                ResponseGoal.LISTEN,
                "",
                model=model,
                memory_use_plan=memory_use_plan,
                allow_sensitive=allow_sensitive,
                as_of=self.clock(),
            )
            output.interaction_guidance = context.recent_dynamic_summary
            output.interaction_tone = (
                model.recent_dynamics.interaction_tone.value
                if context.recent_dynamic_summary
                else None
            )
        return output

    def _update_existing_truth(
        self,
        key: RelationshipKey,
        analysis: CurrentStateAnalysis,
        turn_id: str,
        observed_at: datetime,
    ) -> None:
        ref = [f"turn:{turn_id}"]
        model = self.relationships.get_relationship(key)
        if analysis.repair_requires_context:
            context = self.relationships.get_relationship_context(
                key, ResponseGoal.REFLECT, "关系", model=model, as_of=self.clock()
            )
            if not (context.recent_dynamic_summary or context.unresolved_threads):
                analysis.repair = False
        proposals = interaction_candidates(analysis, model, turn_id, observed_at)
        if analysis.permanent_address_boundary:
            proposals.append(
                candidate_for(
                    RelationshipUpdateKind.BOUNDARY,
                    "用户明确设置长期称呼边界",
                    ref,
                    {
                        "id": "rejected-address",
                        "description": "不再使用用户明确拒绝的称呼；这条边界不随临时状态过期"
                        + (
                            f"；用户原话：{analysis.rejected_address_text}"
                            if analysis.rejected_address_text
                            else ""
                        ),
                    },
                    observed_at,
                )
            )
        if proposals:
            self.relationships.commit_candidates(key, proposals)
        # The OpenLoop remains the source of truth. Resolve only an explicit, unique topic match.
        for topic in analysis.completed_topics:
            loops = [
                loop
                for loop in self.memory.list_open_loops(key.user_id)
                if topic in " ".join([loop.summary, *loop.topic_keys])
                and loop.scope.companion_id == key.companion_id
                and loop.scope.relationship_id == key.relationship_id
                and loop.status
                in {OpenLoopStatus.OPEN, OpenLoopStatus.WAITING_FOR_REPLY, OpenLoopStatus.SNOOZED}
                and loop.updated_at <= observed_at
                and self.relationships.evidence_valid(key, f"open_loop:{loop.id}", self.clock())
            ]
            if len(loops) == 1:
                self.memory.update_open_loop(
                    loops[0].id,
                    OpenLoopUpdateRequest(
                        user_id=key.user_id,
                        transition=OpenLoopTransition.RESOLVE,
                        source_turn_id=turn_id,
                        resolution_summary="用户明确报告该事项已结束",
                        expected_revision=loops[0].revision,
                    ),
                )


def choose_response_goal(
    base: ResponseGoal, preparation: StatePreparation, *, host_goal: ResponseGoal | None = None
) -> ResponseGoal:
    analysis = preparation.analysis
    if analysis.explicit_goal is not None:
        return analysis.explicit_goal
    if host_goal is not None:
        return host_goal
    if analysis.concrete_task:
        return (
            base
            if base in {ResponseGoal.DIRECT_ANSWER, ResponseGoal.PROBLEM_SOLVE}
            else ResponseGoal.DIRECT_ANSWER
        )
    need = next(
        (
            record
            for record in preparation.records
            if record.slot == "communication:need" and record.status is StateStatus.ACTIVE
        ),
        None,
    )
    if need:
        return ResponseGoal(need.value)
    if preparation.interaction_tone in {"tense", "slightly_tense"}:
        return ResponseGoal.LISTEN
    return base
