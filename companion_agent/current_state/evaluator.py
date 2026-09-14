"""Conservative current assertions; uncertain semantics stay in the conversation."""

from __future__ import annotations

import re

from companion_agent.current_state.models import (
    CurrentStateAnalysis,
    StateKind,
    StateObservation,
    StateStatus,
)
from companion_memoryos.discourse import (
    LEADING_CONTEXT,
    NONASSERTIVE,
    OTHER_SUBJECT,
    asserted_clause,
    direct_clauses,
    negated_predicate,
)
from companion_memoryos.schemas import ProcessTurnResult, ResponseGoal

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
ADVICE = re.compile(
    r"(?:帮我|给我|替我|请你|一起|能不能).{0,10}(?:办法|方案|建议|对策|主意|思路|选项|解决)"
    r"|(?:需要|想听|要听|可以给).{0,5}(?:建议|方案)|有什么.{0,4}(?:办法|思路|建议)"
)
LISTEN = re.compile(
    r"(?:别|不要|不用|不想|不需要).{0,4}(?:建议|方案|主意|对策|办法|说教|分析)"
    r"|(?:先|请)听我(?:说|讲)"
    r"|(?:听我(?:说|讲)|让我.{0,5}(?:说|讲)).{0,5}(?:就好|就行|完|下去)"
    r"|(?:只|就)想.{0,3}(?:倾诉|吐槽|说说)|(?:我|只是|就)?想先(?:说|讲)完"
)
TASK = re.compile(
    r"(?:帮我|请|给我|替我|麻烦你).{0,10}(?:修改|改|润色|翻译|写|解释|比较|计算|整理|检查|查一下|分析|列出|看看)"
    r"|(?:讲|说|来).{0,3}(?:笑话|段子)|(?:怎么|如何|多少|为什么|是什么|哪个好)"
    r"|(?:你|我们).{1,20}(?:过|记得|知道|能否|能不能).{0,15}(?:吗|么|[？?])"
)
HUMOR_REQUEST = re.compile(r"(?:讲|说|来).{0,3}(?:笑话|段子)|(?:可以|恢复).{0,4}(?:开玩笑|调侃)")
CONDITIONS = {
    "fatigue": re.compile(r"疲惫|疲倦|(?:很|好|太|有点|只是)累|累(?:了|得|坏了|死了|$)"),
    "sleep_loss": re.compile(r"(?:没|没有|未)睡好|没睡够|失眠"),
    "sadness": re.compile(r"难过|伤心|低落"),
    "pressure": re.compile(r"压力|紧张|焦虑|担心"),
}
COMPLAINT = re.compile(
    r"打断(?:了)?我|误解(?:了)?我|误会(?:了)?我|不尊重我|没听我"
    r"|生你的气|对你.{0,4}(?:生气|不满|失望)|争吵|吵架|误会"
)
REPAIR = re.compile(r"原谅你|不再生你的气|(?:误会|争吵|分歧|我们之间).{0,8}(?:说开|解决|和解)")
OTHER_TARGET = re.compile(r"朋友|同事|老板|家人|父母|妈妈|爸爸|他|她")


def eligible_clauses(text: str) -> list[str]:
    clauses = []
    for clause in direct_clauses(text):
        if NONASSERTIVE.search(clause):
            continue
        if PAST.search(clause) and not re.search(r"现在|今天|目前|仍然|依然", clause):
            continue
        if re.search(r"将会|到时候|可能会|会不会", clause):
            continue
        if re.search(r"明天|后天|下周|下个月|准备|打算", clause):
            continue
        if re.search(r"昨晚|昨天|昨日", clause) and not CONDITIONS["sleep_loss"].search(clause):
            continue
        clauses.append(clause)
    return clauses


def _affirmed(pattern: re.Pattern[str], clause: str) -> bool:
    return any(not negated_predicate(clause, m.start()) for m in pattern.finditer(clause))


def analyze_current_turn(
    text: str, result: ProcessTurnResult | None = None
) -> CurrentStateAnalysis:
    # Model discourse can suggest a goal at runtime, but never becomes a durable directive.
    # The optional result argument remains compatible with existing hosts.
    analysis = CurrentStateAnalysis()
    clauses = eligible_clauses(text)
    accepted = "，".join(clauses)
    other_relation = any(
        OTHER_TARGET.search(c) and re.search(r"误会|争吵|吵架|原谅|和解", c) for c in clauses
    )
    analysis.topics = [topic for topic in TOPICS if topic in accepted]
    analysis.concrete_task = any(_affirmed(TASK, c) for c in direct_clauses(text))
    analysis.topic_switch = bool(re.search(r"换个话题|换一个话题|不聊这个|先聊别的", accepted))
    address = re.compile(
        r"(?:我希望你)?(?:以后|今后|一直|永远).{0,6}(?:别|不要).{0,10}(?:称呼|叫我).{0,40}"
    )
    for raw in re.split(r"[，,。；;！!？?\n]", text):
        if address.fullmatch(raw.strip()) and any(
            address.fullmatch(c) for c in eligible_clauses(raw)
        ):
            analysis.permanent_address_boundary = True
            analysis.rejected_address_text = raw.strip()
    for clause in clauses:
        today = "今天" in clause or "今日" in clause
        if _affirmed(LISTEN, clause):
            analysis.explicit_goal = ResponseGoal.LISTEN
        elif _affirmed(ADVICE, clause) and not re.search(
            r"(?:别|不要|不用|不想).{0,5}(?:建议|方案|办法)", clause
        ):
            analysis.explicit_goal = ResponseGoal.PROBLEM_SOLVE
        if re.search(r"(?:别|不要|不想).{0,4}(?:玩笑|调侃|吐槽我)", clause):
            analysis.observations.append(
                StateObservation(
                    kind=StateKind.STYLE, slot="humor", value="reduce", applies_today=today
                )
            )
        if _affirmed(HUMOR_REQUEST, clause):
            analysis.observations.append(
                StateObservation(
                    kind=StateKind.STYLE,
                    slot="humor",
                    value="normal",
                    status=StateStatus.ENDED,
                    reason="user_released_style_request",
                )
            )
        hold = re.search(r"(?:别|不要|不想)(?:再)?.{0,2}(?:提|聊|说这件)", clause)
        reopen = re.search(r"(?:继续|接着|重新|再).{0,3}(?:聊|说|讨论)", clause)
        targets = [topic for topic in TOPICS if topic in clause]
        if hold and not negated_predicate(clause, hold.start()):
            analysis.stop_reference = True
            hold_targets: list[str | None] = list(targets) or [None]
            for target in hold_targets:
                analysis.observations.append(
                    StateObservation(
                        kind=StateKind.STYLE,
                        slot=f"reference:{target}" if target else "reference",
                        value="hold",
                        topic=target,
                        reason="user_requested_no_reference_not_resolution",
                    )
                )
        elif reopen and not negated_predicate(clause, reopen.start()):
            analysis.reopened_topics.extend(targets)
            analysis.reopen_unscoped = not targets
        if not asserted_clause(clause):
            continue
        for name, pattern in CONDITIONS.items():
            match = pattern.search(clause)
            if not match:
                continue
            prefix = clause[: match.start()]
            body = LEADING_CONTEXT.sub("", clause)
            own = not OTHER_SUBJECT.search(body) and bool(
                re.match(r"我|很|好|太|有点|只是|没睡好|没有睡好|失眠|疲惫|疲倦", body)
                or re.search(r"让我|我感到|我觉得", prefix)
            )
            if not own or re.search(r"帮我|请|翻译|解释|想问|怎么写|把.+改", prefix):
                continue
            if OTHER_TARGET.search(prefix) and not re.search(r"(?:让|令|使)我", prefix):
                continue
            if re.match(r"(?:是什么意思|是什么|的英文)", clause[match.end() :]):
                continue
            negated = negated_predicate(clause, match.start())
            if negated and re.search(r"不是不|并非不|不能不", prefix):
                continue
            topic = next((topic for topic in analysis.topics if topic in clause), None)
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
        if not OTHER_TARGET.search(clause) and (
            not other_relation or re.search(r"你|咱俩", clause)
        ):
            companion = bool(re.search(r"你|我们|咱俩|咱们", clause))
            repair = REPAIR.search(clause)
            outcome = re.search(r"说开|解决|和解", clause)
            if (
                repair
                and not negated_predicate(clause, repair.start())
                and not re.search(r"愿意|想", clause[: repair.start()])
                and (outcome is None or not negated_predicate(clause, outcome.start()))
            ):
                analysis.repair = True
                analysis.repair_requires_context = not companion
                analysis.conflict = False
            elif companion:
                if (
                    repair
                    and "原谅你" in repair[0]
                    and negated_predicate(clause, repair.start())
                    and not re.search(r"不是不|并非不|不能不", clause)
                    and LEADING_CONTEXT.sub("", clause).startswith("我")
                ):
                    analysis.conflict, analysis.repair = True, False
                for complaint in COMPLAINT.finditer(clause):
                    if re.search(r"担心|害怕|希望|以为|猜测|你说", clause[: complaint.start()]):
                        continue
                    if negated_predicate(clause, complaint.start()):
                        if re.search(r"记错|弄错|误判|不是冲突", accepted):
                            analysis.conflict_correction = True
                        continue
                    if re.search(
                        r"(?:可以|随时|尽管|允许|请|别|不要).{0,6}$", clause[: complaint.start()]
                    ):
                        continue
                    analysis.conflict, analysis.repair = True, False
        for topic in (topic for topic in analysis.topics if topic in clause):
            outcome = re.search(
                re.escape(topic) + r"(?:已经|已|终于|总算|刚刚|刚|今天|顺利){0,3}"
                r"(结束|完成|通过|考完|面完|出结果|有结果)",
                clause,
            )
            if outcome and not negated_predicate(clause, outcome.start(1)):
                analysis.completed_topics.append(topic)
    if analysis.explicit_goal is not None:
        analysis.observations.append(
            StateObservation(
                kind=StateKind.COMMUNICATION,
                slot="need",
                value=analysis.explicit_goal.value,
                applies_today="今天" in accepted or "今日" in accepted,
            )
        )
    analysis.completed_topics = list(dict.fromkeys(analysis.completed_topics))
    return analysis
