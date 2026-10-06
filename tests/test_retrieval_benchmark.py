from __future__ import annotations

import pytest

from companion_agent.testing.retrieval_benchmark import evidence_metrics, select_questions


def test_partial_evidence_is_not_complete_recall() -> None:
    result = evidence_metrics(["a", "x", "y"], {"a", "b"}, 3)
    assert result == {
        "recall": 0.5,
        "precision": 1 / 3,
        "returned_precision": 1 / 3,
        "hit": 1.0,
        "all_evidence": 0.0,
        "reciprocal_rank": 1.0,
    }


def test_empty_slots_and_failed_queries_do_not_inflate_precision() -> None:
    assert evidence_metrics(["a"], {"a"}, 6)["precision"] == 1 / 6
    assert evidence_metrics([], {"a"}, 6)["hit"] == 0
    assert evidence_metrics([], {"a"}, 6)["recall"] == 0


def test_cutoff_excludes_late_hit() -> None:
    assert evidence_metrics(["x", "a"], {"a"}, 1)["hit"] == 0
    assert evidence_metrics(["x", "a"], {"a"}, 3)["reciprocal_rank"] == 0.5


def test_invalid_gold_and_duplicate_results_are_rejected() -> None:
    with pytest.raises(ValueError):
        evidence_metrics([], set(), 6)
    with pytest.raises(ValueError):
        evidence_metrics(["a", "a"], {"a"}, 6)


def test_selection_keeps_all_valid_questions_and_audits_every_exclusion() -> None:
    selected, excluded = select_questions(
        {
            "sample_id": "example",
            "qa": [
                {"question": "q", "category": 1, "evidence": ["D1:1"]},
                {"question": "q", "category": 2, "evidence": ["D1:1", "D2:9"]},
                {"question": "q", "category": 3, "evidence": []},
                {"question": "q", "category": 5, "evidence": ["D1:1"]},
            ],
        },
        {"D1:1"},
    )
    assert len(selected) == 1
    assert selected[0]["gold"] == ["D1:1"]
    assert [row["reason"] for row in excluded] == [
        "unresolvable_evidence_id",
        "no_annotated_evidence",
        "adversarial_no_positive_retrieval_target",
    ]
