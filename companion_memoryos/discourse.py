from __future__ import annotations

import re

from companion_memoryos.config import CompanionConfig
from companion_memoryos.schemas import (
    AutomaticActionStatus,
    DiscourseInterpretation,
    DiscourseInterpretationStatus,
    DiscourseSignal,
    MemoryScope,
    ResponseGoal,
)

LEADING_CONTEXT = re.compile(
    r"^(?:(?:但是|不过|可是|而且|其实|只是|还是|也|但|今天|今日|现在|最近|目前|刚才|昨晚|昨天)\s*)+"
)
OTHER_SUBJECT = re.compile(
    r"^(?:我(?:的)?(?:朋友|同事|家人|妈妈|爸爸|同学|老板|室友)|他|她|他们|她们|朋友|同事|听说|据说)"
)
NONASSERTIVE = re.compile(
    r"假设|假如|如果|万一|举个例子|扮演|设定|可能|也许|好像|似乎|是否|是不是|会不会"
)
NEGATION = re.compile(
    r"(?:并没有|不是|并不|不曾|未曾|没有|尚未|还没|不能|不会|不愿|不想|不要|不用|不必|不再|别|没|未|不)"
    r"(?:(?:能够|愿意|觉得|感到|可以|真的|完全|一直|马上|已经|那么|特别|要你|让你|希望你|说|再|还|就|很|太|能|想|是)\s*)*$"
)


def direct_clauses(text: str) -> list[str]:
    """A conservative fallback, retaining scope across comma-separated reported clauses.

    A placeholder prevents deleting a quote from joining unrelated words into a directive.
    Hosts' speech spans are applied before this function; this also handles plain text.
    """
    text = re.sub(r'“[^”]*”|「[^」]*」|『[^』]*』|"[^"\n]*"', "[引用]", text)
    clauses: list[str] = []
    for sentence in re.finditer(r"(?P<body>[^。；;！!？?\n]+)(?P<ending>[。；;！!？?\n]?)", text):
        reported = False
        for raw in re.split(r"[，,]|(?=但是|不过|可是|但(?:我|你|和你))", sentence["body"]):
            clause = raw.strip()
            body = LEADING_CONTEXT.sub("", clause)
            if not body:
                continue
            if OTHER_SUBJECT.search(body) or re.search(
                r"假设|假如|如果|万一|举个例子|扮演|设定", body
            ):
                reported = True
                continue
            if re.match(r"我(?!的?(?:朋友|同事|家人|同学))|你|请|帮我|给我|让我", body):
                reported = False
            if reported:
                continue
            ending = sentence["ending"]
            clauses.append(clause + (ending if ending in "？?" else ""))
    return clauses


def negated_predicate(clause: str, start: int) -> bool:
    """Only the governing prefix, not an unrelated negation elsewhere in the turn."""
    return bool(NEGATION.search(clause[:start]))


def asserted_clause(clause: str) -> bool:
    return not NONASSERTIVE.search(clause) and not re.search(r"[？?]|吗(?:[。！!]?)$", clause)


def grounded_model_signals(
    content: str,
    proposed: list[DiscourseSignal],
    *,
    evidence_text: str | None = None,
) -> list[DiscourseSignal]:
    """Model labels need matching direct evidence before they can cause local actions."""
    anchors = {
        DiscourseSignal.LISTEN_ONLY: (
            r"(?:让我|听我).{0,10}(?:说|讲)|(?:别|不要|不想).{0,5}(?:建议|分析|方案)"
            r"|(?:只|就)想.{0,3}(?:倾诉|吐槽)"
        ),
        DiscourseSignal.ADVICE_REQUESTED: (
            r"(?:帮我|给我|想听|需要).{0,10}(?:建议|办法|方案)|我该怎么办"
        ),
        DiscourseSignal.MEMORY_QUESTION: r"记得|记不记得|还记|说过|聊过",
        DiscourseSignal.WRONG_REFERENCE: r"记错|弄错|搞混|混淆|不是这件|没对上",
        DiscourseSignal.STOP_REFERENCING: r"(?:别|不要|不想).{0,4}(?:提|说这件)",
        DiscourseSignal.TOPIC_SWITCH: r"换.{0,3}话题|不聊这个|聊别的",
        DiscourseSignal.OUTCOME_REPORTED: (
            r"结束|完成|通过|考完|面完|出结果|有结果|结果出来|最后没去|后来没去"
        ),
    }
    clauses = direct_clauses(content)
    if evidence_text is not None:
        clauses = [clause for clause in clauses if clause.rstrip("？?") in evidence_text]
    return [
        signal
        for signal in proposed
        if any(
            not negated_predicate(clause, match.start())
            and not NONASSERTIVE.search(clause)
            and (signal is not DiscourseSignal.OUTCOME_REPORTED or asserted_clause(clause))
            and (signal is not DiscourseSignal.OUTCOME_REPORTED or asserted_clause(clause))
            for clause in clauses
            for match in re.finditer(anchors[signal], clause)
        )
    ]


def interpret_explicit_discourse(
    *,
    user_id: str,
    scope: MemoryScope,
    turn_id: str,
    content: str,
    config: CompanionConfig,
) -> DiscourseInterpretation:
    clauses = direct_clauses(content.casefold())
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
        signal: [
            phrase
            for phrase in phrases
            if any(
                not negated_predicate(clause, match.start()) and not NONASSERTIVE.search(clause)
                for clause in clauses
                for match in re.finditer(re.escape(phrase), clause)
            )
        ]
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
