from __future__ import annotations

from datetime import UTC, datetime, timedelta

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


@pytest.mark.parametrize("query", ["5月1号聊了什么", "在05月01日发生了什么", "2026年5月1号"])
def test_chinese_month_day_uses_local_calendar_year(query: str) -> None:
    hint = extract_temporal_hint(query, datetime(2026, 9, 29, tzinfo=UTC), "Asia/Shanghai")
    assert hint.start == datetime(2026, 4, 30, 16, tzinfo=UTC)
    assert hint.end == hint.start + timedelta(days=1)


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("去年12月31号", datetime(2025, 12, 31, tzinfo=UTC)),
        ("明年1月1日", datetime(2027, 1, 1, tzinfo=UTC)),
        ("12月31日", datetime(2026, 12, 31, tzinfo=UTC)),
    ],
)
def test_bare_month_day_does_not_guess_a_previous_year(query: str, expected: datetime) -> None:
    assert extract_temporal_hint(query, datetime(2026, 1, 2, tzinfo=UTC)).start == expected


@pytest.mark.parametrize("query", ["2月30号", "13月1日", "4月27日和5月2日", "2026-05-01与5月2号"])
def test_invalid_or_multiple_month_days_do_not_narrow_to_one_day(query: str) -> None:
    assert not extract_temporal_hint(query, datetime(2026, 9, 29, tzinfo=UTC)).has_window


def test_bare_event_day_does_not_backdate_future_plans() -> None:
    now = datetime(2026, 9, 29, tzinfo=UTC)
    assert literal_event_day("10月1号要去看展", now) is None
    assert literal_event_day("9月28号去了图书馆", now).start == datetime(2026, 9, 28, tzinfo=UTC)
