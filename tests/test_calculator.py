"""Arithmetic evidence travels through the same bounded tool loop as other tools."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from companion_agent.automation.calculator import CalculationError, calculate
from companion_agent.automation.loop import AgentLoop
from companion_agent.context import ChatMessage
from tests.test_agent_automation import ScriptModel, hub_at


def test_named_decimal_totals_balances_and_difference_reach_model(tmp_path: Path) -> None:
    hub, external, _ = hub_at(tmp_path)
    calculations = [
        {"name": "a_total", "expression": "87.90 * 2 + 23.40"},
        {"name": "b_total", "expression": "61.25 * 2 + 15.60"},
        {"name": "a_left", "expression": "260 - a_total"},
        {"name": "b_left", "expression": "260 - b_total"},
        {"name": "left_difference", "expression": "b_left - a_left"},
    ]
    model = ScriptModel("calculate", {"calculations": calculations})
    loop = AgentLoop(model, hub)
    with loop.run("c", "costs") as run:
        loop.generate([ChatMessage(role="user", content="核对两个方案的花费、余额和差额。")])
    assert run.steps == 2 and run.tool_calls == 1 and run.status == "completed"
    result = json.loads(model.histories[-1][-1]["content"])
    assert result["status"] == "succeeded"
    assert [row["value"] for row in result["results"]] == [
        "199.2",
        "138.1",
        "60.8",
        "121.9",
        "61.1",
    ]
    assert not any(row["approximate"] for row in result["results"])
    assert not external.calls
    assert hub.store.actions()[0]["tool_name"] == "calculate"
    assert not hub.store.jobs()


def test_decimal_precision_and_rounding_propagate() -> None:
    result = calculate(
        [
            {"name": "sum", "expression": "0.1 + 0.2"},
            {"name": "ratio", "expression": "1 / 3"},
            {"name": "restored", "expression": "ratio * 3"},
            {"name": "signed", "expression": "-(2 + 3) * +2.5"},
        ]
    )["results"]
    assert result[0]["value"] == "0.3" and not result[0]["approximate"]
    assert result[1]["value"].startswith("0.333333") and result[1]["approximate"]
    assert result[2]["approximate"]
    assert result[3]["value"] == "-12.5" and not result[3]["approximate"]


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').getcwd()",
        "open('some-file', 'w')",
        "(1).__class__",
        "[1][0]",
        "True + 1",
        "'1' + '2'",
        "2 ** 1000000",
        "1 // 2",
        "1 % 2",
        "0x10",
        "1_000",
        "unknown + 1",
        "1 / 0",
        "1e999",
        "1e-99",
        "1e24 * 2",
        "1e-24 / 2",
        "1+" * 100 + "1",
        "-" * 20 + "1",
        "",
        "1 +",
        "round(1, 999)",
        "round(1, True)",
        "round(1, 1.5)",
        "round(1, -1)",
        "round(1, ndigits=2)",
        "round()",
        "round(1, 2, 3)",
        "round(__import__('os').getcwd())",
    ],
)
def test_unsupported_or_unbounded_expressions_are_rejected(expression: str) -> None:
    with pytest.raises(CalculationError):
        calculate([{"name": "result", "expression": expression}])


def test_failed_calculation_has_no_partial_success_or_external_execution(tmp_path: Path) -> None:
    hub, external, _ = hub_at(tmp_path)
    result = hub.invoke(
        "calculate",
        {"calculations": [{"name": "result", "expression": "1/0"}]},
        "c",
        "zero",
    )
    assert result["status"] == "failed" and "零" in result["message"]
    assert "results" not in result and not external.calls
    assert hub.invoke("calculate", {"calculations": []}, "c", "empty")["status"] == "denied"
    hub.config.loop.enabled = False
    assert (
        hub.invoke(
            "calculate", {"calculations": [{"name": "r", "expression": "1+2"}]}, "c", "disabled"
        )["status"]
        == "denied"
    )


def test_duplicate_names_and_forward_references_are_rejected() -> None:
    with pytest.raises(CalculationError):
        calculate([{"name": "x", "expression": "1"}, {"name": "x", "expression": "2"}])
    with pytest.raises(CalculationError):
        calculate([{"name": "x", "expression": "y+1"}, {"name": "y", "expression": "2"}])


def test_chinese_named_results_and_explicit_decimal_rounding(tmp_path: Path) -> None:
    hub, external, _ = hub_at(tmp_path)
    result = hub.invoke(
        "calculate",
        {
            "calculations": [
                {"name": "A_花费", "expression": "187.60"},
                {"name": "B_花费", "expression": "138.10"},
                {"name": "节省比例", "expression": "round((A_花费-B_花费)/A_花费*100, 2)"},
                {"name": "小数边界", "expression": "round(2.345, 2)"},
                {"name": "负数边界", "expression": "round(-2.345, 2)"},
                {"name": "取整", "expression": "round(2.5)"},
            ]
        },
        "c",
        "chinese-rounding",
    )
    assert result["status"] == "succeeded" and result["rounding"] == "half_up"
    assert [r["value"] for r in result["results"]] == [
        "187.6",
        "138.1",
        "26.39",
        "2.35",
        "-2.35",
        "3",
    ]
    assert all(r["approximate"] for r in result["results"][2:])
    assert not external.calls


def test_old_calculations_cannot_displace_latest_user_correction(tmp_path: Path) -> None:
    hub, _, _ = hub_at(tmp_path)
    hub.invoke(
        "calculate",
        {"calculations": [{"name": "old_total", "expression": "10+20"}]},
        "c",
        "old-request",
    )
    model = ScriptModel(
        "calculate", {"calculations": [{"name": "new_total", "expression": "10+15"}]}
    )
    loop = AgentLoop(model, hub)
    correction = "第二项应该是15，其他不变。重新计算。"
    with loop.run("c", "corrected"):
        loop.generate(
            [
                ChatMessage(role="system", content="应用规则"),
                ChatMessage(role="user", content="先算10+20。"),
                ChatMessage(role="assistant", content="合计30。"),
                ChatMessage(role="user", content=correction),
            ]
        )
    sent = model.histories[0]
    assert sent[-1] == {"role": "user", "content": correction}
    record_index = next(
        i for i, m in enumerate(sent) if str(m.get("content", "")).startswith("本地工具记录")
    )
    old_user_index = next(i for i, m in enumerate(sent) if m.get("content") == "先算10+20。")
    assert sent[record_index]["role"] == "user" and record_index < old_user_index
