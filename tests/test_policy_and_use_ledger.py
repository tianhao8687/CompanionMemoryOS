from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from companion_memoryos.schemas import (
    ConsentState,
    ConversationRole,
    ConversationTurnInput,
    MemoryInput,
    MemoryKind,
    MemoryScope,
    MemoryUseInput,
    PolicyConstraintInput,
    PolicyConstraintStatus,
    PolicyEffect,
    PolicyGateRequest,
    ProactivityRequest,
    RealityLayer,
    RecallRequest,
    RecallUseMode,
    SpeechAct,
    SpeechSpan,
)
from companion_memoryos.service import CompanionMemoryService

SCOPE = MemoryScope(companion_id="companion", relationship_id="relationship")


def test_latest_applicable_policy_controls_outbound_action(
    service: CompanionMemoryService,
) -> None:
    deny = service.create_policy_constraint(
        PolicyConstraintInput(
            user_id="alice",
            action="use_pet_name",
            effect=PolicyEffect.DENY,
            reason_code="user_boundary",
        )
    )
    blocked = service.evaluate_policy(
        PolicyGateRequest(user_id="alice", scope=SCOPE, actions=["use_pet_name"])
    )
    allow = service.create_policy_constraint(
        PolicyConstraintInput(
            user_id="alice",
            scope=SCOPE,
            action="use_pet_name",
            effect=PolicyEffect.ALLOW,
            reason_code="user_restored_for_relationship",
        )
    )
    restored = service.evaluate_policy(
        PolicyGateRequest(user_id="alice", scope=SCOPE, actions=["use_pet_name"])
    )
    assert blocked.allowed is False
    assert blocked.policy_version == deny.version
    assert restored.allowed is True
    assert restored.policy_version == allow.version


def test_new_global_deny_overrides_stale_specific_allow(
    service: CompanionMemoryService,
) -> None:
    service.create_policy_constraint(
        PolicyConstraintInput(
            user_id="alice",
            scope=SCOPE,
            action="use_pet_name",
            effect=PolicyEffect.ALLOW,
            reason_code="old_allow",
        )
    )
    service.create_policy_constraint(
        PolicyConstraintInput(
            user_id="alice",
            action="use_pet_name",
            effect=PolicyEffect.DENY,
            reason_code="new_global_boundary",
        )
    )
    decision = service.evaluate_policy(
        PolicyGateRequest(user_id="alice", scope=SCOPE, actions=["use_pet_name"])
    )
    assert decision.allowed is False


def test_future_policy_does_not_open_a_gap_before_it_becomes_valid(
    service: CompanionMemoryService,
) -> None:
    now = datetime.now(UTC)
    future = now + timedelta(days=1)
    deny = service.create_policy_constraint(
        PolicyConstraintInput(
            user_id="alice",
            scope=SCOPE,
            action="proactive_contact",
            effect=PolicyEffect.DENY,
            reason_code="current_boundary",
            valid_from=now - timedelta(days=1),
        )
    )
    allow = service.create_policy_constraint(
        PolicyConstraintInput(
            user_id="alice",
            scope=SCOPE,
            action="proactive_contact",
            effect=PolicyEffect.ALLOW,
            reason_code="scheduled_restore",
            valid_from=future,
        )
    )

    before = service.evaluate_policy(
        PolicyGateRequest(
            user_id="alice",
            scope=SCOPE,
            actions=["proactive_contact"],
            as_of=now,
        )
    )
    after = service.evaluate_policy(
        PolicyGateRequest(
            user_id="alice",
            scope=SCOPE,
            actions=["proactive_contact"],
            as_of=future + timedelta(minutes=1),
        )
    )

    assert before.allowed is False
    assert before.applied_constraints[0].id == deny.id
    assert after.allowed is True
    assert after.applied_constraints[0].id == allow.id


def test_outbound_task_with_old_policy_version_is_rejected(
    service: CompanionMemoryService,
) -> None:
    initial = service.evaluate_policy(
        PolicyGateRequest(user_id="alice", scope=SCOPE, actions=["send_message"])
    )
    service.create_policy_constraint(
        PolicyConstraintInput(
            user_id="alice",
            scope=SCOPE,
            action="use_pet_name",
            effect=PolicyEffect.DENY,
            reason_code="new_boundary",
        )
    )

    stale = service.evaluate_policy(
        PolicyGateRequest(
            user_id="alice",
            scope=SCOPE,
            actions=["send_message"],
            task_policy_version=initial.policy_version,
        )
    )

    assert stale.allowed is False
    assert stale.blocked_actions == ["send_message"]
    assert "stale_policy_version" in stale.reasons


def test_policy_can_be_revoked_and_purged_without_reusing_its_version(
    service: CompanionMemoryService,
) -> None:
    constraint = service.create_policy_constraint(
        PolicyConstraintInput(
            user_id="alice",
            scope=SCOPE,
            action="use_pet_name",
            effect=PolicyEffect.DENY,
            reason_code="user_boundary",
        )
    )
    revoked = service.revoke_policy_constraint(constraint.id, "alice")
    after_revoke = service.store.current_policy_version("alice")
    stale = service.evaluate_policy(
        PolicyGateRequest(
            user_id="alice",
            scope=SCOPE,
            actions=["send_message"],
            task_policy_version=constraint.version,
        )
    )

    assert revoked.status is PolicyConstraintStatus.REVOKED
    assert after_revoke > constraint.version
    assert stale.allowed is False

    service.purge_policy_constraint(constraint.id, "alice")
    assert service.list_policy_constraints("alice") == []
    with service.store.database.connection() as connection:
        audit_rows = connection.execute(
            "SELECT event_type, payload_json FROM audit_events WHERE memory_id = ?",
            (constraint.id,),
        ).fetchall()
    assert [row["event_type"] for row in audit_rows] == ["policy_constraint.purged"]
    assert "use_pet_name" not in audit_rows[0]["payload_json"]

    replacement = service.create_policy_constraint(
        PolicyConstraintInput(
            user_id="alice",
            scope=SCOPE,
            action="use_pet_name",
            effect=PolicyEffect.ALLOW,
            reason_code="user_changed_mind",
        )
    )
    assert replacement.version > after_revoke


def test_proactivity_is_blocked_by_policy_gate(service: CompanionMemoryService) -> None:
    service.create_policy_constraint(
        PolicyConstraintInput(
            user_id="alice",
            scope=SCOPE,
            action="proactive_contact",
            effect=PolicyEffect.FREEZE,
            reason_code="do_not_contact",
        )
    )
    now = datetime.now(UTC)
    decision = service.proactivity(
        ProactivityRequest(
            user_id="alice",
            scope=SCOPE,
            permission_granted=True,
            last_user_message_at=now - timedelta(days=1),
            has_relevant_reason=True,
            as_of=now,
        )
    )
    assert decision.should_reach_out is False
    assert "policy_gate_denied" in decision.reasons


def test_turn_deletion_revokes_then_purges_derived_policy_without_reusing_version(
    service: CompanionMemoryService,
) -> None:
    turn_scope = SCOPE.model_copy(update={"conversation_id": "conversation"})
    turn = service.append_turn(
        ConversationTurnInput(
            user_id="alice",
            scope=turn_scope,
            actor_id="alice",
            role=ConversationRole.USER,
            content="今晚别联系我",
            consent=ConsentState.GRANTED,
        )
    ).turn
    assert turn is not None
    constraint = service.create_policy_constraint(
        PolicyConstraintInput(
            user_id="alice",
            scope=SCOPE,
            action="proactive_contact",
            effect=PolicyEffect.DENY,
            reason_code="user_boundary",
            source_turn_id=turn.id,
            source_direct_user_instruction=True,
        )
    )

    with pytest.raises(ValueError, match="explicit user decision"):
        service.forget_turn(turn.id, "alice")
    service.forget_turn(turn.id, "alice", revoke_source_policies=True)
    after_forget = service.store.current_policy_version("alice")
    stored_constraint = next(
        item for item in service.list_policy_constraints("alice") if item.id == constraint.id
    )
    stale = service.evaluate_policy(
        PolicyGateRequest(
            user_id="alice",
            scope=SCOPE,
            actions=["send_message"],
            task_policy_version=constraint.version,
        )
    )

    assert stored_constraint.status is PolicyConstraintStatus.REVOKED
    assert after_forget > constraint.version
    assert stale.allowed is False
    assert "stale_policy_version" in stale.reasons

    service.purge_turn(turn.id, "alice")
    assert all(item.id != constraint.id for item in service.list_policy_constraints("alice"))
    with service.store.database.connection() as connection:
        audit_rows = connection.execute(
            "SELECT event_type, payload_json FROM audit_events WHERE memory_id = ?",
            (constraint.id,),
        ).fetchall()
    assert [row["event_type"] for row in audit_rows] == ["policy_constraint.source_purged"]
    assert "proactive_contact" not in audit_rows[0]["payload_json"]
    next_constraint = service.create_policy_constraint(
        PolicyConstraintInput(
            user_id="alice",
            action="use_pet_name",
            effect=PolicyEffect.DENY,
            reason_code="new_boundary",
        )
    )
    assert next_constraint.version > after_forget


def test_policy_source_turn_cannot_be_reassigned_to_another_relationship(
    service: CompanionMemoryService,
) -> None:
    source_scope = SCOPE.model_copy(update={"conversation_id": "conversation"})
    turn = service.append_turn(
        ConversationTurnInput(
            user_id="alice",
            scope=source_scope,
            actor_id="alice",
            role=ConversationRole.USER,
            content="不要叫我宝宝",
            consent=ConsentState.GRANTED,
        )
    ).turn
    assert turn is not None

    with pytest.raises(ValueError, match="non-global"):
        service.create_policy_constraint(
            PolicyConstraintInput(
                user_id="alice",
                action="use_pet_name",
                effect=PolicyEffect.DENY,
                reason_code="unsafe_scope_escalation",
                source_turn_id=turn.id,
                source_direct_user_instruction=True,
            )
        )

    with pytest.raises(ValueError, match="policy scope"):
        service.create_policy_constraint(
            PolicyConstraintInput(
                user_id="alice",
                scope=MemoryScope(relationship_id="another-relationship"),
                action="use_pet_name",
                effect=PolicyEffect.DENY,
                reason_code="wrong_scope",
                source_turn_id=turn.id,
                source_direct_user_instruction=True,
            )
        )


def test_source_backed_policy_requires_direct_user_attestation_and_user_turn(
    service: CompanionMemoryService,
) -> None:
    turn_scope = SCOPE.model_copy(update={"conversation_id": "conversation"})
    user_turn = service.append_turn(
        ConversationTurnInput(
            user_id="alice",
            scope=turn_scope,
            actor_id="alice",
            role=ConversationRole.USER,
            content="不要叫我宝宝",
            consent=ConsentState.GRANTED,
        )
    ).turn
    third_party_turn = service.append_turn(
        ConversationTurnInput(
            user_id="alice",
            scope=turn_scope,
            actor_id="friend",
            role=ConversationRole.THIRD_PARTY,
            content="她说不要叫她宝宝",
            consent=ConsentState.GRANTED,
        )
    ).turn
    assert user_turn is not None
    assert third_party_turn is not None

    with pytest.raises(ValueError, match="direct-user attestation"):
        PolicyConstraintInput(
            user_id="alice",
            scope=SCOPE,
            action="use_pet_name",
            effect=PolicyEffect.DENY,
            reason_code="missing_attestation",
            source_turn_id=user_turn.id,
        )

    with pytest.raises(ValueError, match="user-authored"):
        service.create_policy_constraint(
            PolicyConstraintInput(
                user_id="alice",
                scope=SCOPE,
                action="use_pet_name",
                effect=PolicyEffect.DENY,
                reason_code="third_party_quote",
                source_turn_id=third_party_turn.id,
                source_direct_user_instruction=True,
            )
        )


def test_quoted_user_turn_cannot_be_attested_into_a_boundary(
    service: CompanionMemoryService,
) -> None:
    turn_scope = SCOPE.model_copy(update={"conversation_id": "conversation"})
    content = "对方说：以后别联系我"
    quoted = "以后别联系我"
    start = content.index(quoted)
    turn = service.append_turn(
        ConversationTurnInput(
            user_id="alice",
            scope=turn_scope,
            actor_id="alice",
            role=ConversationRole.USER,
            content=content,
            consent=ConsentState.GRANTED,
            speech_spans=[
                SpeechSpan(
                    start_offset=start,
                    end_offset=start + len(quoted),
                    quote_depth=1,
                    attributed_speaker_id="other-person",
                    target_actor_id="alice",
                    reality_layer=RealityLayer.QUOTE,
                    speech_act=SpeechAct.QUOTE,
                    model_fingerprint="discourse:test",
                )
            ],
        )
    ).turn
    assert turn is not None

    with pytest.raises(ValueError, match="quoted or fictional"):
        service.create_policy_constraint(
            PolicyConstraintInput(
                user_id="alice",
                scope=SCOPE,
                action="proactive_contact",
                effect=PolicyEffect.DENY,
                reason_code="quoted_boundary",
                source_turn_id=turn.id,
                source_direct_user_instruction=True,
            )
        )


def test_mixed_speaker_turn_requires_claim_level_anchor_before_policy_promotion(
    service: CompanionMemoryService,
) -> None:
    turn_scope = SCOPE.model_copy(update={"conversation_id": "conversation"})
    content = "对方说别联系她，但我没有这个要求"
    quoted = "别联系她"
    direct = "但我没有这个要求"
    turn = service.append_turn(
        ConversationTurnInput(
            user_id="alice",
            scope=turn_scope,
            actor_id="alice",
            role=ConversationRole.USER,
            content=content,
            consent=ConsentState.GRANTED,
            speech_spans=[
                SpeechSpan(
                    start_offset=content.index(quoted),
                    end_offset=content.index(quoted) + len(quoted),
                    quote_depth=1,
                    attributed_speaker_id="other-person",
                    target_actor_id="alice",
                    reality_layer=RealityLayer.QUOTE,
                    speech_act=SpeechAct.QUOTE,
                    model_fingerprint="discourse:test",
                ),
                SpeechSpan(
                    start_offset=content.index(direct),
                    end_offset=content.index(direct) + len(direct),
                    attributed_speaker_id="alice",
                    speech_act=SpeechAct.ASSERTION,
                    model_fingerprint="discourse:test",
                ),
            ],
        )
    ).turn
    assert turn is not None

    with pytest.raises(ValueError, match="quoted or fictional"):
        service.create_policy_constraint(
            PolicyConstraintInput(
                user_id="alice",
                scope=SCOPE,
                action="proactive_contact",
                effect=PolicyEffect.DENY,
                reason_code="mixed_speaker_without_anchor",
                source_turn_id=turn.id,
                source_direct_user_instruction=True,
            )
        )


def test_memory_use_ledger_exposes_repetition_without_storing_output_text(
    service: CompanionMemoryService,
) -> None:
    memory = service.remember(
        MemoryInput(
            user_id="alice",
            scope=SCOPE,
            kind=MemoryKind.RITUAL,
            title="内部梗",
            content="把周一叫作小怪兽日",
            consent=ConsentState.GRANTED,
            explicit_user_request=True,
        )
    ).memory
    assert memory is not None
    use = service.record_memory_use(
        MemoryUseInput(
            user_id="alice",
            scope=SCOPE,
            memory_id=memory.id,
            response_group_id="response-one",
            use_mode=RecallUseMode.NATURAL,
            purpose="shared_joke",
            rendered_excerpt="又到小怪兽日啦",
        )
    )
    assert use.output_hash is not None
    assert "小怪兽" not in use.output_hash

    context = service.recall(RecallRequest(user_id="alice", scope=SCOPE, query="小怪兽日"))
    summary = next(item for item in context.memory_use_summaries if item.memory_id == memory.id)
    assert summary.use_count == 1
    assert len(service.export("alice").memory_uses) == 1

    service.purge(memory.id, "alice")
    assert service.list_memory_uses("alice", memory.id) == []


def test_forgotten_memory_cannot_receive_a_new_use_event(
    service: CompanionMemoryService,
) -> None:
    memory = service.remember(
        MemoryInput(
            user_id="alice",
            scope=SCOPE,
            kind=MemoryKind.RITUAL,
            title="已撤回的梗",
            content="把周二叫作云朵日",
            consent=ConsentState.GRANTED,
            explicit_user_request=True,
        )
    ).memory
    assert memory is not None
    service.forget(memory.id, "alice")

    with pytest.raises(ValueError, match="active or historical"):
        service.record_memory_use(
            MemoryUseInput(
                user_id="alice",
                scope=SCOPE,
                memory_id=memory.id,
                response_group_id="late-response",
                use_mode=RecallUseMode.NATURAL,
                purpose="should_not_happen",
            )
        )
