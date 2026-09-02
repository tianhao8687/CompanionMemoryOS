from __future__ import annotations

from typing import Protocol

import tiktoken


class TokenCounter(Protocol):
    """Host-supplied text budget counter; no provider dependency is required."""

    def count(self, text: str) -> int: ...


class TiktokenTokenCounter:
    def __init__(self, encoding_name: str) -> None:
        self.encoding_name = encoding_name
        self._encoding = tiktoken.get_encoding(encoding_name)

    def count(self, text: str) -> int:
        return len(self._encoding.encode(text))
