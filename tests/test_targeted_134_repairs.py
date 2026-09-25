"""Small regressions for partial forgetting, numeric comparisons and task focus."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from companion_agent.app import LOCAL_USER
from companion_agent.automation.calculator import CalculationError, calculate
from companion_agent.automation.loop import AgentLoop
from companion_agent.context import ChatMessage
from companion_agent.evidence_policy import filter_recent_turns
from companion_agent.llm import ModelResponse
from companion_agent.memory_redaction import location_ranges, place_fragments
from companion_agent.relationship.models import RelationshipKey
from companion_memoryos.schemas import (
    ConsentState,
    ConversationRole,
    ConversationTurnInput,
    MemoryUsePlan,
    RealityLayer,
    SpeechSpan,
    TurnDeletionState,
)
from tests.test_agent_automation import ScriptModel, hub_at
from tests.test_automatic_memory import visible_context
from tests.test_companion_functional import chat, host_for
from tests.test_romance_app import RecordingLLM


class DraftModel(RecordingLLM):
    def generate(self, messages):
        self.inputs.append(messages)
        if "写一句" in messages[-1].content:
            text = "「有些没拍成，就留着。」\n旧胶片盒放在橙色帆布袋里。杯子放在书桌上。"
        else:
            text = "我在，慢慢说。"
        return ModelResponse(text=text, model="test")


def test_location_forgetting_retains_draft_and_other_object_across_restart(tmp_path: Path):
    model = DraftModel()
    host = host_for(tmp_path, model)
    original = chat(host, "旧胶片盒放在橙色帆布袋里，里面有一卷冲坏的黑白胶片。", "source")
    written = chat(host, "帮我给胶片相册写一句扉页文案。", "draft")
    chat(host, "请把旧胶片盒放在哪里这件事忘掉。", "forget")
    source = host.memory.store.get_turn(original["user"]["id"], LOCAL_USER)
    reply = host.memory.store.get_turn(written["assistant"]["id"], LOCAL_USER)
    assert source.deletion_state is TurnDeletionState.ACTIVE
    assert "冲坏的黑白胶片" in source.content and "橙色帆布袋" not in source.content
    assert reply.content == "「有些没拍成，就留着。」\n杯子放在书桌上。"
    assert reply.deletion_state is TurnDeletionState.ACTIVE
    key = RelationshipKey(
        user_id=LOCAL_USER,
        companion_id=source.scope.companion_id,
        relationship_id=source.scope.relationship_id,
    )
    assert filter_recent_turns(host.memory, key, [reply], MemoryUsePlan(), datetime.now(UTC)) == [
        reply
    ]
    with host.database.connection() as db:
        assert not db.execute("SELECT 1 FROM turn_fts WHERE content LIKE '%橙色帆布袋%'").fetchall()
    restarted = host_for(tmp_path, model)
    chat(
        restarted,
        "之前你给胶片相册写的那句扉页文案是什么？",
        "recall",
        restarted.new_conversation()["id"],
    )
    context = visible_context(model)
    assert "有些没拍成，就留着" in context
    assert "橙色帆布袋" not in context


def test_redaction_keeps_quotation_attribution_and_invalidates_old_index(service):
    content = "旧盒子在绿柜底层。她说：我住月亮上。"
    start = content.index("她说")
    turn = service.append_turn(
        ConversationTurnInput(
            user_id="u",
            scope={"conversation_id": "c"},
            actor_id="u",
            role=ConversationRole.USER,
            content=content,
            consent=ConsentState.GRANTED,
            speech_spans=[
                SpeechSpan(
                    start_offset=start,
                    end_offset=len(content),
                    quote_depth=1,
                    attributed_speaker_id="she",
                    reality_layer=RealityLayer.FICTION,
                    machine_generated=False,
                )
            ],
            retrieval_keys=["绿柜底层"],
            embedding=[1.0, 0.0],
            embedding_space="test",
            metadata={"interpreter_text": "绿柜底层"},
        )
    ).turn
    clean = service.store.redact_turn(turn.id, "u", [(0, start)])
    assert clean.content == "她说：我住月亮上。"
    assert clean.speech_spans[0].start_offset == 0
    assert clean.speech_spans[0].quote_depth == 1
    assert clean.speech_spans[0].reality_layer is RealityLayer.FICTION
    assert not clean.retrieval_keys and "interpreter_text" not in clean.metadata
    with service.store.database.connection() as db:
        assert (
            db.execute(
                "SELECT COUNT(*) FROM turn_embeddings WHERE turn_id=?", (turn.id,)
            ).fetchone()[0]
            == 0
        )
    with pytest.raises(KeyError):
        service.store.redact_turn(turn.id, "other", [(0, 1)])


def test_location_paraphrase_is_removed_but_independent_draft_is_retained():
    text = "柜子最底下。\n「有些没拍成，就留着。」"
    ranges = location_ranges(
        text, "旧胶片盒", places=place_fragments("灰色铁柜的最底层"), dependent=True
    )
    assert ranges == [(0, len("柜子最底下。\n"))]


def test_container_only_acknowledgement_cannot_reveal_forgotten_location():
    text = "帆布袋先别整个倒出来。\n「有些没拍成，就留着。」"
    ranges = location_ranges(
        text, "旧胶片盒", places=place_fragments("橙色帆布袋里"), dependent=True
    )
    assert ranges == [(0, len("帆布袋先别整个倒出来。\n"))]


def test_generation_cannot_commit_a_reply_using_a_just_redacted_source(tmp_path):
    model = RecordingLLM()
    host = host_for(tmp_path, model)
    original = chat(host, "旧盒子在绿柜底层。另有一张车票。", "source")

    def redact_during_generation(messages):
        host.memory.store.redact_turn(
            original["user"]["id"], LOCAL_USER, [(0, len("旧盒子在绿柜底层。"))]
        )
        return ModelResponse(text="在绿柜底层。", model="test")

    model.generate = redact_during_generation
    with pytest.raises(ValueError, match="source changed during generation"):
        chat(host, "旧盒子在哪儿？", "racing-reply")


@pytest.mark.parametrize(
    "amount,relation,difference", [(36, "greater", "6"), (30, "equal", "0"), (29, "less", "-1")]
)
def test_affordability_relation_and_difference_travel_through_tool_loop(
    tmp_path, amount, relation, difference
):
    hub, external, _ = hub_at(tmp_path)
    model = ScriptModel(
        "calculate",
        {
            "calculations": [
                {"name": "余额", "expression": str(amount)},
                {"name": "费用", "expression": "30"},
            ],
            "comparisons": [{"name": "追加项目", "left": "余额", "right": "费用"}],
        },
    )
    loop = AgentLoop(model, hub)
    with loop.run("c", "compare"):
        loop.generate([ChatMessage(role="user", content="帮我算够不够加这个项目。")])
    result = json.loads(model.histories[-1][-1]["content"])
    assert result["comparisons"][0]["relation"] == relation
    assert result["comparisons"][0]["difference"] == difference
    assert not external.calls


def test_comparisons_reject_missing_results_and_keep_rounding_status():
    with pytest.raises(CalculationError):
        calculate(
            [{"name": "钱", "expression": "1"}], [{"name": "比较", "left": "旧余额", "right": "钱"}]
        )
    result = calculate(
        [{"name": "三分之一", "expression": "1/3"}, {"name": "费用", "expression": "0.3"}],
        [{"name": "比较", "left": "三分之一", "right": "费用"}],
    )
    assert result["comparisons"][0]["approximate"]


def test_current_writing_task_gets_delivery_guidance_without_changing_native_user(tmp_path):
    model = RecordingLLM()
    host = host_for(tmp_path, model)
    chat(host, "刚洗完头，坐着发一会儿呆。", "casual")
    request = "我想在植物相册扉页加一句简短的话，你试着写一句，不要端着。"
    chat(host, request, "writing")
    assert model.inputs[-1][-1] == ChatMessage(role="user", content=request)
    system = model.inputs[-1][0].content
    assert system.index("[CURRENT TASK]") > system.index("[PERSONA]")
    chat(host, "哈哈，我就喜欢和你拌两句嘴。", "casual-again")
    assert "[CURRENT TASK]" not in model.inputs[-1][0].content


def test_experience_summary_does_not_hide_the_requested_original_reply(tmp_path, monkeypatch):
    import companion_agent.runtime as runtime

    model = DraftModel()
    host = host_for(tmp_path, model)
    written = chat(host, "帮我给胶片相册写一句扉页文案。", "draft")
    original = runtime.compile_experience_context

    def summarized(*args, **kwargs):
        result = original(*args, **kwargs)
        return result.model_copy(
            update={
                "text": '[{"summary":"用户曾请助手写相册文案"}]',
                "covered_evidence_ids": [
                    f"turn:{written[role]['id']}" for role in ("user", "assistant")
                ],
            }
        )

    monkeypatch.setattr(runtime, "compile_experience_context", summarized)
    chat(host, "之前你给胶片相册写的扉页那句是什么？", "recall", host.new_conversation()["id"])
    assert "有些没拍成，就留着" in visible_context(model)
