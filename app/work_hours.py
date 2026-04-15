from __future__ import annotations

from datetime import datetime


STRONG_WORK_APPS = ("code", "cursor", "pycharm", "intellij", "webstorm", "word", "zoom")


def _minute_of_day(value: datetime) -> int:
    local = value.astimezone()
    return local.hour * 60 + local.minute


def parse_time_to_minutes(value: str, fallback_minutes: int) -> int:
    try:
        hour_text, minute_text = value.split(":", maxsplit=1)
        hour = int(hour_text)
        minute = int(minute_text)
    except (ValueError, AttributeError):
        return fallback_minutes
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return fallback_minutes
    return hour * 60 + minute


def minutes_to_hhmm(value: int) -> str:
    normalized = max(0, min(23 * 60 + 59, value))
    return f"{normalized // 60:02d}:{normalized % 60:02d}"


def infer_is_work_hour(
    timestamp: datetime,
    app_name: str | None,
    kpm_value: int,
    work_time_start: str = "13:30",
    work_time_end: str = "18:00",
    flex_minutes: int = 120,
) -> bool:
    work_start_minutes = parse_time_to_minutes(work_time_start, fallback_minutes=(13 * 60 + 30))
    work_end_minutes = parse_time_to_minutes(work_time_end, fallback_minutes=(18 * 60))
    minute = _minute_of_day(timestamp)
    weekday = timestamp.astimezone().weekday()
    app = (app_name or "").strip().lower()

    # Weekday time window with flexible lead/lag to absorb day-by-day schedule shifts.
    in_flexible_window = (
        weekday < 5 and (work_start_minutes - flex_minutes) <= minute <= (work_end_minutes + flex_minutes)
    )

    # Some apps are strong work indicators even with low KPM, e.g. Zoom meetings.
    strong_work_app = any(keyword in app for keyword in STRONG_WORK_APPS)

    # Typing activity itself can indicate active work when app metadata is weak.
    activity_signal = kpm_value >= 25

    return in_flexible_window or strong_work_app or activity_signal
