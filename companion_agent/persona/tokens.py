from companion_memoryos.tokens import TiktokenTokenCounter, TokenCounter

DEFAULT_MAX_PERSONA_TOKENS = 1200


class PersonaBudgetError(ValueError):
    """The mandatory persona cannot fit; never silently discard its constraints."""


def default_token_counter() -> TokenCounter:
    return TiktokenTokenCounter("cl100k_base")
