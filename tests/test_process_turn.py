"""Small integration replays use scripted proposals, never pretend to measure real LLM quality."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from typer.testing import CliRunner

from companion_memoryos.api import create_app
from companion_memoryos.cli import app
from companion_memoryos.config import CompanionConfig
from companion_memoryos.interpreter import InterpreterError
from companion_memoryos.schemas import (
    ConversationRole,
    ConversationTurnInput,
    DiscourseSignal,
    EntityProposal,
    EpisodeHint,
    InterpreterContext,
    InterpreterOutput,
    InterpreterUsage,
    MemoryCandidate,
    MemoryKind,
    MemoryScope,
    MemoryStatus,
    OpenLoopCandidate,
    OpenLoopKind,
    OpenLoopStatus,
    ProcessTurnRequest,
    RealityLayer,
    SpeechSpanProposal,
    StateClaim,
    TurnInterpretation,
)
from companion_memoryos.service import CompanionMemoryService

SCOPE = MemoryScope(companion_id="ai", relationship_id="rel", conversation_id="chat")


def request(text: str = "我喜欢雨天", key: str = "delivery-1", **updates):
    return ProcessTurnRequest.model_validate(
        {
            "user_id": "user",
            "scope": SCOPE,
            "content": text,
            "idempotency_key": key,
            "consent": "granted",
            "model_consent": "granted",
            **updates,
        }
    )


class ScriptedInterpreter:
    def __init__(self, proposal: TurnInterpretation | None = None, callback=None) -> None:
        self.proposal = proposal or TurnInterpretation()
        self.contexts: list[InterpreterContext] = []
        self.callback = callback

    def interpret(self, context: InterpreterContext) -> InterpreterOutput:
        self.contexts.append(context)
        if self.callback is not None:
            self.callback(context)
        return InterpreterOutput(
            interpretation=self.proposal,
            model_fingerprint="scripted:075",
            usage=InterpreterUsage(prompt_tokens=100, completion_tokens=40, total_tokens=140),
        )


def hosted(
    service: CompanionMemoryService, interpreter: ScriptedInterpreter
) -> CompanionMemoryService:
    return CompanionMemoryService(service.store, service.config, turn_interpreter=interpreter)


def test_unified_flow_commits_raw_before_one_call_and_reuses_receipt(service) -> None:
    def check_committed(context):
        assert service.store.database._active_connection.get() is None
        assert service.store.get_turn(context.current_turn.id, "user").content == "我喜欢雨天"

    model = ScriptedInterpreter(
        TurnInterpretation(
            topics=["雨天"],
            state_claims=[
                StateClaim(
                    title="天气偏好",
                    content="用户说喜欢雨天",
                    subject_actor_id="user",
                    predicate="likes_weather",
                )
            ],
        ),
        check_committed,
    )
    memory = hosted(service, model)
    first = memory.process_turn(request())
    second = memory.process_turn(request())
    assert first.interpretation_status == "completed", first.reasons
    assert second.interpretation_status == "cached"
    assert first.model_calls == 1 and second.model_calls == 0 and len(model.contexts) == 1
    assert first.storage.turn.id == second.storage.turn.id
    assert second.storage.duplicate_of == first.storage.turn.id
    assert second.storage.turn.occurred_at == first.storage.turn.occurred_at
    assert first.interpretation == second.interpretation
    assert first.model_usage.total_tokens == 140
    assert first.interpretation.processing_metadata["prompt_sha256"] is None
    saved = memory.store.get(first.interpretation.memory_ids[0], "user")
    assert saved.status is MemoryStatus.CANDIDATE
    assert saved.evidence_turn_ids == [first.storage.turn.id]
    assert first.response_context is not None
    assert first.storage.turn.id not in [
        item.turn.id for item in first.response_context.turn_fallback
    ]
    with pytest.raises(ValueError):
        memory.process_turn(request("改了内容"))


@pytest.mark.parametrize(
    "fault",
    [
        InterpreterError("interpreter_timeout"),
        RuntimeError("secret-key-provider-body"),
    ],
)
def test_model_failure_keeps_raw_and_local_recall_without_leaking_error(service, fault) -> None:
    def fail(_):
        raise fault

    model = ScriptedInterpreter(callback=fail)
    memory = hosted(service, model)
    result = memory.process_turn(request())
    assert result.interpretation_status == "failed"
    assert result.storage.stored and result.storage.turn.content == "我喜欢雨天"
    assert result.response_context is not None
    assert len(memory.store.list_turns("user")) == 1
    assert "secret-key-provider-body" not in result.model_dump_json()
    model.callback = None
    retry = memory.process_turn(request())
    assert retry.interpretation_status == "completed"
    assert retry.storage.duplicate_of == result.storage.turn.id
    assert len(model.contexts) == 2  # Explicit host retry, never an implicit transport retry.


def test_invalid_proposal_leaves_only_raw_not_partial_episode_or_candidates(service) -> None:
    model = ScriptedInterpreter(
        TurnInterpretation(
            speech_spans=[SpeechSpanProposal(start_offset=0, end_offset=1000)],
            episode_hint=EpisodeHint(action="new", title="假设事件"),
            memory_candidates=[
                MemoryCandidate(kind=MemoryKind.SHARED_MOMENT, title="候选", content="候选")
            ],
        )
    )
    memory = hosted(service, model)
    result = memory.process_turn(request())
    assert result.interpretation_status == "failed"
    assert result.storage.stored
    assert memory.list_memories("user") == [] and memory.list_episodes("user") == []
    assert memory.get_turn_interpretation(result.storage.turn.id, "user") is None


def test_explicit_local_instruction_skips_model_and_history(service) -> None:
    model = ScriptedInterpreter()
    result = hosted(service, model).process_turn(request("先听我说。"))
    assert result.interpretation_status == "rules_only"
    assert result.discourse.signals == [DiscourseSignal.LISTEN_ONLY]
    assert result.response_context is None
    assert result.model_calls == 0 and model.contexts == []


def test_natural_variant_uses_model_and_keeps_current_turn_priority(service) -> None:
    model = ScriptedInterpreter(TurnInterpretation(discourse_signals=[DiscourseSignal.LISTEN_ONLY]))
    result = hosted(service, model).process_turn(request("让我把这段说完，可以吗"))
    assert result.interpretation_status == "completed"
    assert result.discourse.current_turn_requires_full_attention
    assert result.response_context is None


def test_unknown_model_and_separate_capture_and_model_authorization(service) -> None:
    off = service.process_turn(request())
    assert off.interpretation_status == "not_configured" and off.storage.stored
    model = ScriptedInterpreter()
    memory = hosted(service, model)
    denied = memory.process_turn(request("别存这句", "capture-denied", consent="denied"))
    assert not denied.storage.stored and denied.interpretation_status == "not_stored"
    private = memory.process_turn(request("只在本地保存", "private", model_consent="denied"))
    assert private.storage.stored and private.interpretation_status == "not_authorized"
    sensitive = memory.process_turn(request("敏感经历", "sensitive", sensitivity="sensitive"))
    assert sensitive.interpretation_status == "not_authorized"
    assert model.contexts == []


def test_budget_exceeded_preserves_long_raw_and_bounded_recall(service) -> None:
    settings = service.config.interpreter.model_copy(update={"max_input_tokens": 1})
    config = service.config.model_copy(update={"interpreter": settings})
    model = ScriptedInterpreter()
    memory = CompanionMemoryService(service.store, config, turn_interpreter=model)
    content = "这是一条很长但需要完整保存的消息。" * 300
    result = memory.process_turn(request(content))
    assert result.interpretation_status == "budget_exceeded"
    assert result.storage.turn.content == content
    assert result.model_calls == 0 and model.contexts == []
    assert "long_turn_recalled_with_bounded_query_prefix" in result.reasons
    assert result.response_context is not None


def test_prompt_budget_trims_history_without_truncating_current_turn(service) -> None:
    class LengthCounter:
        def count(self, text: str) -> int:
            return len(text)

    settings = service.config.interpreter.model_copy(update={"max_input_tokens": 5000})
    config = service.config.model_copy(update={"interpreter": settings})
    memory = CompanionMemoryService(service.store, config, token_counter=LengthCounter())
    memory.process_turn(request("以前的话" * 2000, "long-history", enable_recall=False))
    model = ScriptedInterpreter()
    memory.turn_interpreter = model
    result = memory.process_turn(request("现在的一小句话", "current", enable_recall=False))
    assert result.interpretation_status == "completed", result.reasons
    assert result.estimated_input_tokens <= settings.max_input_tokens
    assert model.contexts[0].recent_turns == []
    assert model.contexts[0].current_turn.content == "现在的一小句话"


def test_context_has_recent_replies_but_not_other_scope_future_or_sensitive_data(service) -> None:
    moment = datetime.now(UTC)
    for index, changes in enumerate(
        [
            {},
            {"scope": SCOPE.model_copy(update={"companion_id": "other"})},
            {"scope": SCOPE.model_copy(update={"relationship_id": "other"})},
            {"scope": SCOPE.model_copy(update={"group_id": "other"})},
            {"sensitivity": "sensitive"},
            {"occurred_at": moment + timedelta(days=1)},
            {"reality_layer": "roleplay"},
        ]
    ):
        service.process_turn(
            request(
                f"上下文 {index}",
                f"context-{index}",
                enable_recall=False,
                occurred_at=changes.pop("occurred_at", moment - timedelta(days=1)),
                **changes,
            )
        )
    model = ScriptedInterpreter()
    result = hosted(service, model).process_turn(
        request(
            "我的上下文",
            "now",
            occurred_at=moment,
            enable_recall=False,
        )
    )
    assert result.interpretation_status == "completed", result.reasons
    assert [turn.content for turn in model.contexts[0].recent_turns] == ["上下文 0"]


def test_new_turn_during_model_call_prevents_old_response_context(service) -> None:
    def interrupt(_):
        service.append_turn(
            ConversationTurnInput(
                user_id="user",
                scope=SCOPE,
                actor_id="user",
                role="user",
                content="我换个话题",
                consent="granted",
            )
        )

    result = hosted(service, ScriptedInterpreter(callback=interrupt)).process_turn(request())
    assert result.interpretation_status == "completed"
    assert result.response_stale and result.response_context is None


def test_deleted_source_during_model_call_cannot_recreate_derived_data(service) -> None:
    def forget(context):
        service.forget_turn(context.current_turn.id, "user")

    model = ScriptedInterpreter(
        TurnInterpretation(
            state_claims=[
                StateClaim(
                    title="雨天", content="喜欢雨天", subject_actor_id="user", predicate="likes"
                )
            ]
        ),
        forget,
    )
    result = hosted(service, model).process_turn(request())
    assert result.interpretation_status == "source_invalidated"
    assert result.storage.turn is None and result.interpretation is None
    assert result.response_context is None and service.list_memories("user") == []


def test_simultaneous_duplicate_delivery_calls_model_once(service) -> None:
    entered, released = Event(), Event()

    def hold(_):
        entered.set()
        assert released.wait(5)

    model = ScriptedInterpreter(callback=hold)
    memory = hosted(service, model)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(memory.process_turn, request(enable_recall=False))
        assert entered.wait(5)
        second = executor.submit(memory.process_turn, request(enable_recall=False))
        released.set()
        results = [first.result(timeout=5), second.result(timeout=5)]
    assert {result.interpretation_status for result in results} == {"completed", "cached"}
    assert sum(result.model_calls for result in results) == 1 and len(model.contexts) == 1
    assert len(memory.store.list_turns("user")) == 1


def test_assistant_candidates_have_companion_subject_not_user_or_shared_fact(service) -> None:
    model = ScriptedInterpreter(
        TurnInterpretation(
            state_claims=[
                StateClaim(
                    title="AI 风格",
                    content="AI 提议直接安慰",
                    predicate="style",
                    subject_actor_id="ai",
                ),
                StateClaim(
                    title="错误归因",
                    content="用户喜欢红裙",
                    predicate="likes",
                    subject_actor_id="user",
                ),
            ],
            memory_candidates=[
                MemoryCandidate(kind="shared_moment", title="假约会", content="我们一起去约会")
            ],
        )
    )
    result = hosted(service, model).process_turn(
        request(
            "我会直接一点安慰你",
            role=ConversationRole.ASSISTANT,
        )
    )
    assert result.storage.turn.actor_id == "ai"
    assert result.interpretation_status == "completed"
    memories = service.list_memories("user")
    assert len(memories) == 1 and memories[0].subject_actor_id == "ai"
    assert result.response_context is None


def test_api_and_cli_unified_entry_point(tmp_path: Path, config: CompanionConfig) -> None:
    model = ScriptedInterpreter(TurnInterpretation(topics=["雨天"]))
    application = create_app(tmp_path / "api", config, turn_interpreter=model)
    token = application.state.tokens.get_or_create()
    with TestClient(application) as client:
        body = request().model_dump(mode="json")
        assert client.post("/api/v1/turns/process", json=body).status_code == 401
        response = client.post(
            "/api/v1/turns/process", json=body, headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200, response.text
        assert response.json()["interpretation_status"] == "completed"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(tmp_path / "cli"),
            "process-turn",
            "user",
            "rel",
            "chat",
            "先听我说",
            "--companion-id",
            "ai",
            "--idempotency-key",
            "cli-1",
            "--consent",
            "granted",
            "--calendar-timezone",
            "Asia/Singapore",
        ],
    )
    assert result.exit_code == 0, result.output
    assert '"interpretation_status": "rules_only"' in result.output


def test_process_schema_rejects_cross_scope_recall_and_missing_scope() -> None:
    with pytest.raises(ValidationError):
        request(scope=MemoryScope(conversation_id="chat"))
    with pytest.raises(ValidationError):
        request(recall_request={"user_id": "other", "scope": SCOPE})
    with pytest.raises(ValidationError):
        request(calendar_timezone="Not/AZone")


def test_nonreal_turn_cannot_create_real_state_and_recall_does_not_mix_realms(service) -> None:
    model = ScriptedInterpreter(
        TurnInterpretation(
            state_claims=[
                StateClaim(
                    title="错误现实状态",
                    content="我是一名骑士",
                    subject_actor_id="user",
                    predicate="occupation",
                    reality_layer=RealityLayer.REAL_WORLD,
                ),
            ],
            entities=[
                EntityProposal(ref="knight", name="骑士", reality_layer=RealityLayer.REAL_WORLD)
            ],
        )
    )
    memory = hosted(service, model)
    fiction = memory.process_turn(
        request("剧情里我是一名骑士", "fiction", reality_layer="roleplay")
    )
    assert fiction.interpretation_status == "completed"
    assert (
        fiction.interpretation.memory_ids == [] and fiction.interpretation.entity_resolutions == []
    )
    reality = memory.process_turn(request("现实里骑士这个话题我提过吗", "real"))
    assert reality.response_context is not None
    assert fiction.storage.turn.id not in [
        item.turn.id for item in reality.response_context.turn_fallback
    ]
    assert all("剧情里" not in item.content for item in model.contexts[-1].recent_turns)


def test_unverified_catalog_id_cannot_bypass_namesake_resolution(service) -> None:
    model = ScriptedInterpreter(
        TurnInterpretation(
            entities=[EntityProposal(ref="wang", name="小王")],
        )
    )
    memory = hosted(service, model)
    first = memory.process_turn(request("同事小王喜欢下雨", "first"))
    identity = first.interpretation.entity_resolutions[0].entity.id
    model.proposal = TurnInterpretation(
        state_claims=[
            StateClaim(
                title="小王偏好",
                content="小王喜欢咖啡",
                subject_actor_id=identity,
                predicate="likes",
            ),
        ]
    )
    later = memory.process_turn(request("小王喜欢咖啡", "later"))
    assert later.interpretation.memory_ids == []
    assert "unknown_subject_candidate_deferred" in later.reasons


def test_local_directive_is_not_applied_twice_after_model_enrichment(service, monkeypatch) -> None:
    calls = []
    original = service.interpret_turn

    def record(request):
        calls.append(request)
        return original(request)

    model = ScriptedInterpreter(TurnInterpretation(topics=["同名人物"]))
    memory = hosted(service, model)
    monkeypatch.setattr(memory, "interpret_turn", record)
    result = memory.process_turn(request("不是那个，我说的是我同学小王"))
    assert result.interpretation_status == "completed"
    assert len(calls) == 1
    assert DiscourseSignal.WRONG_REFERENCE in result.discourse.signals


def test_outcome_enrichment_can_resolve_previously_untargeted_local_rule(service) -> None:
    model = ScriptedInterpreter(
        TurnInterpretation(
            topics=["面试"],
            open_loop_candidates=[
                OpenLoopCandidate(
                    kind=OpenLoopKind.EVENT_OUTCOME, summary="等待面试结果", topic_keys=["面试"]
                )
            ],
        )
    )
    memory = hosted(service, model)
    first = memory.process_turn(request("下周参加面试，还没有结果", "pending", enable_recall=False))
    assert first.interpretation_status == "completed"
    loop_id = first.interpretation.open_loop_ids[0]
    model.proposal = TurnInterpretation(
        topics=["面试"], discourse_signals=[DiscourseSignal.OUTCOME_REPORTED]
    )
    result = memory.process_turn(request("面试结果出来了，是通过", "outcome", enable_recall=False))
    assert result.interpretation_status == "completed"
    assert (
        next(item for item in memory.list_open_loops("user") if item.id == loop_id).status
        is OpenLoopStatus.RESOLVED
    )
