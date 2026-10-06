import json

import pytest

from companion_agent.testing.long_context_benchmark import chunks, span_metrics, summarize


def test_chunking_covers_original_nonwhitespace_characters():
    text = " \n" + "长上下文测试。" * 200 + "\n "
    spans = chunks(text)
    assert all(text[left:right] == text[left:right].strip() for left, right in spans)
    assert all(right - left <= 320 for left, right in spans)
    assert span_metrics(text, (0, len(text)), spans)["coverage"] == 1


def test_reference_coverage_deduplicates_overlapping_spans():
    assert span_metrics("abcdefghij", (0, 10), [(0, 5), (3, 8)])["coverage"] == 0.8
    assert span_metrics("abc def", (0, 7), [(0, 3), (4, 7)])["full_reference"] == 1
    assert span_metrics("abcdefghij", (0, 10), [])["coverage"] == 0


@pytest.mark.parametrize("width,overlap", [(0, 0), (3, 3), (3, -1)])
def test_invalid_chunks_are_rejected(width, overlap):
    with pytest.raises(ValueError):
        chunks("abc", width, overlap)


def test_failed_query_stays_in_quality_denominator():
    empty = span_metrics("abc", (0, 3), [])
    full = span_metrics("abc", (0, 3), [(0, 3)])
    result = summarize(
        [
            {
                "status": "completed",
                "metrics": {str(k): full for k in (1, 3, 6)},
                "total_ms": 20,
                "retrieval_ms": 18,
                "retrieved": [(0, 3)],
            },
            {"status": "failed", "metrics": {str(k): empty for k in (1, 3, 6)}},
        ]
    )
    assert result["metrics"]["6"]["coverage"] == 0.5
    assert result["failed"] == 1
    assert result["total_ms"]["n"] == 1


def test_preparation_freezes_balanced_positions_without_using_answers(tmp_path, monkeypatch):
    from companion_agent.testing import long_context_benchmark as benchmark

    rows = []
    for position, start in enumerate((0, 12, 24)):
        for i in range(4):
            rows.append(
                {
                    "id": f"row-{position}-{i}",
                    "query": f"question-{position}-{i}",
                    "answer": "not indexed",
                    "context": "x" * start + "REF" + "y" * (30 - start),
                    "refered_chunk": "REF",
                    "qwen_length": 30,
                }
            )
    path = tmp_path / "clongeval_story_small.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    monkeypatch.setattr(benchmark, "SIZES", {"small": path.stat().st_size})
    first, audit = benchmark.prepare(tmp_path)
    second, _ = benchmark.prepare(tmp_path)
    assert first == second
    assert len(first) == 12
    assert len(audit["source_hashes"]) == 1
    assert all(
        sum(case["position"] == pos for case in first) == 4
        for pos in ("beginning", "middle", "end")
    )
