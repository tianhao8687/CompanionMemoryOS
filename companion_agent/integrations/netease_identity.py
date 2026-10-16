"""Match the metadata NetEase actually publishes, including primary-artist SMTC."""

from __future__ import annotations

import re
import unicodedata


def normalized(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def artists_match(reported: str, artists: list[str], *, primary_only: bool = False) -> bool:
    expected = {normalized(value) for value in artists if value.strip()}
    actual = normalized(reported)
    if not actual or not expected:
        return False
    if actual == normalized("/".join(artists)):
        return True
    if primary_only and actual in expected:
        return True
    supplied = {
        normalized(value) for value in re.split(r"\s*[/、,，;；]\s*", reported) if value.strip()
    }
    return bool(supplied) and (supplied <= expected if primary_only else supplied == expected)


def window_matches(window_title: str, title: str, artist: str) -> bool:
    prefix = normalized(title) + " - "
    value = normalized(window_title)
    return bool(
        title.strip()
        and value.startswith(prefix)
        and artists_match(artist, value[len(prefix) :].split("/"), primary_only=True)
    )
