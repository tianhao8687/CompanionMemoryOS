from __future__ import annotations

import re
from datetime import datetime

from companion_memoryos.config import CompanionConfig
from companion_memoryos.constants import (
    EMPTY_SCORE,
    HALF_LIFE_BASE,
    PERFECT_SCORE,
    SECONDS_PER_DAY,
)
from companion_memoryos.schemas import EmotionSignal, MemoryRecord, RecallRequest, ScoreBreakdown

_WORD_PATTERN = re.compile(r"[A-Za-z0-9_]+")
_CJK_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")


def tokenize(text: str, config: CompanionConfig) -> set[str]:
    tokens = {
        match.group().casefold()
        for match in _WORD_PATTERN.finditer(text)
        if len(match.group()) >= config.retrieval.minimum_token_length
    }
    for match in _CJK_PATTERN.finditer(text):
        segment = match.group()
        for size in range(config.retrieval.cjk_ngram_min, config.retrieval.cjk_ngram_max + 1):
            tokens.update(segment[index : index + size] for index in range(len(segment) - size + 1))
    return tokens


def build_fts_query(text: str, config: CompanionConfig) -> str:
    selected = sorted(tokenize(text, config))[: config.retrieval.max_fts_terms]
    return " OR ".join('"' + token.replace('"', '""') + '"' for token in selected)


def score_memory(
    memory: MemoryRecord,
    request: RecallRequest,
    config: CompanionConfig,
    as_of: datetime,
) -> ScoreBreakdown:
    query_tokens = tokenize(request.query, config)
    memory_tokens = tokenize(
        " ".join([memory.title, memory.content, *memory.needs]),
        config,
    )
    lexical = _jaccard(query_tokens, memory_tokens)
    salience = memory.salience * memory.confidence
    recency = _recency(memory.event_at, as_of, config.retrieval.recency_half_life_days)
    emotion = _emotion_similarity(request.emotions, memory.emotions)
    need = _jaccard(set(request.needs), set(memory.needs))
    continuity = config.continuity[request.intent][memory.kind]
    weights = config.ranking
    total = (
        lexical * weights.lexical
        + salience * weights.salience
        + recency * weights.recency
        + emotion * weights.emotion
        + need * weights.need
        + continuity * weights.continuity
    )
    return ScoreBreakdown(
        lexical=lexical,
        salience=salience,
        recency=recency,
        emotion=emotion,
        need=need,
        continuity=continuity,
        total=total,
    )


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return EMPTY_SCORE
    return len(left & right) / len(left | right)


def _recency(event_at: datetime, as_of: datetime, half_life_days: float) -> float:
    age_days = max(EMPTY_SCORE, (as_of - event_at).total_seconds() / SECONDS_PER_DAY)
    return float(HALF_LIFE_BASE ** (age_days / half_life_days))


def _emotion_similarity(left: list[EmotionSignal], right: list[EmotionSignal]) -> float:
    if not left or not right:
        return EMPTY_SCORE
    left_by_label = {signal.label: signal for signal in left}
    right_by_label = {signal.label: signal for signal in right}
    labels = set(left_by_label) | set(right_by_label)
    shared = set(left_by_label) & set(right_by_label)
    if not shared:
        return EMPTY_SCORE
    label_similarity = len(shared) / len(labels)
    intensity_similarity = sum(
        PERFECT_SCORE - abs(left_by_label[label].intensity - right_by_label[label].intensity)
        for label in shared
    ) / len(shared)
    return (label_similarity + intensity_similarity) / len((label_similarity, intensity_similarity))
