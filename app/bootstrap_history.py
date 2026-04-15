from __future__ import annotations

from datetime import datetime, timedelta, timezone
import random

from .storage import MetricsRepository


class WeeklyHistoryBootstrapper:
    def __init__(self, seed: int = 20260415) -> None:
        self._rand = random.Random(seed)
        self._minimum_week_samples = 7 * 24 * 60

    def ensure_seeded(self, repository: MetricsRepository, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        week_ago = now - timedelta(days=7)
        existing = repository.count_history(since_timestamp=week_ago)
        if existing >= self._minimum_week_samples:
            return

        start = (now - timedelta(days=7)).replace(second=0, microsecond=0)
        for minute_offset in range(self._minimum_week_samples):
            timestamp = start + timedelta(minutes=minute_offset)
            app_name, kpm = self._simulate_minute(timestamp=timestamp)
            status_label = self._status_from_kpm(kpm_value=kpm)
            repository.save_minute_record(
                timestamp=timestamp,
                kpm_value=kpm,
                status_label=status_label,
                app_name=app_name,
            )

    def _simulate_minute(self, timestamp: datetime) -> tuple[str, int]:
        weekday = timestamp.weekday()
        minute_of_day = timestamp.hour * 60 + timestamp.minute
        in_morning_research = 11 * 60 <= minute_of_day < 12 * 60
        in_lunch_video = 12 * 60 <= minute_of_day < 13 * 60
        in_work_window = 13 * 60 + 30 <= minute_of_day <= 18 * 60

        monday_class = weekday == 0 and (16 * 60 + 30) <= minute_of_day <= (17 * 60 + 55)
        wednesday_class = weekday == 2 and (13 * 60 + 40) <= minute_of_day <= (17 * 60 + 55)
        in_class = monday_class or wednesday_class

        if in_work_window and not in_class:
            return self._simulate_work_minute()
        if in_class:
            return self._simulate_class_minute()
        if in_morning_research:
            return ("Safari", self._clamped_gauss(mean=16, std=6))
        if in_lunch_video:
            return ("Safari", self._clamped_gauss(mean=4, std=3))
        return ("Offline", self._clamped_gauss(mean=1, std=1))

    def _simulate_work_minute(self) -> tuple[str, int]:
        roll = self._rand.random()
        if roll < 0.45:
            return ("Code", self._clamped_gauss(mean=118, std=18))
        if roll < 0.75:
            return ("Safari", self._clamped_gauss(mean=95, std=20))
        if roll < 0.88:
            return ("Word", self._clamped_gauss(mean=55, std=14))
        if roll < 0.94:
            return ("Zoom", self._clamped_gauss(mean=22, std=9))
        return ("WeChat", self._clamped_gauss(mean=28, std=12))

    def _simulate_class_minute(self) -> tuple[str, int]:
        roll = self._rand.random()
        if roll < 0.72:
            return ("Zoom", self._clamped_gauss(mean=18, std=7))
        if roll < 0.90:
            return ("WeChat", self._clamped_gauss(mean=20, std=8))
        return ("Safari", self._clamped_gauss(mean=14, std=6))

    def _status_from_kpm(self, kpm_value: int) -> str:
        if kpm_value < 5:
            return "Idle"
        if kpm_value >= 60:
            return "Focused"
        return "Relaxed"

    def _clamped_gauss(self, mean: float, std: float) -> int:
        return max(0, int(round(self._rand.gauss(mean, std))))
