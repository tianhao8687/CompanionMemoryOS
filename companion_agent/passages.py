"""Literal, source-addressable windows; no summaries or inferred facts."""

from __future__ import annotations

import re

from companion_memoryos.config import CompanionConfig
from companion_memoryos.scoring import lexical_similarity
from companion_memoryos.semantic_index import cosine

PASSAGE_CHARACTERS = 240
EVIDENCE_CHARACTERS = 720


def passage_spans(text: str, width: int = PASSAGE_CHARACTERS) -> list[tuple[int, int]]:
    if width < 1:
        raise ValueError("passage width must be positive")
    boundaries = [match.end() for match in re.finditer(r"[。！？!?；;\n]+", text)]
    spans: list[tuple[int, int]] = []
    start = 0
    cursor = 0
    while start < len(text):
        limit = min(start + width, len(text))
        while cursor < len(boundaries) and boundaries[cursor] <= start:
            cursor += 1
        end = limit
        index = cursor
        while index < len(boundaries) and boundaries[index] <= limit:
            end = boundaries[index]
            index += 1
        if limit == len(text):
            end = limit
        spans.append((start, end))
        start = end
    return spans


def evidence_window(
    text: str,
    query: str,
    config: CompanionConfig,
    query_vector: list[float] | None = None,
    vectors: list[tuple[int, int, list[float]]] | None = None,
) -> tuple[int, int]:
    spans = passage_spans(text)
    if not spans:
        return (0, 0)
    semantic = {
        (start, end): max(0.0, cosine(query_vector, vector))
        for start, end, vector in vectors or []
        if query_vector
    }
    best = max(
        range(len(spans)),
        key=lambda index: (
            max(
                lexical_similarity(query, text[slice(*spans[index])], config),
                semantic.get(spans[index], 0.0),
            ),
            -index,
        ),
    )
    # Keep the adjacent cause/consequence with its matching sentence, within one budget.
    left, right = max(0, best - 1), min(len(spans) - 1, best + 1)
    while spans[right][1] - spans[left][0] > EVIDENCE_CHARACTERS:
        if right > best:
            right -= 1
        else:
            left += 1
    return spans[left][0], spans[right][1]
