"""Small, source-aware current task cues shared by context and state selection."""

from __future__ import annotations

import re

from companion_memoryos.discourse import NONASSERTIVE, direct_clauses, negated_predicate

CHOICE_REQUEST = re.compile(
    r"^(?:(?:那|好|行|还是|现在|今天|今晚|就|先)\s*)*"
    r"(?:帮我|替我|给我|你|请(?:你)?|麻烦(?:你)?)"
    r"(?:(?:来|直接|就|先|再|帮我|替我|给我|随便|重新|干脆)\s*)*"
    r"(?:(?:从|在)[^，。！？?!]{1,40}?(?:里|中)\s*)?"
    r"(?:给[^，。！？?!]{1,12}?)?"
    r"(?P<action>挑选|选择|推荐|挑|选)(?![了过的]|(?:好|出)[了的])"
)


def is_choice_request(text: str) -> bool:
    """A delegated choice is a task, never consent to buy, send, or schedule it.

    Match a current addressed request, not a past choice, quote, condition or
    prohibition. Unmatched wording remains available verbatim to the main model.
    The original request supplies quantity and constraints; no output quota is set.
    """
    return any(
        not NONASSERTIVE.search(clause)
        and (match := CHOICE_REQUEST.match(clause))
        and not negated_predicate(clause, match.start("action"))
        for clause in direct_clauses(text)
    )
