"""Bounded decimal arithmetic, with no Python execution or external access."""

from __future__ import annotations

import ast
import re
from decimal import ROUND_HALF_UP, Decimal, DecimalException, Inexact, localcontext
from typing import Any


class CalculationError(ValueError):
    """A safe, user-visible explanation without evaluation internals."""


NAME_PATTERN = r"[A-Za-z\u3400-\u9fff][A-Za-z0-9_\u3400-\u9fff]{0,47}"
NAME = re.compile(NAME_PATTERN + r"\Z")
NUMBER = re.compile(r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d{1,3})?\Z")
MAX_VALUE = Decimal("1e24")
MIN_VALUE = Decimal("1e-24")


def calculate(
    calculations: list[dict[str, str]], comparisons: list[dict[str, str]] | None = None
) -> dict[str, Any]:
    """Evaluate named expressions in order; only earlier names can be referenced."""
    if not 1 <= len(calculations) <= 24:
        raise CalculationError("一次计算需要 1 到 24 个表达式。")
    if len(comparisons or []) > 24:
        raise CalculationError("一次最多比较 24 组结果。")
    values: dict[str, Decimal] = {}
    rounded: dict[str, bool] = {}
    results: list[dict[str, Any]] = []

    def bounded(value: Decimal) -> Decimal:
        magnitude = value.copy_abs()
        if not value.is_finite() or magnitude > MAX_VALUE or (value and magnitude < MIN_VALUE):
            raise CalculationError("数值超出本地计算范围。")
        return value

    for item in calculations:
        name, expression = item.get("name", ""), item.get("expression", "").strip()
        if not NAME.fullmatch(name) or name in values:
            raise CalculationError("结果名称需以中英文字开头，可含数字或下划线，且不能重复。")
        if not 1 <= len(expression) <= 256:
            raise CalculationError("表达式为空或过长。")
        try:
            tree = ast.parse(expression, mode="eval")
        except (SyntaxError, ValueError, RecursionError):
            raise CalculationError("表达式格式无效。") from None
        if sum(1 for _ in ast.walk(tree)) > 96:
            raise CalculationError("表达式过于复杂。")
        referenced: set[str] = set()

        def evaluate(
            node: ast.AST,
            depth: int = 0,
            *,
            source: str = expression,
            references: set[str] = referenced,
        ) -> Decimal:
            if depth > 16:
                raise CalculationError("表达式嵌套过深。")
            if isinstance(node, ast.Constant) and type(node.value) in {int, float}:
                literal = ast.get_source_segment(source, node) or ""
                if NUMBER.fullmatch(literal):
                    return bounded(Decimal(literal))
            elif isinstance(node, ast.Name):
                if node.id not in values:
                    raise CalculationError("表达式引用了尚未计算的名称。")
                references.add(node.id)
                return values[node.id]
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "round"
                and not node.keywords
                and 1 <= len(node.args) <= 2
            ):
                places = 0
                if len(node.args) == 2:
                    digits = node.args[1]
                    if (
                        not isinstance(digits, ast.Constant)
                        or type(digits.value) is not int
                        or not 0 <= digits.value <= 12
                    ):
                        raise CalculationError("round 的小数位需为 0 到 12 的整数。")
                    places = digits.value
                value = evaluate(node.args[0], depth + 1)
                return bounded(value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP))
            elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
                value = evaluate(node.operand, depth + 1)
                return bounded(value if isinstance(node.op, ast.UAdd) else -value)
            elif isinstance(node, ast.BinOp) and isinstance(
                node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)
            ):
                left, right = evaluate(node.left, depth + 1), evaluate(node.right, depth + 1)
                if isinstance(node.op, ast.Add):
                    return bounded(left + right)
                if isinstance(node.op, ast.Sub):
                    return bounded(left - right)
                if isinstance(node.op, ast.Mult):
                    return bounded(left * right)
                if right == 0:
                    raise CalculationError("除数不能为零。")
                return bounded(left / right)
            raise CalculationError("仅支持十进制数字、已计算的名称、括号、加减乘除和 round。")

        try:
            with localcontext() as context:
                context.prec = 28
                context.clear_flags()
                value = evaluate(tree.body)
                approximate = context.flags[Inexact] or any(rounded[ref] for ref in referenced)
        except DecimalException:
            raise CalculationError("数值无法计算。") from None
        values[name], rounded[name] = value, approximate
        formatted = format(value, "f") if value else "0"
        if "." in formatted:
            formatted = formatted.rstrip("0").rstrip(".")
        results.append(
            {"name": name, "expression": expression, "value": formatted, "approximate": approximate}
        )
    compared: list[dict[str, Any]] = []
    comparison_names: set[str] = set()
    for item in comparisons or []:
        name, left, right = item.get("name", ""), item.get("left", ""), item.get("right", "")
        if not NAME.fullmatch(name) or name in comparison_names:
            raise CalculationError("比较名称无效或重复。")
        if left not in values or right not in values:
            raise CalculationError("比较两侧必须引用本次已计算的名称。")
        comparison_names.add(name)
        with localcontext() as context:
            context.prec = 28
            context.clear_flags()
            difference = bounded(values[left] - values[right])
            approximate = rounded[left] or rounded[right] or context.flags[Inexact]
        relation = "greater" if difference > 0 else "less" if difference < 0 else "equal"
        compared.append(
            {
                "name": name,
                "left": left,
                "right": right,
                "left_value": format(values[left], "f"),
                "right_value": format(values[right], "f"),
                "relation": relation,
                "difference": format(difference, "f"),
                "approximate": approximate,
            }
        )
    return {
        "status": "succeeded",
        "results": results,
        "comparisons": compared,
        "precision_digits": 28,
        "rounding": "half_up",
    }
