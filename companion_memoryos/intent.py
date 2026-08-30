from __future__ import annotations

import re

_EXPLICIT_MEMORY_DIRECTIVE = re.compile(
    r"^(?:请)?(?:帮我)?(?:记住|记一下|记得)|"
    r"^(?:以后|下次)(?:请)?(?:叫我|不要|别|记得)|"
    r"^(?:不要再|别再|请叫我)|"
    r"^我希望你以后"
)


def has_explicit_memory_directive(text: str) -> bool:
    """Recognize direct user instructions without turning ordinary narration into consent."""

    return _EXPLICIT_MEMORY_DIRECTIVE.search(text.strip()) is not None
