"""Advisory expression observations from dialogue already admitted to this request.

No extra retrieval, persistent preference, model call, or response rewriting is used.
Only closed labels and native dialogue indexes leave the comparison step; historical
text is never copied into system rules. These cues are not a language-quality score.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from companion_agent.context.composer import ChatMessage


DIALOGUE_FLOW_RULES = """在用户选定的人物设定内接续当前来回，身份、性格和明确的相处偏好保持一致。
每次回应眼前的新信息、已经回答的问题或正在展开的事情；用户换了话题就跟上新话题。
先理解这轮具体说了什么，再决定怎样回应，不沿用固定的“复述感受、安慰、追问”顺序。
关心、倾听、解释和轻松互动按语境自然结合；回应目标只是提示，不是持续不变的说话模式。
近期表达观察仅提示可见旧回复中可能重复的开头、结尾或整段表达；结合原对话判断，
用当前细节接话，不只是给旧套话换同义词。无需为了变化强行转话题、编造情绪或制造分歧。
用户明确要求的口头禅、固定格式、原文复述、再次确认和事实准确性优先于表达变化。
篇幅和提问由当前需要决定，不按轮次切换套路；自然说完即可，不必为延长聊天补一个问题。
相关且允许使用的记忆可以帮助接话，无关旧情绪和示例中的虚构经历不能代替当前内容。
这些是接话建议，不新增人物性格；与用户设定或当前明确要求有出入时，以用户为准。"""


def _comparable(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKC", text).casefold() if c.isalnum())


def expression_patterns(dialogue: list[ChatMessage]) -> list[dict[str, Any]]:
    """Describe repetitions in at most six visible assistant messages, without text."""
    recent = [(i, m.content) for i, m in enumerate(dialogue) if m.role == "assistant"][-6:]
    groups: dict[str, dict[str, list[int]]] = {
        kind: defaultdict(list) for kind in ("same_reply", "same_opening", "same_closing")
    }
    comparable: list[tuple[int, str]] = []
    for index, text in recent:
        # Repeated code and quoted blocks often need literal fidelity, not variation.
        if "```" in text or any(line.lstrip().startswith(">") for line in text.splitlines()):
            continue
        clauses = [part for part in re.split(r"[。！？!?；;，,\n]+", text) if _comparable(part)]
        whole = _comparable(text)
        if not clauses or len(whole) < 8:
            continue
        groups["same_reply"][whole].append(index)
        for kind, part in (("same_opening", clauses[0]), ("same_closing", clauses[-1])):
            value = _comparable(part)
            if len(value) >= 5:
                groups[kind][value].append(index)
        if 24 <= len(whole) <= 600:
            comparable.append((index, whole))
    cues = [
        {"kind": kind, "turn_indexes": indexes}
        for kind, values in groups.items()
        for indexes in values.values()
        if len(indexes) > 1
    ]
    for offset, (index, text) in enumerate(comparable):
        for other_index, other in comparable[offset + 1 :]:
            if text != other and SequenceMatcher(None, text, other, autojunk=False).ratio() >= 0.86:
                cues.append({"kind": "similar_reply", "turn_indexes": [index, other_index]})
    # Keep the context bounded; the model still receives the admitted original dialogue.
    return cues[:8]
