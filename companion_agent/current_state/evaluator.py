"""Clause-level, conservative self-report and directive recognition; no response templates."""

from __future__ import annotations

import re

from companion_agent.current_state.models import (
    CurrentStateAnalysis,
    StateKind,
    StateObservation,
    StateStatus,
)
from companion_memoryos.schemas import DiscourseSignal, ProcessTurnResult, ResponseGoal

TOPICS = (
    "面试",
    "考试",
    "房租",
    "搬家",
    "项目",
    "论文",
    "工作",
    "家人",
    "手术",
    "报告",
    "经济",
    "学业",
)
PAST = re.compile(r"去年|前年|上个月|小时候|那时候|那阵子|曾经|以前|上周")
HYPOTHETICAL = re.compile(r"假设|假如|如果|万一|举个例子|扮演|设定|角色正在")
OTHER_SUBJECT = re.compile(
    r"^(?:我(?:的)?(?:朋友|同事|家人|妈妈|爸爸|同学)|他|她|他们|她们|朋友|同事|听说|据说)"
)
NEGATIVE = re.compile(r"(?:不是|并不|不再|没有|没|不|并没有)(?:觉得|感到|那么|特别|很)?$")
ADVICE = re.compile(
    r"(?:帮我|给我|替我|请你|一起|能不能).{0,10}(?:办法|方案|建议|对策|主意|思路|选项|解决)|(?:需要|想听|要听|可以给).{0,5}(?:建议|方案)|有什么.{0,4}(?:办法|思路|建议)"
)
LISTEN = re.compile(
    r"(?:先|暂时|今天|现在)?.{0,3}(?:别|不要|不用|不想|不需要).{0,4}(?:建议|方案|主意|对策|办法|说教|分析)|(?:听我(?:说|讲)|让我.{0,5}(?:说|讲)).{0,5}(?:就好|就行|完|下去)|(?:只|就)想.{0,3}(?:倾诉|吐槽|说说)"
)
TASK = re.compile(
    r"(?:帮我|请|给我|替我|麻烦你).{0,10}(?:修改|改一下|改改|润色|翻译|写|解释|比较|计算|整理|检查|查一下|分析|列出)|(?:怎么|如何|多少|为什么|是什么|哪个好|能否|能不能)"
)
CONDITIONS = {
    "fatigue": re.compile(r"疲惫|疲倦|(?:很|好|太|有点|只是)累|累(?:了|得|坏了|死了|$)"),
    "sleep_loss": re.compile(r"(?:没|没有|未)睡好|没睡够|失眠"),
    "sadness": re.compile(r"难过|伤心|低落"),
    "pressure": re.compile(r"压力|紧张|焦虑|担心"),
}


def eligible_clauses(text: str) -> list[str]:
    # Span-aware filtering happens in MemoryOS first; also remove unannotated quotations.
    text = re.sub(r'“[^”]*”|「[^」]*」|"[^"\n]*"', "", text)
    clauses = []
    for raw in re.split(r"[，,。；;！!？?\n]", text):
        clause = re.sub(r"^(?:(?:但是|不过|可是|而且|其实|但)\s*)+", "", raw.strip())
        if not clause or OTHER_SUBJECT.search(clause) or HYPOTHETICAL.search(clause):
            continue
        if PAST.search(clause) and not re.search(r"现在|今天|目前|仍然|依然", clause):
            continue
        if re.search(r"将会|到时候|可能会|会不会", clause):
            continue
        if re.search(r"昨晚|昨天|昨日", clause) and not CONDITIONS["sleep_loss"].search(clause):
            continue
        clauses.append(clause)
    return clauses


def analyze_current_turn(text: str, result: ProcessTurnResult) -> CurrentStateAnalysis:
    analysis = CurrentStateAnalysis()
    clauses = eligible_clauses(text)
    accepted = "，".join(clauses)
    analysis.topics = [topic for topic in TOPICS if topic in accepted]
    analysis.concrete_task = bool(TASK.search(accepted)) or text.rstrip().endswith(("?", "？"))
    analysis.topic_switch = bool(re.search(r"换个话题|换一个话题|不聊这个|先聊别的", accepted))
    analysis.stop_reference = bool(
        re.search(r"(?:别|不要|不想).{0,4}(?:再提|再说这件|提这件)", accepted)
    )
    analysis.permanent_address_boundary = bool(
        re.search(r"(?:以后|今后|一直|永远).{0,6}(?:别|不要).{0,10}(?:称呼|叫我)", accepted)
    )
    self_context = bool(re.search(r"我|今天|现在|最近|目前|昨晚", accepted))
    for clause in clauses:
        today = "今天" in accepted or "今日" in accepted
        # Within a turn, a later explicit directive wins. A quoted or reported request cannot.
        listen = LISTEN.search(clause)
        advice = ADVICE.search(clause)
        if listen:
            analysis.explicit_goal = ResponseGoal.LISTEN
        elif advice and not re.search(r"(?:别|不要|不用|不想).{0,5}(?:建议|方案|办法)", clause):
            analysis.explicit_goal = ResponseGoal.PROBLEM_SOLVE
        if re.search(
            r"(?:今天|现在|暂时|先)?.{0,4}(?:别|不要|不想).{0,4}(?:玩笑|调侃|吐槽我)", clause
        ):
            analysis.observations.append(
                StateObservation(
                    kind=StateKind.STYLE, slot="humor", value="reduce", applies_today=today
                )
            )
        if re.search(r"(?:可以|不用再避开|恢复).{0,4}(?:开玩笑|调侃)", clause):
            analysis.observations.append(
                StateObservation(
                    kind=StateKind.STYLE,
                    slot="humor",
                    value="normal",
                    status=StateStatus.ENDED,
                    reason="user_released_style_request",
                )
            )
        for name, pattern in CONDITIONS.items():
            match = pattern.search(clause)
            if (
                not match
                or not self_context
                or re.search(r"是不是|算不算|会不会|可能|也许|好像|似乎|说不上", clause)
            ):
                continue
            prefix = clause[: match.start()]
            subject_text = re.sub(r"^(?:今天|现在|最近|目前|昨晚|昨天|今日|刚才)", "", clause)
            own_subject = bool(
                re.match(r"我|很|好|太|有点|只是|还是|没睡好|没有睡好|失眠|疲惫|疲倦", subject_text)
            )
            own_subject = own_subject or bool(re.search(r"让我|我感到|我觉得", prefix))
            if (
                not own_subject
                or re.search(r"帮我|请|翻译|解释|想问|怎么写|把.+改", prefix)
                or re.match(r"(?:是什么意思|是什么|的英文)", clause[match.end() :])
            ):
                continue
            negated = bool(NEGATIVE.search(prefix[-12:]))
            topic = next((topic for topic in analysis.topics if topic in clause), None)
            if topic is None and len(analysis.topics) == 1:
                topic = analysis.topics[0]
            if name != "pressure":
                topic = None
            analysis.observations.append(
                StateObservation(
                    kind=StateKind.CONDITION,
                    slot=f"{name}:{topic or 'general'}",
                    value=name,
                    topic=topic,
                    status=StateStatus.RETRACTED if negated else StateStatus.ACTIVE,
                    reason="explicit_user_correction" if negated else "direct_recent_self_report",
                )
            )
        # Relations with a third party are not a conflict with the companion.
        other_target = bool(re.search(r"同事|朋友|老板|家人|父母", clause)) and not bool(
            re.search(r"你(?:刚才|一直|总|又)|和你|咱俩", clause)
        )
        if (
            not other_target
            and re.search(
                r"(?:你|我们).{0,12}(?:打断|误解|误会|争吵|吵架|不尊重|没听我)|(?:对你|生你的气)",
                clause,
            )
            and not re.search(r"你(?:可以|随时|尽管)|允许你", clause)
        ) and re.search(r"不舒服|难受|生气|别|不要|打断|争吵|误会|没听", clause):
            analysis.conflict = True
        if (
            not other_target
            and re.search(
                r"(?:误会|争吵|分歧|我们之间).{0,8}(?:说开|解决|和解)|不再生你的气|原谅你", clause
            )
            and not re.search(r"还没|没有|未解决|没说开", clause)
        ):
            analysis.repair = True
            analysis.conflict = False
        if re.search(r"(?:结束|完成|考完|面完|搞定|通过|出结果|有结果)", clause) and not re.search(
            r"还没|没有|尚未|没结束|未完成|没通过", clause
        ):
            analysis.completed_topics.extend(
                topic
                for topic in analysis.topics
                if re.search(
                    re.escape(topic) + r"(?:已经|已|终于|总算|刚刚|刚|今天|顺利){0,3}"
                    r"(?:结束|完成|通过|考完|面完|出结果|有结果)",
                    clause,
                )
            )
    # Reuse the existing optional interpreter's discourse decision, without extracting
    # speculative emotional states or making another provider call.
    if analysis.explicit_goal is None and result.discourse is not None and clauses:
        signals = set(result.discourse.signals)
        if (
            signals & {DiscourseSignal.LISTEN_ONLY, DiscourseSignal.ADVICE_REQUESTED}
            and result.discourse.suggested_goal
            and re.search(r"听我|建议|办法|方案|帮我|吐槽|倾诉", accepted)
        ):
            analysis.explicit_goal = result.discourse.suggested_goal
    if analysis.explicit_goal is not None:
        analysis.observations.append(
            StateObservation(
                kind=StateKind.COMMUNICATION,
                slot="need",
                value=analysis.explicit_goal.value,
                applies_today="今天" in accepted or "今日" in accepted,
            )
        )
    if analysis.stop_reference:
        analysis.observations.append(
            StateObservation(
                kind=StateKind.STYLE,
                slot="reference",
                value="hold",
                reason="user_requested_no_reference_not_resolution",
            )
        )
    elif clauses and (
        bool(result.discourse and result.discourse.user_asked_memory_question)
        or re.search(r"(?:继续|接着|重新|再).{0,3}(?:聊|说|讨论)", accepted)
    ):
        analysis.observations.append(
            StateObservation(
                kind=StateKind.STYLE,
                slot="reference",
                value="normal",
                status=StateStatus.ENDED,
                reason="user_reopened_topic",
            )
        )
    analysis.completed_topics = list(dict.fromkeys(analysis.completed_topics))
    return analysis
