from __future__ import annotations

from datetime import UTC, datetime

from companion_memoryos.temporal import extract_temporal_hint


def test_invalid_explicit_dates_degrade_without_raising() -> None:
    as_of = datetime(2026, 8, 30, tzinfo=UTC)

    chinese = extract_temporal_hint("2026年13月40日发生的事", as_of)
    iso = extract_temporal_hint("2026-02-31发生的事", as_of)

    assert chinese.has_window is False
    assert iso.has_window is False
