import pytest

from companion_memoryos.discourse import fact_recall_clauses


@pytest.mark.parametrize(
    "text",
    [
        "帮我回忆档案的保管位置。",
        "请你回顾我们上周聊的安排。",
        "替我回忆一下原来的计划。",
    ],
)
def test_explicit_recall_directive_is_a_request(text):
    assert fact_recall_clauses(text)


@pytest.mark.parametrize(
    "text",
    [
        "不要帮我回忆之前的事情。",
        "如果我说帮我回忆旧事，你先问清楚。",
        "她说：帮我回忆档案位置。",
        "我看到一句话：‘帮我回忆一下往事’。",
        "帮我整理一下桌子。",
        "我想起来档案在青鹭柜。",
    ],
)
def test_reported_hypothetical_negative_and_unrelated_text_is_not_recall(text):
    assert not fact_recall_clauses(text)
