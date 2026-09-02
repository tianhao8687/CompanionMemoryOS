from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from companion_memoryos.constants import (
    CALENDAR_FIRST_DAY,
    CALENDAR_FIRST_MONTH,
    MONTHS_PER_YEAR,
    RELATIVE_DAY_BEFORE_YESTERDAY_DAYS,
    RELATIVE_YESTERDAY_DAYS,
)

_CHINESE_DATE = re.compile(r"(?P<year>\d{4})年(?P<month>\d{1,2})月(?P<day>\d{1,2})日?")
_ISO_DATE = re.compile(r"(?P<date>\d{4}-\d{1,2}-\d{1,2})")


@dataclass(frozen=True)
class TemporalHint:
    start: datetime | None = None
    end: datetime | None = None
    prefer_recent: bool = False

    @property
    def has_window(self) -> bool:
        return self.start is not None or self.end is not None


def extract_temporal_hint(
    query: str, as_of: datetime, calendar_timezone: str = "UTC"
) -> TemporalHint:
    if as_of.tzinfo is None:
        raise ValueError("as_of must include a timezone")
    local = as_of.astimezone(ZoneInfo(calendar_timezone))
    hint = _extract_local_temporal_hint(query, local)
    return TemporalHint(
        start=hint.start.astimezone(UTC) if hint.start is not None else None,
        end=hint.end.astimezone(UTC) if hint.end is not None else None,
        prefer_recent=hint.prefer_recent,
    )


def _extract_local_temporal_hint(query: str, as_of: datetime) -> TemporalHint:
    explicit = _explicit_date(query, as_of)
    if explicit is not None:
        return explicit

    today = _day_start(as_of)
    if "前天" in query:
        start = today - timedelta(days=RELATIVE_DAY_BEFORE_YESTERDAY_DAYS)
        return TemporalHint(start, start + timedelta(days=RELATIVE_YESTERDAY_DAYS))
    if "昨天" in query or "昨日" in query:
        start = today - timedelta(days=RELATIVE_YESTERDAY_DAYS)
        return TemporalHint(start, today)
    if "今天" in query or "今日" in query:
        return TemporalHint(today, today + timedelta(days=RELATIVE_YESTERDAY_DAYS))

    week_start = today - timedelta(days=today.weekday())
    if "上周" in query or "上星期" in query:
        start = week_start - timedelta(weeks=RELATIVE_YESTERDAY_DAYS)
        return TemporalHint(start, week_start)
    if "本周" in query or "这周" in query or "这个星期" in query:
        return TemporalHint(
            week_start,
            week_start + timedelta(weeks=RELATIVE_YESTERDAY_DAYS),
        )

    month_start = today.replace(day=CALENDAR_FIRST_DAY)
    if "上个月" in query or "上月" in query:
        previous_month_end = month_start - timedelta(days=RELATIVE_YESTERDAY_DAYS)
        start = previous_month_end.replace(day=CALENDAR_FIRST_DAY)
        return TemporalHint(start, month_start)
    if "本月" in query or "这个月" in query:
        return TemporalHint(month_start, _next_month(month_start))

    year_start = today.replace(month=CALENDAR_FIRST_MONTH, day=CALENDAR_FIRST_DAY)
    if "去年" in query:
        start = year_start.replace(year=year_start.year - RELATIVE_YESTERDAY_DAYS)
        return TemporalHint(start, year_start)
    if "今年" in query:
        return TemporalHint(
            year_start,
            year_start.replace(year=year_start.year + RELATIVE_YESTERDAY_DAYS),
        )

    prefer_recent = any(marker in query for marker in ("上次", "最近", "刚才", "前几天"))
    return TemporalHint(prefer_recent=prefer_recent)


def temporal_similarity(event_at: datetime, hint: TemporalHint) -> float:
    if hint.start is not None and event_at < hint.start:
        return 0.0
    if hint.end is not None and event_at >= hint.end:
        return 0.0
    if hint.has_window:
        return 1.0
    return 0.0


def _explicit_date(query: str, as_of: datetime) -> TemporalHint | None:
    chinese = _CHINESE_DATE.search(query)
    if chinese is not None:
        try:
            start = as_of.replace(
                year=int(chinese.group("year")),
                month=int(chinese.group("month")),
                day=int(chinese.group("day")),
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            )
        except ValueError:
            return None
        return TemporalHint(start, start + timedelta(days=RELATIVE_YESTERDAY_DAYS))
    iso = _ISO_DATE.search(query)
    if iso is None:
        return None
    try:
        parsed = datetime.fromisoformat(iso.group("date")).replace(tzinfo=as_of.tzinfo)
    except ValueError:
        return None
    return TemporalHint(parsed, parsed + timedelta(days=RELATIVE_YESTERDAY_DAYS))


def _day_start(value: datetime) -> datetime:
    return value.replace(hour=0, minute=0, second=0, microsecond=0)


def _next_month(value: datetime) -> datetime:
    if value.month == MONTHS_PER_YEAR:
        return value.replace(
            year=value.year + RELATIVE_YESTERDAY_DAYS,
            month=CALENDAR_FIRST_MONTH,
        )
    return value.replace(month=value.month + RELATIVE_YESTERDAY_DAYS)
