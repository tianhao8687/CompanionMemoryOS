from companion_agent.testing.chinese_retrieval_benchmark import (
    dialogue_text,
    prepare_samples,
    reference_ids,
)


def test_reference_parser_never_evaluates_code_or_empty_gold():
    assert reference_ids("['a', 'b', 'a']") == ["a", "b"]
    assert reference_ids("[__import__('sys').exit()]") == []
    assert reference_ids([]) == []
    assert reference_ids([123]) == []


def test_dialogue_rendering_preserves_nested_lines_and_dates():
    assert dialogue_text({"2020-01-01": [["甲:你好", "乙:早上好"]]}) == (
        "2020-01-01\n甲:你好\n乙:早上好"
    )


def test_holdout_uses_official_documents_not_answers_and_reports_exclusions():
    memories = [
        {
            "profile": {"Protagonist": name},
            "profile_description": "角色资料",
            "social_relationship": {},
            "events": {"e": {"content": "事件原文"}},
            "dialogues": {"d": {"contents": {"2020": ["甲:对话原文"]}}},
        }
        for name in ["张小红", "未查看角色"]
    ]
    sections = {
        "events": {
            "e": [
                {"Question": "事件？", "Answer": "禁止进入索引", "Reference Memory": "['e']"},
                {"Question": "坏标注？", "Reference Memory": "['missing']"},
            ]
        },
        "dialogues": {"d": [{"Question": "对话？", "Reference Memory": "['d']"}]},
    }
    samples, audits = prepare_samples(
        [{**memory} for memory in memories],
        [{name: sections} for name in ["张小红", "未查看角色"]],
        split="holdout",
    )
    assert len(samples) == 1 and samples[0]["person"] == "未查看角色"
    assert len(samples[0]["qa"]) == 2
    assert [row["evidence"] for row in samples[0]["qa"]] == [["e"], ["d"]]
    assert all("禁止进入索引" not in row["text"] for row in samples[0]["conversation"]["session_1"])
    assert sum(len(audit["excluded"]) for audit in audits) == 1
