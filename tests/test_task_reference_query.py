from __future__ import annotations

import pytest

from companion_agent.memory_lifecycle import task_reference_query


@pytest.mark.parametrize(
    ("text", "reference"),
    [
        ("帮我把没去青禾公司的原因写成一句给朋友的解释。", "没去青禾公司的原因"),
        ("替我把错过云桥读书会的原因讲给同事听。", "错过云桥读书会的原因"),
        ("给我把昨天没去白桦展厅的缘由翻译成英文。", "昨天没去白桦展厅的缘由"),
        ("帮我把清单里的预算写成一条消息。", "清单里的预算"),
        ("给我把清单里的预算算一下。", "清单里的预算"),
        ("你把最后留下的三个选项解释给朋友听。", "最后留下的三个选项"),
    ],
)
def test_reference_is_a_literal_task_argument(text: str, reference: str) -> None:
    assert task_reference_query(text) == reference
    assert reference in text


@pytest.mark.parametrize(
    "text",
    [
        "帮我写一句给朋友的解释。",
        "不要帮我把那件事写成消息。",
        "如果明天有空，帮我把那件事写成消息。",
        "同事说：帮我把那件事写成消息。",
        "他说的是“帮我把那件事写成消息”。",
        "帮我把“我没去那家公司”翻译成英文。",
        "帮我把刚才编给我的故事写成一条消息。",
        "帮我把写成的草稿解释给朋友听。",
        "帮我把日程写成消息，同时替我把菜单翻译成英文。",
        "你之前把那次旅行写成的短文是什么？",
        "你把那次旅行写成的短文还在吗？",
    ],
)
def test_ambiguous_or_noncurrent_tasks_keep_the_original_query(text: str) -> None:
    assert task_reference_query(text) is None
