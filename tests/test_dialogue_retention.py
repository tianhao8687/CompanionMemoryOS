"""Retrieval confidence must not erase an interlocutor's immediately preceding position."""

from datetime import UTC, datetime

import pytest

from companion_agent.evidence_policy import filter_recent_turns
from companion_agent.relationship.models import RelationshipKey
from companion_memoryos.experience import plan_memory_use
from companion_memoryos.schemas import (
    ConsentState,
    ConversationRole,
    ConversationTurnInput,
    ExperienceEvidenceKind,
    MemoryReferenceFeedbackInput,
    MemoryReferenceMode,
    MemoryScope,
    RecallRequest,
    RecallUseMode,
    ReferenceFeedbackKind,
    ResponseGoal,
    ResponsePlanRequest,
    RetrievalAction,
    TurnRecallItem,
)
from companion_memoryos.service import CompanionMemoryService

KEY = RelationshipKey(user_id="u", companion_id="xiaohe", relationship_id="r")
SCOPE = MemoryScope(companion_id="xiaohe", relationship_id="r", conversation_id="c")


def dialogue(service: CompanionMemoryService):
    user = service.append_turn(
        ConversationTurnInput(
            user_id="u",
            scope=SCOPE,
            actor_id="u",
            role=ConversationRole.USER,
            content="你想先逛哪边？",
            consent=ConsentState.GRANTED,
        )
    ).turn
    assert user
    reply = service.append_turn(
        ConversationTurnInput(
            user_id="u",
            scope=SCOPE,
            actor_id="xiaohe",
            role=ConversationRole.ASSISTANT,
            content="我想先看看旧唱片。",
            consent=ConsentState.GRANTED,
            reply_to_turn_id=user.id,
        )
    ).turn
    assert reply
    return user, reply


def reference_plan(service, turn, *, scope=SCOPE, feedback=None):
    context = service.recall(RecallRequest(user_id="u", scope=scope, query="另一个话题"))
    context = context.model_copy(
        update={
            "sections": {},
            "event_fallback": [],
            "state_result": None,
            "retrieval_action": RetrievalAction.ABSTAIN,
            "turn_fallback": [
                TurnRecallItem(
                    turn=turn,
                    evidence_text=turn.content,
                    lexical=0.05,
                    temporal=0.0,
                    recency=1.0,
                    total=0.1,
                    recall_confidence=0.05,
                    use_mode=RecallUseMode.DO_NOT_ASSERT,
                    reasons=["raw_turn_fallback", "non_user_turn_not_user_fact"],
                )
            ],
        }
    )
    return plan_memory_use(
        context,
        ResponsePlanRequest(
            user_id="u", scope=scope, trigger_turn_id="current", goal=ResponseGoal.DIRECT_ANSWER
        ),
        feedback or {},
        set(),
        service.config,
    )


def test_low_retrieval_confidence_keeps_current_assistant_dialogue(service):
    user, reply = dialogue(service)
    plan = reference_plan(service, reply)
    # Still ineligible as retrieved factual evidence; retaining native speech is separate.
    assert plan.decisions[0].mode is MemoryReferenceMode.SUPPRESS
    assert filter_recent_turns(service, KEY, [user, reply], plan, datetime.now(UTC)) == [
        user,
        reply,
    ]


@pytest.mark.parametrize("target", ["user", "reply"])
def test_explicit_reference_feedback_still_hides_reply_lineage(service, target):
    user, reply = dialogue(service)
    source = user if target == "user" else reply
    service.record_reference_feedback(
        MemoryReferenceFeedbackInput(
            user_id="u",
            scope=SCOPE,
            evidence_kind=ExperienceEvidenceKind.TURN,
            evidence_id=source.id,
            kind=ReferenceFeedbackKind.DO_NOT_REFERENCE,
        )
    )
    plan = reference_plan(service, reply)
    retained = filter_recent_turns(service, KEY, [user, reply], plan, datetime.now(UTC))
    assert reply not in retained
    assert (user in retained) == (target == "reply")


def test_deleted_source_still_hides_retained_dialogue(service):
    user, reply = dialogue(service)
    plan = reference_plan(service, reply)
    service.forget_turn(user.id, "u")
    assert not filter_recent_turns(service, KEY, [reply], plan, datetime.now(UTC))


def test_dialogue_exception_does_not_recover_user_or_other_session_evidence(service):
    user, reply = dialogue(service)
    plan = reference_plan(service, user)
    assert not filter_recent_turns(service, KEY, [user, reply], plan, datetime.now(UTC))
    plan = reference_plan(
        service, reply, scope=SCOPE.model_copy(update={"conversation_id": "other"})
    )
    assert filter_recent_turns(service, KEY, [user, reply], plan, datetime.now(UTC)) == [user]
