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
from companion_memoryos.temporal import TemporalHint, temporal_similarity

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


def build_search_document(texts: list[str], config: CompanionConfig) -> str:
    tokens: set[str] = set()
    for text in texts:
        tokens.update(tokenize(text, config))
    selected = sorted(tokens, key=lambda token: (-len(token), token))[
        : config.retrieval.max_index_terms
    ]
    return " ".join(selected)


def build_fts_query(text: str, config: CompanionConfig) -> str:
    selected = sorted(
        tokenize(text, config),
        key=lambda token: (-len(token), token),
    )[: config.retrieval.max_fts_terms]
    return " OR ".join('"' + token.replace('"', '""') + '"' for token in selected)


def score_memory(
    memory: MemoryRecord,
    request: RecallRequest,
    config: CompanionConfig,
    as_of: datetime,
    semantic_similarity: float = EMPTY_SCORE,
    temporal_hint: TemporalHint | None = None,
) -> ScoreBreakdown:
    query_tokens = tokenize(request.query, config)
    memory_tokens = tokenize(
        " ".join([memory.title, memory.content, *memory.needs]),
        config,
    )
    lexical = _weighted_overlap(query_tokens, memory_tokens)
    semantic = max(EMPTY_SCORE, min(PERFECT_SCORE, semantic_similarity))
    entity = entity_similarity(request, memory, config)
    temporal = (
        temporal_similarity(memory.event_at, temporal_hint)
        if temporal_hint is not None
        else EMPTY_SCORE
    )
    salience = memory.salience * memory.confidence
    recency = recency_score(memory.event_at, as_of, config.retrieval.recency_half_life_days)
    emotion = _emotion_similarity(request.emotions, memory.emotions)
    need = _weighted_overlap(set(request.needs), set(memory.needs))
    continuity = config.continuity[request.intent][memory.kind]
    weights = config.ranking
    total = (
        lexical * weights.lexical
        + semantic * weights.semantic
        + entity * weights.entity
        + temporal * weights.temporal
        + salience * weights.salience
        + recency * weights.recency
        + emotion * weights.emotion
        + need * weights.need
        + continuity * weights.continuity
    )
    return ScoreBreakdown(
        lexical=lexical,
        semantic=semantic,
        entity=entity,
        temporal=temporal,
        salience=salience,
        recency=recency,
        emotion=emotion,
        need=need,
        continuity=continuity,
        total=total,
    )


def entity_similarity(
    request: RecallRequest,
    memory: MemoryRecord,
    config: CompanionConfig,
) -> float:
    if request.entity_ids:
        requested = set(request.entity_ids)
        memory_ids = {entity.id for entity in memory.entities}
        return _weighted_overlap(requested, memory_ids)
    if not request.query or not memory.entities:
        return EMPTY_SCORE
    entity_tokens: set[str] = set()
    for entity in memory.entities:
        entity_tokens.update(tokenize(entity.name, config))
        for alias in entity.aliases:
            entity_tokens.update(tokenize(alias, config))
    return _weighted_overlap(tokenize(request.query, config), entity_tokens)


def event_entity_similarity(
    request: RecallRequest,
    entity_ids: set[str],
    entity_text: str,
    config: CompanionConfig,
) -> float:
    if request.entity_ids:
        return _weighted_overlap(set(request.entity_ids), entity_ids)
    return _weighted_overlap(tokenize(request.query, config), tokenize(entity_text, config))


def lexical_similarity(left_text: str, right_text: str, config: CompanionConfig) -> float:
    return _weighted_overlap(tokenize(left_text, config), tokenize(right_text, config))


def _weighted_overlap(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return EMPTY_SCORE
    shared_weight = sum(len(token) for token in left & right)
    smaller_weight = min(
        sum(len(token) for token in left),
        sum(len(token) for token in right),
    )
    if smaller_weight == EMPTY_SCORE:
        return EMPTY_SCORE
    return shared_weight / smaller_weight


def recency_score(event_at: datetime, as_of: datetime, half_life_days: float) -> float:
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
