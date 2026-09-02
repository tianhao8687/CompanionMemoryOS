from __future__ import annotations

from companion_memoryos.config import CompanionConfig
from companion_memoryos.schemas import (
    AutomaticActionStatus,
    DiscourseInterpretation,
    DiscourseInterpretationStatus,
    DiscourseSignal,
    MemoryScope,
    ResponseGoal,
)


def interpret_explicit_discourse(
    *,
    user_id: str,
    scope: MemoryScope,
    turn_id: str,
    content: str,
    config: CompanionConfig,
) -> DiscourseInterpretation:
    normalized = content.casefold()
    phrase_families = {
        DiscourseSignal.LISTEN_ONLY: config.discourse.listen_only_phrases,
        DiscourseSignal.ADVICE_REQUESTED: config.discourse.advice_request_phrases,
        DiscourseSignal.MEMORY_QUESTION: config.discourse.memory_question_phrases,
        DiscourseSignal.WRONG_REFERENCE: config.discourse.wrong_reference_phrases,
        DiscourseSignal.STOP_REFERENCING: config.discourse.stop_referencing_phrases,
        DiscourseSignal.TOPIC_SWITCH: config.discourse.topic_switch_phrases,
        DiscourseSignal.OUTCOME_REPORTED: config.discourse.outcome_reported_phrases,
    }
    matched = {
        signal: [phrase for phrase in phrases if phrase in normalized]
        for signal, phrases in phrase_families.items()
    }
    matched = {signal: phrases for signal, phrases in matched.items() if phrases}
    return interpret_discourse_signals(
        user_id=user_id, scope=scope, turn_id=turn_id, signals=list(matched), matched=matched
    )


def interpret_discourse_signals(
    *,
    user_id: str,
    scope: MemoryScope,
    turn_id: str,
    signals: list[DiscourseSignal],
    matched: dict[DiscourseSignal, list[str]] | None = None,
) -> DiscourseInterpretation:
    """Shared current-turn decisions; model proposals cannot change permanent policy."""
    signals = list(dict.fromkeys(signals))
    conflicting = {
        DiscourseSignal.LISTEN_ONLY,
        DiscourseSignal.ADVICE_REQUESTED,
    } <= set(signals)
    status = (
        DiscourseInterpretationStatus.CONFLICTING
        if conflicting
        else DiscourseInterpretationStatus.RECOGNIZED
        if signals
        else DiscourseInterpretationStatus.UNKNOWN
    )
    goal = None
    if not conflicting:
        if DiscourseSignal.LISTEN_ONLY in signals:
            goal = ResponseGoal.LISTEN
        elif DiscourseSignal.ADVICE_REQUESTED in signals:
            goal = ResponseGoal.PROBLEM_SOLVE
    full_attention = DiscourseSignal.LISTEN_ONLY in signals or conflicting
    memory_question = DiscourseSignal.MEMORY_QUESTION in signals
    interrupt = DiscourseSignal.TOPIC_SWITCH in signals
    guidance: list[str] = []
    if conflicting:
        guidance.append(
            "同一句里同时出现倾听与建议信号；先跟随最后的自然语境，不自动改变长期偏好。"
        )
    if full_attention:
        guidance.append("本轮让当前表达优先，不主动切换到旧事项或追加回访。")
    if memory_question:
        guidance.append("用户明确在问过去；检索完成前不能声称记得，也不能断言用户没说过。")
    if DiscourseSignal.WRONG_REFERENCE in signals:
        guidance.append("简短承认引用没有对上；若最近引用目标不唯一，只问一个自然线索。")
    if DiscourseSignal.STOP_REFERENCING in signals:
        guidance.append("停止主动引用该证据；这不是删除原始记录，也不要求用户再次解释。")
    if interrupt:
        guidance.append("取消尚未发送的旧回复拍，直接跟随新话题。")
    if DiscourseSignal.OUTCOME_REPORTED in signals:
        guidance.append("用户报告了事项结果；只有当前话题唯一对应一条未完成事项时才能自动关闭。")
    return DiscourseInterpretation(
        user_id=user_id,
        scope=scope,
        turn_id=turn_id,
        status=status,
        signals=signals,
        matched_phrases=matched or {},
        suggested_goal=goal,
        user_asked_memory_question=memory_question,
        current_turn_requires_full_attention=full_attention,
        interrupt_pending_response=interrupt,
        automatic_action_status=AutomaticActionStatus.NOT_REQUESTED,
        response_guidance=guidance,
    )
