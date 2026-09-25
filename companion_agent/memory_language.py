"""Bounded, literal memory intents for the offline companion."""

from __future__ import annotations

import re
from dataclasses import dataclass

from companion_agent.communication import CommunicationPreference, communication_preferences
from companion_memoryos.discourse import NONASSERTIVE, direct_clauses, negated_predicate

# Prefer missing a vague fact to inventing a lasting preference. No review question is needed.
UNCERTAIN = re.compile(
    r"假如|如果|可能|也许|开玩笑|据说|他说|她说|朋友说|以前|曾经|小时候|"
    r"小说|角色扮演|假装|[“”‘’\"'?？]|(?:吗|么)[。！!\s]*$"
)
SENSITIVE = re.compile(r"自杀|自残|药|诊断|密码|银行卡|身份证|性癖")
PREFERENCE = re.compile(
    r"(?:现在|目前)?我(?:平时|一直|比较|很|最|现在|其实|目前)*"
    r"(?:不再喜欢|不喜欢|不爱|讨厌|喜欢|爱喝|爱吃)"
    r"(?P<subject>[^，,；;。.!！?？]{1,36})"
)
FEEDBACK = re.compile(r"(?:以后|请|希望你)?(?:少说教|先听我讲|少给建议|回复短一点|多给建议)")
REMEMBER = re.compile(
    r"(?:这次|这轮|今天)?(?:请)?(?:帮我)?(?:记住|记一下|记下)(?:一下)?"
    r"[：:，,\s]*(?P<note>[^\n]{1,2000})$"
)
FAVORITE = re.compile(
    r"(?:现在|目前)?我(?:现在|目前|一直|其实|平时|比较|真的)*最(?:喜欢|爱)"
    r"(?:的(?P<category>[^，,；;。.!！?？是的]{0,16})是(?P<value>[^，,；;。.!！?？]{1,36})"
    r"|(?P<bare>[^，,；;。.!！?？]{1,36}))"
)


def memory_note(text: str) -> str | None:
    """A user request to keep a note, without a punctuation/password-like incantation."""
    match = REMEMBER.fullmatch(text.strip())
    if not match or re.search(r"[?？]|(?:了|过)?吗[。！!\s]*$", text):
        return None
    note = match["note"].strip(" ：:，,。！!\t")
    return note or None


def supported_literal(candidate: str, text: str) -> bool:
    """Accept whole or partial literal assertions, but not removed scope operators."""
    candidate = candidate.strip(" 。.!！\n")
    if not candidate or candidate not in text:
        return False
    clauses = direct_clauses(candidate)
    if not clauses or any(UNCERTAIN.search(clause) for clause in clauses):
        return False

    def normalized(value: str) -> str:
        return re.sub(r"[\s。.!！；;，,]", "", value)

    if normalized("".join(clauses)) != normalized(candidate):
        return False
    supported = [clause for clause in direct_clauses(text) if not UNCERTAIN.search(clause)]
    return all(any(clause in original for original in supported) for clause in clauses)


def shared_material(text: str) -> bool:
    """An explicitly framed shared quotation is an episode, not a self-report.

    Bare quotes and fictional instructions do not create personal preferences. Keep
    the whole original envelope so the quoted speaker and reality remain visible.
    """
    quote = re.search(r'“[^”]+”|「[^」]+」|『[^』]+』|"[^"\n]+"', text)
    if quote is None or SENSITIVE.search(text) or len(text) > 2000:
        return False
    frame = text[: quote.start()]
    if re.search(r"假如|如果|假设|可能|也许|不要|别|[?？]", frame):
        return False
    return bool(
        re.search(r"我(?:收到|读到|看到|分享|转发)|(?:发给我|给我发|给我看)", frame)
        and re.search(r"资料|文章|小说|人物|小传|台词|文字|消息|记录|片段", frame)
    )


@dataclass(frozen=True)
class LiteralMemory:
    content: str
    subject: str
    reflection: bool = False
    behavior: CommunicationPreference | None = None
    favorite: bool = False
    category: str | None = None
    value: str | None = None


def literal_memories(text: str) -> list[LiteralMemory]:
    if SENSITIVE.search(text):
        return []
    settings = communication_preferences(text)
    found = [LiteralMemory(s.original, "communication:" + s.dimension, True, s) for s in settings]
    # Conditions/quotations govern their own clauses; an old value in a correction
    # must not veto an independent, explicit statement of the new value.
    for clause in direct_clauses(memory_note(text) or text):
        clause = clause.strip()
        if any(item.content == clause for item in found):
            continue
        if UNCERTAIN.search(clause):
            continue
        favorite = FAVORITE.fullmatch(clause)
        if favorite:
            category = favorite["category"] or None
            value = favorite["value"] or favorite["bare"]
            if value.startswith("喝") and not category:
                category, value = "饮品", value[1:]
            category = {"饮料": "饮品", "喝的": "饮品"}.get(category or "", category)
            value = re.sub(r"[了呢]$", "", value).strip()
            if value and not re.search(r"但|不过|只是|还没|并不|不一定", value):
                found.append(
                    LiteralMemory(
                        clause,
                        f"favorite:{category}" if category else f"favorite-value:{value}",
                        favorite=True,
                        category=category,
                        value=value,
                    )
                )
            continue
        match = PREFERENCE.fullmatch(clause)
        if match:
            subject = re.sub(r"[了呢]$", "", match["subject"]).strip()
            subject = re.sub(r"^(?:喝|吃)", "", subject)
            if subject and not re.search(r"但|不过|只是|还没|并不|不一定", subject):
                found.append(LiteralMemory(clause, subject))
        elif FEEDBACK.fullmatch(clause) and "先听我讲" not in clause:
            subject = "communication:length" if "回复短" in clause else "communication:advice"
            found.append(LiteralMemory(clause, subject, reflection=True))
    # Keep a combined communication directive as one auditable original statement.
    if (
        len(found) > 1
        and all(item.reflection for item in found)
        and len({item.subject for item in found}) == 1
    ):
        return [LiteralMemory(text.strip("。！!\n "), found[0].subject, True, found[-1].behavior)]
    return found


def forget_target(text: str) -> str | None:
    # Resolve an explicitly moved object's old location inside the same direct
    # sentence. Do not infer the object from a guessed recent topic.
    clauses = direct_clauses(text)
    for index, clause in enumerate(clauses):
        if re.fullmatch(
            r"(?:之前|以前|原来)(?:跟你说的|告诉你的|说的)?(?:那个|的|旧)?位置(?:请)?(?:忘掉|忘记|删掉)",
            clause,
        ):
            for antecedent in reversed(clauses[:index]):
                moved = re.fullmatch(
                    r"(?:我的)?(?P<item>[\w]{2,24}?)(?:已经|刚刚)?(?:挪了|换了|搬了|移了)(?:个)?(?:地方|位置)",
                    antecedent,
                )
                if moved and not UNCERTAIN.search(antecedent):
                    return "@location:" + moved["item"]
    for clause in clauses:
        # Scope belongs to this direct command, not to unrelated sentences in
        # the same message. An old fact is a legitimate explicit deletion target.
        if NONASSERTIVE.search(clause) or re.search(
            r"开玩笑|据说|小说|假装|\[引用\]|[?？]|(?:吗|么)$", clause
        ):
            continue
        command = clause.rsplit("：", 1)[-1].rsplit(":", 1)[-1].strip()
        command = re.sub(r"^(?:另外|还有|对了|顺便)(?:请)?", "请", command)
        prefix = r"(?:请|麻烦你)?(?:帮我)?"
        match = re.fullmatch(prefix + r"(?:忘掉|忘记|别再记着|别记住)(.{1,100})", command)
        if not match:
            match = re.fullmatch(prefix + r"把(.{1,100}?)(忘掉|忘记|删掉)(?:吧)?", command)
            if match and negated_predicate(command, match.start(2)):
                continue
        if not match:
            continue
        target = match[1].strip(" ：:")
        if target in {"这件事", "这条记忆", "刚才那件事", "刚才说的", "这个"}:
            return "@recent"
        target = re.sub(r"^关于", "", target)
        target = re.sub(
            r"(?:这件事|这件事情|的事情|的事|的记忆|的喜好|的偏好|喜好|偏好)$", "", target
        )
        location = re.fullmatch(r"(.{2,40}?)(?:放(?:在)?哪里|放哪儿|的(?:旧)?位置)", target)
        if location:
            return "@location:" + location[1]
        return target.strip() or None
    return None
