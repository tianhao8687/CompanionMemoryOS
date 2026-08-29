from __future__ import annotations

import ast
from pathlib import Path

RUNTIME_POLICY_FILES = [
    Path("companion_memoryos/policy.py"),
    Path("companion_memoryos/scoring.py"),
    Path("companion_memoryos/service.py"),
]
ALLOWED_LITERALS = {-1, 0, 1}


def test_behavior_modules_do_not_contain_magic_numbers() -> None:
    violations: list[str] = []
    for path in RUNTIME_POLICY_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, int | float)
                and node.value not in ALLOWED_LITERALS
            ):
                violations.append(f"{path}:{node.lineno} -> {node.value}")
    assert violations == [], "move behavioral numbers to defaults.toml:\n" + "\n".join(violations)
