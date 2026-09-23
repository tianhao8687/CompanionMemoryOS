"""Bounded, literal memory intents for the offline companion."""

from __future__ import annotations

import re
from dataclasses import dataclass

# Prefer missing a vague fact to inventing a lasting preference. No review question is needed.
UNCERTAIN = re.compile(
    r"假如|如果|可能|也许|开玩笑|据说|他说|她说|朋友说|以前|曾经|小时候|"
    r"小说|角色扮演|假装|[“”‘’\"'?？]|(?:吗|么)[。！!\s]*$"
)
SENSITIVE = re.compile(r"自杀|自残|药|诊断|密码|银行卡|身份证|性癖")
PREFERENCE = re.compile(
    r"我(?:平时|一直|比较|很|最|现在|其实|目前)?"
    r"(?:不再喜欢|不喜欢|不爱|讨厌|喜欢|爱喝|爱吃)"
    r"(?P<subject>[^，,；;。.!！?？]{1,36})"
)
FEEDBACK = re.compile(r"(?:以后|请|希望你)?(?:少说教|先听我讲|少给建议|回复短一点|多给建议)")


@dataclass(frozen=True)
class LiteralMemory:
    content: str
    subject: str
    reflection: bool = False


def literal_memories(text: str) -> list[LiteralMemory]:
    if UNCERTAIN.search(text) or SENSITIVE.search(text):
        return []
    found = []
    for clause in re.split(r"[。！!\n，,；;]", text):
        clause = clause.strip()
        match = PREFERENCE.fullmatch(clause)
        if match:
            subject = re.sub(r"[了呢]$", "", match["subject"]).strip()
            subject = re.sub(r"^(?:喝|吃)", "", subject)
            if subject and not re.search(r"但|不过|只是|还没|并不|不一定", subject):
                found.append(LiteralMemory(clause, subject))
        elif FEEDBACK.fullmatch(clause):
            subject = "communication:length" if "回复短" in clause else "communication:advice"
            found.append(LiteralMemory(clause, subject, reflection=True))
    # Keep a combined communication directive as one auditable original statement.
    if (
        len(found) > 1
        and all(item.reflection for item in found)
        and len({item.subject for item in found}) == 1
    ):
        return [LiteralMemory(text.strip("。！!\n "), found[0].subject, True)]
    return found


def forget_target(text: str) -> str | None:
    if UNCERTAIN.search(text):
        return None
    text = text.strip("。！!\n ")
    match = re.fullmatch(r"(?:请)?(?:帮我)?(?:忘掉|忘记|别再记着|别记住)(.{1,100})", text)
    if not match:
        match = re.fullmatch(r"(?:请)?把(.{1,100}?)(?:忘掉|忘记|删掉)", text)
    if not match:
        return None
    target = match[1].strip(" ：:")
    if target in {"这件事", "这条记忆", "刚才那件事", "刚才说的", "这个"}:
        return "@recent"
    target = re.sub(r"^关于", "", target)
    target = re.sub(r"(?:这件事|这件事情|的事情|的事|的记忆|的喜好|的偏好|喜好|偏好)$", "", target)
    return target.strip() or None
