from __future__ import annotations

from datetime import UTC, datetime

import pytest

from companion_memoryos.temporal import extract_temporal_hint, literal_event_day


def test_invalid_explicit_dates_degrade_without_raising() -> None:
    as_of = datetime(2026, 8, 30, tzinfo=UTC)

    chinese = extract_temporal_hint("2026年13月40日发生的事", as_of)
    iso = extract_temporal_hint("2026-02-31发生的事", as_of)

    assert chinese.has_window is False
    assert iso.has_window is False


def test_event_day_uses_source_timezone_and_keeps_day_precision() -> None:
    observed = datetime(2026, 9, 23, 17, tzinfo=UTC)  # September 24 in Shanghai.
    day = literal_event_day("我昨天买了个水杯。", observed, "Asia/Shanghai")
    assert day is not None
    assert day.start == datetime(2026, 9, 22, 16, tzinfo=UTC)
    assert day.end == datetime(2026, 9, 23, 16, tzinfo=UTC)


@pytest.mark.parametrize(
    "source",
    [
        "昨天买的水杯今天打碎了。",
        "我在2026年9月12日参加读书会，在2026年9月19日上手作课。",
        "2026年10月1日准备去看展。",
        "2026年13月40日去了书店。",
        "我买了个水杯。",
    ],
)
def test_event_day_does_not_invent_ambiguous_or_future_dates(source: str) -> None:
    assert literal_event_day(source, datetime(2026, 9, 24, tzinfo=UTC)) is None
