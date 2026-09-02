from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from companion_memoryos.constants import (
    AMBIGUITY_MINIMUM_CANDIDATES,
    EMPTY_SCORE,
    MINIMUM_RESULT_LIMIT,
    PERFECT_SCORE,
)
from companion_memoryos.prompting import render_prompt
from companion_memoryos.schemas import (
    STATE_ANSWER_SEMANTICS,
    AnswerCardinality,
    AnswerSemantics,
    CompanionContext,
    ConversationRole,
    ConversationTurnRecord,
    EventRecallItem,
    PolicyBundleManifest,
    RealityLayer,
    RecallItem,
    RecallRequest,
    RecallUseMode,
    ResolutionStatus,
    RetrievalAction,
    RetrievalOutcome,
    ScoreBreakdown,
    StateQuery,
    TemporalAnchorRecord,
    TurnRecallItem,
)
from companion_memoryos.scoring import (
    build_fts_query,
    event_entity_similarity,
    lexical_similarity,
    recency_score,
    score_memory,
)
from companion_memoryos.service_rules import (
    AMBIGUITY_GUIDANCE,
    INCOMPLETE_RECALL_GUIDANCE,
    NO_MATCH_GUIDANCE,
    PINNED_KINDS,
    RESPONSE_GUIDANCE,
    SECTION_BY_KIND,
    STATE_CONTESTED_GUIDANCE,
    STATE_EVIDENCE_GUIDANCE,
    STATE_UNKNOWN_GUIDANCE,
    TEMPORAL_ANCHOR_AMBIGUITY_GUIDANCE,
)
from companion_memoryos.store import (
    EventSearchCandidate,
    MemorySearchCandidate,
    TurnSearchCandidate,
)
from companion_memoryos.temporal import TemporalHint, extract_temporal_hint, temporal_similarity

if TYPE_CHECKING:
    from companion_memoryos.service import CompanionMemoryService


def recall(self: CompanionMemoryService, request: RecallRequest) -> CompanionContext:
    settings = self.config.retrieval
    limit = request.limit or settings.default_limit
    limit = max(MINIMUM_RESULT_LIMIT, min(limit, settings.max_limit))
    event_limit = (
        settings.default_event_limit if request.event_limit is None else request.event_limit
    )
    event_limit = max(0, min(event_limit, settings.max_event_limit))
    turn_limit = settings.default_turn_limit if request.turn_limit is None else request.turn_limit
    turn_limit = max(0, min(turn_limit, settings.max_turn_limit))
    character_budget = request.max_characters or settings.default_max_characters
    character_budget = max(MINIMUM_RESULT_LIMIT, min(character_budget, settings.max_characters))
    token_budget = request.max_tokens or settings.default_max_tokens
    token_budget = max(MINIMUM_RESULT_LIMIT, min(token_budget, settings.max_tokens))
    state_result = None
    if request.state_predicate is not None:
        state_result = self.query_state(
            StateQuery(
                user_id=request.user_id,
                scope=request.scope,
                predicate=request.state_predicate,
                subject_actor_id=request.state_subject_actor_id,
                valid_at=request.valid_at or request.as_of,
                known_at=request.known_at or request.as_of,
                semantics=request.answer_semantics,
                reality_layer=request.state_reality_layer,
            )
        )
    state_mode = state_result is not None
    utterance_mode = request.answer_semantics is AnswerSemantics.UTTERANCE_HISTORY
    temporal_hint, resolved_anchor, anchor_candidates = self._temporal_context(request)
    anchor_ambiguity = len(anchor_candidates) >= AMBIGUITY_MINIMUM_CANDIDATES
    event_after = request.event_after or temporal_hint.start
    event_before = request.event_before or temporal_hint.end
    fts_query = build_fts_query(request.query, self.config)
    pool = self.store.active_pool(
        request.user_id,
        request.scope,
        fts_query,
        settings.candidate_pool,
        request.as_of,
        semantic_pool_size=settings.semantic_candidate_pool,
        minimum_semantic_similarity=settings.minimum_semantic_similarity,
        entity_ids=request.entity_ids,
        emotion_labels=[emotion.label for emotion in request.emotions],
        needs=request.needs,
        query_embedding=request.query_embedding,
        embedding_space=request.embedding_space,
        event_after=event_after,
        event_before=event_before,
        reality_layer=request.state_reality_layer,
    )
    has_cues = self._has_retrieval_cues(request, temporal_hint)
    items = [self._recall_item(candidate, request, temporal_hint) for candidate in pool]
    items = [
        item
        for item in items
        if item.pinned or not has_cues or item.recall_confidence >= settings.minimum_query_match
    ]
    items.sort(key=lambda item: (not item.pinned, -item.score.total, item.memory.id))
    if state_mode or utterance_mode:
        items = [item for item in items if item.pinned]
    pinned = [item for item in items if item.pinned]
    selected = [*pinned]
    selected_ids = {item.memory.id for item in selected}
    for item in items:
        if item.memory.id in selected_ids or len(selected) >= limit:
            continue
        selected.append(item)
        selected_ids.add(item.memory.id)
    structured_answer_available = (
        not utterance_mode
        and (not state_mode)
        and any(self._can_answer_from_structured(item, request, temporal_hint) for item in items)
    )
    event_items = self._recall_events(
        request,
        temporal_hint,
        fts_query,
        event_after,
        event_before,
        0 if structured_answer_available or utterance_mode or state_mode else event_limit,
        has_cues,
    )
    answerable_events = [
        item for item in event_items if item.use_mode is not RecallUseMode.DO_NOT_ASSERT
    ]
    turn_items = self._recall_turns(
        request,
        temporal_hint,
        fts_query,
        event_after,
        event_before,
        0
        if structured_answer_available
        or answerable_events
        or (
            state_result is not None
            and state_result.resolution_status is not ResolutionStatus.UNKNOWN
        )
        else turn_limit,
        has_cues,
    )
    ordinary_items = [item for item in items if not item.pinned]
    answerable_memories = [
        item for item in ordinary_items if item.use_mode is not RecallUseMode.DO_NOT_ASSERT
    ]
    answerable_turns = [
        item for item in turn_items if item.use_mode is not RecallUseMode.DO_NOT_ASSERT
    ]
    turn_ambiguity = self._turns_are_ambiguous(answerable_turns, temporal_hint)
    evidence_ambiguity = turn_ambiguity or self._is_ambiguous(
        [*pinned, *answerable_memories], answerable_events, request, temporal_hint
    )
    state_ambiguity = bool(
        state_result is not None and state_result.resolution_status is ResolutionStatus.CONTESTED
    )
    ambiguity_detected = anchor_ambiguity or state_ambiguity or evidence_ambiguity
    if state_result is not None and state_result.resolution_status is ResolutionStatus.UNKNOWN:
        retrieval_outcome = RetrievalOutcome.NO_MATCH
    elif ambiguity_detected:
        retrieval_outcome = RetrievalOutcome.AMBIGUOUS
    elif state_result is not None or answerable_memories or answerable_events or answerable_turns:
        retrieval_outcome = RetrievalOutcome.MATCH
    else:
        retrieval_outcome = RetrievalOutcome.NO_MATCH
    integrity_manifest = self.store.retrieval_integrity(
        request.user_id,
        request.scope,
        self.config.conversation_ledger.enabled,
        request.query_embedding is not None,
    )
    if (
        self.config.conversation_ledger.require_scoped_recall
        and request.scope.conversation_id is None
    ):
        integrity_manifest = integrity_manifest.model_copy(
            update={
                "negative_claim_safe": False,
                "reasons": [*integrity_manifest.reasons, "scoped_turn_recall_required"],
            }
        )
    guidance = [*RESPONSE_GUIDANCE]
    if anchor_ambiguity:
        guidance.append(TEMPORAL_ANCHOR_AMBIGUITY_GUIDANCE)
    elif state_ambiguity:
        guidance.append(STATE_CONTESTED_GUIDANCE)
    elif ambiguity_detected:
        guidance.append(AMBIGUITY_GUIDANCE)
    elif state_result is not None and state_result.resolution_status is ResolutionStatus.UNKNOWN:
        guidance.append(STATE_UNKNOWN_GUIDANCE)
        if not integrity_manifest.negative_claim_safe:
            guidance.append(INCOMPLETE_RECALL_GUIDANCE)
    elif retrieval_outcome is RetrievalOutcome.NO_MATCH:
        guidance.append(NO_MATCH_GUIDANCE)
        if not integrity_manifest.negative_claim_safe:
            guidance.append(INCOMPLETE_RECALL_GUIDANCE)
    if state_mode:
        guidance.append(STATE_EVIDENCE_GUIDANCE)
    effective_cardinality = (
        AnswerCardinality.MULTI
        if request.answer_semantics is AnswerSemantics.CHANGE_TRAJECTORY
        else request.answer_cardinality
    )
    retrieval_action = self._retrieval_action(
        retrieval_outcome,
        effective_cardinality,
        len(state_result.memories)
        if state_result is not None
        else len(answerable_memories) + len(answerable_events) + len(answerable_turns),
    )
    sections: dict[str, list[RecallItem]] = {}
    for item in pinned:
        self._append_section(sections, item)
    prompt_state_result = (
        state_result.model_copy(update={"memories": []}) if state_result is not None else None
    )
    prompt_text = render_prompt(
        guidance, sections, [], resolved_anchor, state_result=prompt_state_result
    )
    rendered_tokens = self.token_counter.count(prompt_text)
    safety_budget_exceeded = len(prompt_text) > character_budget or rendered_tokens > token_budget
    budget_exhausted = safety_budget_exceeded
    budget_omitted_count = 0
    state_evidence_omitted_count = 0
    if state_result is not None and prompt_state_result is not None:
        for memory in state_result.memories:
            trial_state = prompt_state_result.model_copy(
                update={"memories": [*prompt_state_result.memories, memory]}
            )
            trial_prompt = render_prompt(
                guidance, sections, [], resolved_anchor, state_result=trial_state
            )
            trial_tokens = self.token_counter.count(trial_prompt)
            if len(trial_prompt) <= character_budget and trial_tokens <= token_budget:
                prompt_state_result = trial_state
                prompt_text = trial_prompt
                rendered_tokens = trial_tokens
            else:
                budget_exhausted = True
                budget_omitted_count += 1
                state_evidence_omitted_count += 1
    for item in selected:
        if item.pinned:
            continue
        trial = {section: [*values] for section, values in sections.items()}
        self._append_section(trial, item)
        trial_prompt = render_prompt(
            guidance, trial, [], resolved_anchor, state_result=prompt_state_result
        )
        trial_tokens = self.token_counter.count(trial_prompt)
        if len(trial_prompt) <= character_budget and trial_tokens <= token_budget:
            sections = trial
            prompt_text = trial_prompt
            rendered_tokens = trial_tokens
        else:
            budget_exhausted = True
            budget_omitted_count += 1
    budgeted_events: list[EventRecallItem] = []
    for event_item in event_items:
        trial_events = [*budgeted_events, event_item]
        trial_prompt = render_prompt(
            guidance, sections, trial_events, resolved_anchor, state_result=prompt_state_result
        )
        trial_tokens = self.token_counter.count(trial_prompt)
        if len(trial_prompt) <= character_budget and trial_tokens <= token_budget:
            budgeted_events = trial_events
            prompt_text = trial_prompt
            rendered_tokens = trial_tokens
        else:
            budget_exhausted = True
            budget_omitted_count += 1
    budgeted_turns: list[TurnRecallItem] = []
    for turn_item in turn_items:
        trial_turns = [*budgeted_turns, turn_item]
        trial_prompt = render_prompt(
            guidance, sections, budgeted_events, resolved_anchor, trial_turns, prompt_state_result
        )
        trial_tokens = self.token_counter.count(trial_prompt)
        if len(trial_prompt) <= character_budget and trial_tokens <= token_budget:
            budgeted_turns = trial_turns
            prompt_text = trial_prompt
            rendered_tokens = trial_tokens
        else:
            budget_exhausted = True
            budget_omitted_count += 1
    if (
        state_result is not None
        and state_result.memories
        and (prompt_state_result is not None)
        and (not prompt_state_result.memories)
    ):
        retrieval_action = RetrievalAction.ABSTAIN
    if state_evidence_omitted_count:
        retrieval_action = RetrievalAction.ABSTAIN
    if retrieval_action in {RetrievalAction.ANSWER_SINGLE, RetrievalAction.ANSWER_MULTI}:
        if state_mode:
            answer_evidence_in_prompt = bool(
                prompt_state_result is not None and prompt_state_result.memories
            )
        elif utterance_mode:
            answer_evidence_in_prompt = any(
                item.use_mode is not RecallUseMode.DO_NOT_ASSERT for item in budgeted_turns
            )
        else:
            answer_evidence_in_prompt = (
                any(
                    not item.pinned and item.use_mode is not RecallUseMode.DO_NOT_ASSERT
                    for values in sections.values()
                    for item in values
                )
                or any(item.use_mode is not RecallUseMode.DO_NOT_ASSERT for item in budgeted_events)
                or any(item.use_mode is not RecallUseMode.DO_NOT_ASSERT for item in budgeted_turns)
            )
        if not answer_evidence_in_prompt:
            retrieval_action = RetrievalAction.ABSTAIN
    included_memory_ids = [item.memory.id for values in sections.values() for item in values]
    if prompt_state_result is not None:
        included_memory_ids.extend(memory.id for memory in prompt_state_result.memories)
    included_memory_ids = list(dict.fromkeys(included_memory_ids))
    use_summaries = (
        self.store.memory_use_summaries(request.user_id, included_memory_ids)
        if self.config.memory_use_ledger.enabled
        else []
    )
    return CompanionContext(
        user_id=request.user_id,
        scope=request.scope,
        intent=request.intent,
        sections=sections,
        event_fallback=budgeted_events,
        turn_fallback=budgeted_turns,
        guidance=guidance,
        pending_review_count=self.store.pending_count(request.user_id),
        config_fingerprint=self.config.fingerprint(),
        policy_bundle=PolicyBundleManifest.model_validate(
            self.config.policy_bundle.model_dump(mode="python")
        ),
        generated_at=datetime.now(UTC),
        character_budget=character_budget,
        rendered_characters=len(prompt_text),
        token_budget=token_budget,
        rendered_tokens=rendered_tokens,
        tokenizer=self.tokenizer_name,
        prompt_text=prompt_text,
        retrieval_outcome=retrieval_outcome,
        retrieval_action=retrieval_action,
        answer_semantics=request.answer_semantics,
        answer_cardinality=effective_cardinality,
        ambiguity_detected=ambiguity_detected,
        clarification_guidance=TEMPORAL_ANCHOR_AMBIGUITY_GUIDANCE
        if anchor_ambiguity
        else STATE_CONTESTED_GUIDANCE
        if state_ambiguity
        else AMBIGUITY_GUIDANCE
        if ambiguity_detected
        else None,
        safety_budget_exceeded=safety_budget_exceeded,
        budget_exhausted=budget_exhausted,
        budget_omitted_count=budget_omitted_count,
        state_evidence_omitted_count=state_evidence_omitted_count,
        resolved_temporal_anchor=resolved_anchor,
        temporal_anchor_candidates=anchor_candidates,
        temporal_anchor_ambiguity=anchor_ambiguity,
        integrity_manifest=integrity_manifest,
        memory_use_summaries=use_summaries,
        policy_version=self.store.current_policy_version(request.user_id),
        state_result=prompt_state_result,
    )


def _recall_item(
    self: CompanionMemoryService,
    candidate: MemorySearchCandidate,
    request: RecallRequest,
    temporal_hint: TemporalHint,
) -> RecallItem:
    memory = candidate.memory
    score = score_memory(
        memory, request, self.config, request.as_of, candidate.semantic_similarity, temporal_hint
    )
    reasons = []
    if score.lexical > EMPTY_SCORE:
        reasons.append("query_match")
    if score.semantic > EMPTY_SCORE:
        reasons.append("semantic_match")
    if score.entity > EMPTY_SCORE:
        reasons.append("entity_match")
    if score.temporal > EMPTY_SCORE:
        reasons.append("time_match")
    if score.emotion > EMPTY_SCORE:
        reasons.append("emotion_match")
    if score.need > EMPTY_SCORE:
        reasons.append("need_match")
    pinned = memory.kind in PINNED_KINDS
    if pinned:
        reasons.append("safety_boundary")
    confidence = PERFECT_SCORE if pinned else self._score_confidence(score) * memory.confidence
    confidence = self._calibrate_short_query_confidence(confidence, score, request)
    use_mode = self._use_mode(confidence)
    if not pinned and memory.resolution_status is not ResolutionStatus.RESOLVED:
        use_mode = RecallUseMode.DO_NOT_ASSERT
        reasons.append("unresolved_memory_not_assertable")
    return RecallItem(
        memory=memory,
        score=score,
        reasons=reasons,
        pinned=pinned,
        recall_confidence=confidence,
        use_mode=use_mode,
    )


def _recall_events(
    self: CompanionMemoryService,
    request: RecallRequest,
    temporal_hint: TemporalHint,
    fts_query: str,
    event_after: datetime | None,
    event_before: datetime | None,
    event_limit: int,
    has_cues: bool,
) -> list[EventRecallItem]:
    if not self.config.event_archive.enabled or not event_limit or (not has_cues):
        return []
    if self.config.event_archive.require_scoped_recall and request.scope.conversation_id is None:
        return []
    settings = self.config.retrieval
    pool = self.store.event_pool(
        request.user_id,
        request.scope,
        fts_query,
        settings.event_candidate_pool,
        request.as_of,
        minimum_semantic_similarity=settings.minimum_semantic_similarity,
        entity_ids=request.entity_ids,
        query_embedding=request.query_embedding,
        embedding_space=request.embedding_space,
        event_after=event_after,
        event_before=event_before,
        reality_layer=request.state_reality_layer,
    )
    items = [self._event_item(candidate, request, temporal_hint) for candidate in pool]
    items = [item for item in items if item.recall_confidence >= settings.minimum_query_match]
    items.sort(key=lambda item: (-item.total, item.event.id))
    return items[:event_limit]


def _event_item(
    self: CompanionMemoryService,
    candidate: EventSearchCandidate,
    request: RecallRequest,
    temporal_hint: TemporalHint,
) -> EventRecallItem:
    event = candidate.event
    lexical = lexical_similarity(request.query, event.content, self.config)
    semantic = max(EMPTY_SCORE, min(PERFECT_SCORE, candidate.semantic_similarity))
    entity_text = " ".join(
        value for entity in event.entities for value in (entity.name, *entity.aliases)
    )
    entity = event_entity_similarity(
        request, {value.id for value in event.entities}, entity_text, self.config
    )
    temporal = temporal_similarity(event.occurred_at, temporal_hint)
    recency = recency_score(
        event.occurred_at, request.as_of, self.config.retrieval.recency_half_life_days
    )
    weights = self.config.ranking
    total = (
        lexical * weights.lexical
        + semantic * weights.semantic
        + entity * weights.entity
        + temporal * weights.temporal
        + recency * weights.recency
    )
    confidence = max(lexical, semantic, entity, temporal)
    if (
        len(request.query.strip()) < self.config.retrieval.minimum_natural_query_characters
        and semantic == EMPTY_SCORE
        and (entity == EMPTY_SCORE)
        and (temporal == EMPTY_SCORE)
    ):
        confidence = min(confidence, self.config.retrieval.confidence_hedge_threshold)
    reasons = []
    if lexical > EMPTY_SCORE:
        reasons.append("query_match")
    if semantic > EMPTY_SCORE:
        reasons.append("semantic_match")
    if entity > EMPTY_SCORE:
        reasons.append("entity_match")
    if temporal > EMPTY_SCORE:
        reasons.append("time_match")
    reasons.append("raw_event_fallback")
    return EventRecallItem(
        event=event,
        lexical=lexical,
        semantic=semantic,
        entity=entity,
        temporal=temporal,
        recency=recency,
        total=total,
        recall_confidence=confidence,
        use_mode=self._use_mode(confidence),
        reasons=reasons,
    )


def _recall_turns(
    self: CompanionMemoryService,
    request: RecallRequest,
    temporal_hint: TemporalHint,
    fts_query: str,
    event_after: datetime | None,
    event_before: datetime | None,
    turn_limit: int,
    has_cues: bool,
) -> list[TurnRecallItem]:
    if not self.config.conversation_ledger.enabled or not turn_limit or (not has_cues):
        return []
    if (
        self.config.conversation_ledger.require_scoped_recall
        and request.scope.conversation_id is None
    ):
        return []
    pool = self.store.turn_pool(
        request.user_id,
        request.scope,
        fts_query,
        self.config.retrieval.turn_candidate_pool,
        request.as_of,
        semantic_pool_size=self.config.retrieval.semantic_candidate_pool,
        minimum_semantic_similarity=self.config.retrieval.minimum_semantic_similarity,
        query_embedding=request.query_embedding,
        embedding_space=request.embedding_space,
        actor_id=request.utterance_actor_id
        if request.answer_semantics is AnswerSemantics.UTTERANCE_HISTORY
        else request.state_subject_actor_id or request.user_id
        if request.answer_semantics in STATE_ANSWER_SEMANTICS
        else None,
        exclude_turn_ids=request.exclude_turn_ids,
        event_after=event_after,
        event_before=event_before,
        reality_layer=request.state_reality_layer,
    )
    items = [self._turn_item(candidate, request, temporal_hint) for candidate in pool]
    items = [
        item
        for item in items
        if item.recall_confidence >= self.config.retrieval.minimum_query_match
    ]
    items.sort(key=lambda item: (-item.total, item.turn.id))
    diversified: list[TurnRecallItem] = []
    seen_episode_ids: set[str] = set()
    for item in items:
        episode_id = (
            item.turn.episode_id
            if request.answer_semantics is AnswerSemantics.EVENT_RECALL
            else None
        )
        if episode_id is not None and episode_id in seen_episode_ids:
            continue
        if episode_id is not None:
            seen_episode_ids.add(episode_id)
        diversified.append(item)
    return diversified[:turn_limit]


def _turn_item(
    self: CompanionMemoryService,
    candidate: TurnSearchCandidate,
    request: RecallRequest,
    temporal_hint: TemporalHint,
) -> TurnRecallItem:
    turn = candidate.turn
    recall_text = turn.content
    if (
        request.answer_semantics is AnswerSemantics.UTTERANCE_HISTORY
        or request.answer_semantics in STATE_ANSWER_SEMANTICS
    ):
        recall_text = self._direct_utterance_text(
            turn, request.utterance_actor_id or request.state_subject_actor_id or request.user_id
        )
    content_lexical = lexical_similarity(request.query, recall_text, self.config)
    retrieval_key_match = (
        lexical_similarity(request.query, " ".join(turn.retrieval_keys), self.config)
        if request.answer_semantics is AnswerSemantics.EVENT_RECALL
        else EMPTY_SCORE
    )
    lexical = max(content_lexical, retrieval_key_match)
    semantic = (
        max(EMPTY_SCORE, min(PERFECT_SCORE, candidate.semantic_similarity))
        if recall_text == turn.content
        else EMPTY_SCORE
    )
    temporal = temporal_similarity(turn.occurred_at, temporal_hint)
    recency = recency_score(
        turn.occurred_at, request.as_of, self.config.retrieval.recency_half_life_days
    )
    weights = self.config.ranking
    total = (
        lexical * weights.lexical
        + semantic * weights.semantic
        + temporal * weights.temporal
        + recency * weights.recency
    )
    confidence = max(lexical, semantic, temporal)
    if retrieval_key_match > max(content_lexical, semantic, temporal):
        confidence = min(confidence, self.config.retrieval.confidence_hedge_threshold)
    if (
        len(request.query.strip()) < self.config.retrieval.minimum_natural_query_characters
        and temporal == EMPTY_SCORE
    ):
        confidence = min(confidence, self.config.retrieval.confidence_hedge_threshold)
    reasons = ["raw_turn_fallback"]
    if lexical > EMPTY_SCORE:
        reasons.append("query_match")
    if retrieval_key_match > EMPTY_SCORE:
        reasons.append("retrieval_key_match")
    if semantic > EMPTY_SCORE:
        reasons.append("semantic_match")
    if temporal > EMPTY_SCORE:
        reasons.append("time_match")
    if turn.role is not ConversationRole.USER:
        reasons.append("non_user_turn_not_user_fact")
    if recall_text != turn.content:
        reasons.append("quoted_or_attributed_span_excluded")
    return TurnRecallItem(
        turn=turn,
        evidence_text=recall_text,
        lexical=lexical,
        semantic=semantic,
        temporal=temporal,
        recency=recency,
        total=total,
        recall_confidence=confidence,
        use_mode=self._use_mode(confidence),
        reasons=reasons,
    )


def _direct_utterance_text(turn: ConversationTurnRecord, actor_id: str) -> str:
    if turn.actor_id != actor_id:
        return ""
    if not turn.speech_spans:
        return turn.content
    characters = list(turn.content)
    for span in turn.speech_spans:
        direct_span = (
            span.quote_depth == 0
            and span.reality_layer not in {RealityLayer.QUOTE, RealityLayer.FICTION}
            and (span.attributed_speaker_id in {None, actor_id})
        )
        if direct_span:
            continue
        characters[span.start_offset : span.end_offset] = " " * (
            span.end_offset - span.start_offset
        )
    return "".join(characters)


def _use_mode(self: CompanionMemoryService, confidence: float) -> RecallUseMode:
    settings = self.config.retrieval
    if confidence >= settings.confidence_natural_threshold:
        return RecallUseMode.NATURAL
    if confidence >= settings.confidence_hedge_threshold:
        return RecallUseMode.HEDGE
    return RecallUseMode.DO_NOT_ASSERT


def _can_answer_from_structured(
    item: RecallItem, request: RecallRequest, temporal_hint: TemporalHint
) -> bool:
    if item.pinned or item.use_mode is RecallUseMode.DO_NOT_ASSERT:
        return False
    if temporal_hint.has_window and item.score.temporal == EMPTY_SCORE:
        return False
    if request.entity_ids and item.score.entity == EMPTY_SCORE:
        return False
    if request.emotions and item.score.emotion == EMPTY_SCORE:
        return False
    return not request.needs or item.score.need != EMPTY_SCORE


def _calibrate_short_query_confidence(
    self: CompanionMemoryService, confidence: float, score: ScoreBreakdown, request: RecallRequest
) -> float:
    if len(request.query.strip()) >= self.config.retrieval.minimum_natural_query_characters:
        return confidence
    non_lexical = max(score.semantic, score.entity, score.temporal, score.emotion, score.need)
    if non_lexical > EMPTY_SCORE:
        return confidence
    return min(confidence, self.config.retrieval.confidence_hedge_threshold)


def _score_confidence(score: ScoreBreakdown) -> float:
    return max(
        score.lexical, score.semantic, score.entity, score.temporal, score.emotion, score.need
    )


def _temporal_hint(request: RecallRequest) -> TemporalHint:
    if request.event_after is not None or request.event_before is not None:
        return TemporalHint(start=request.event_after, end=request.event_before)
    return extract_temporal_hint(request.query, request.as_of, request.calendar_timezone)


def _temporal_context(
    self: CompanionMemoryService, request: RecallRequest
) -> tuple[TemporalHint, TemporalAnchorRecord | None, list[TemporalAnchorRecord]]:
    hint = self._temporal_hint(request)
    settings = self.config.temporal_anchors
    if hint.has_window or hint.prefer_recent or (not settings.enabled):
        return (hint, None, [])
    candidates = self.store.resolve_temporal_anchors(
        request.user_id,
        request.scope,
        request.query,
        request.as_of,
        settings.minimum_match_characters,
        settings.max_matches,
    )
    if len(candidates) == 1:
        anchor = candidates[0]
        return (TemporalHint(start=anchor.start_at, end=anchor.end_at), anchor, candidates)
    return (hint, None, candidates)


def _has_retrieval_cues(request: RecallRequest, temporal_hint: TemporalHint) -> bool:
    return bool(
        request.query
        or request.emotions
        or request.needs
        or request.entity_ids
        or request.query_embedding
        or temporal_hint.has_window
        or temporal_hint.prefer_recent
    )


def _is_ambiguous(
    self: CompanionMemoryService,
    items: list[RecallItem],
    event_items: list[EventRecallItem],
    request: RecallRequest,
    temporal_hint: TemporalHint,
) -> bool:
    if not request.query:
        return False
    ordinary = [item for item in items if not item.pinned]
    if len(ordinary) >= AMBIGUITY_MINIMUM_CANDIDATES:
        first, second = ordinary[:AMBIGUITY_MINIMUM_CANDIDATES]
        if self._memory_pair_is_ambiguous(first, second, request, temporal_hint):
            return True
    if len(event_items) < AMBIGUITY_MINIMUM_CANDIDATES:
        return False
    first_event, second_event = event_items[:AMBIGUITY_MINIMUM_CANDIDATES]
    if (
        temporal_hint.prefer_recent
        and first_event.event.occurred_at != second_event.event.occurred_at
    ):
        return False
    if temporal_hint.has_window and first_event.temporal != second_event.temporal:
        return False
    if request.entity_ids and first_event.entity != second_event.entity:
        return False
    return abs(first_event.total - second_event.total) <= self.config.retrieval.ambiguity_score_gap


def _memory_pair_is_ambiguous(
    self: CompanionMemoryService,
    first: RecallItem,
    second: RecallItem,
    request: RecallRequest,
    temporal_hint: TemporalHint,
) -> bool:
    if temporal_hint.prefer_recent and first.memory.event_at != second.memory.event_at:
        return False
    if temporal_hint.has_window and first.score.temporal != second.score.temporal:
        return False
    if request.entity_ids and first.score.entity != second.score.entity:
        return False
    return abs(first.score.total - second.score.total) <= self.config.retrieval.ambiguity_score_gap


def _turns_are_ambiguous(
    self: CompanionMemoryService, items: list[TurnRecallItem], temporal_hint: TemporalHint
) -> bool:
    if len(items) < AMBIGUITY_MINIMUM_CANDIDATES:
        return False
    first, second = items[:AMBIGUITY_MINIMUM_CANDIDATES]
    if temporal_hint.prefer_recent and first.turn.occurred_at != second.turn.occurred_at:
        return False
    if temporal_hint.has_window and first.temporal != second.temporal:
        return False
    return abs(first.total - second.total) <= self.config.retrieval.ambiguity_score_gap


def _retrieval_action(
    outcome: RetrievalOutcome, cardinality: AnswerCardinality, answer_count: int
) -> RetrievalAction:
    if outcome is RetrievalOutcome.NO_MATCH:
        return RetrievalAction.ABSTAIN
    if outcome is RetrievalOutcome.AMBIGUOUS:
        return RetrievalAction.CLARIFY
    if cardinality in {AnswerCardinality.MULTI, AnswerCardinality.OPEN} and answer_count > 1:
        return RetrievalAction.ANSWER_MULTI
    return RetrievalAction.ANSWER_SINGLE


def _append_section(sections: dict[str, list[RecallItem]], item: RecallItem) -> None:
    sections.setdefault(SECTION_BY_KIND[item.memory.kind], []).append(item)
