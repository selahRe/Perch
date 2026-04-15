from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .models import ClusterClassification, MonitoringSettings, StatusClassification, UserClusterLabel
from .settings_store import SettingsStore
from .storage import MetricsRepository
from .user_cluster import UserClusterEngine
from .work_hours import STRONG_WORK_APPS, infer_is_work_hour, minutes_to_hhmm, parse_time_to_minutes


class StatusClassifier:
    DEFAULT_TRAIN_WINDOW_DAYS = 7
    EXTENDED_TRAIN_WINDOW_DAYS = 14
    MIN_TRAIN_SAMPLES = 2000
    WORK_WINDOW_UPDATE_DAYS = 3

    def __init__(
        self,
        settings_store: SettingsStore,
        repository: MetricsRepository | None = None,
        cluster_engine: UserClusterEngine | None = None,
    ) -> None:
        self.settings_store = settings_store
        self.repository = repository
        self.cluster_engine = cluster_engine or UserClusterEngine()

    def classify(self, kpm_value: int, app_name: str | None = None) -> StatusClassification:
        settings = self.settings_store.load()
        effective_focus_threshold = self._effective_focus_threshold(settings, app_name)
        idle_limit = settings.kpm_thresholds.get("idle", settings.idle_limit)

        if kpm_value < idle_limit:
            confidence = min(1.0, (idle_limit - kpm_value) / max(1, idle_limit))
            return StatusClassification(label="Idle", confidence=round(confidence, 3))

        if kpm_value >= effective_focus_threshold:
            confidence = min(
                1.0,
                (kpm_value - effective_focus_threshold + 1) / max(1, effective_focus_threshold),
            )
            return StatusClassification(label="Focused", confidence=round(confidence, 3))

        relaxed_band = max(1, effective_focus_threshold - idle_limit)
        midpoint = idle_limit + (relaxed_band / 2)
        distance = abs(kpm_value - midpoint)
        confidence = max(0.5, 1.0 - (distance / relaxed_band))
        return StatusClassification(label="Relaxed", confidence=round(confidence, 3))

    def classify_with_cluster(
        self,
        kpm_value: int,
        app_name: str | None = None,
        now: datetime | None = None,
    ) -> ClusterClassification:
        now = now or datetime.now(timezone.utc)
        settings = self._refresh_work_window_if_needed(now=now)
        history_rows = self._load_recent_history(now)
        self.cluster_engine.ensure_model(history_rows=history_rows, now=now)
        is_work_hour = infer_is_work_hour(
            timestamp=now,
            app_name=app_name,
            kpm_value=kpm_value,
            work_time_start=settings.work_time_start,
            work_time_end=settings.work_time_end,
        )
        user_cluster, cluster_confidence = self.cluster_engine.predict(
            kpm_value=kpm_value,
            app_name=app_name,
            is_work_hour=is_work_hour,
        )

        status = self._cluster_to_status(user_cluster=user_cluster, confidence=cluster_confidence)
        return ClusterClassification(status=status, user_cluster=user_cluster)

    def _effective_focus_threshold(self, settings: MonitoringSettings, app_name: str | None) -> int:
        focus_threshold = settings.kpm_thresholds.get("focus", settings.focus_threshold)
        minimum_focus = settings.kpm_thresholds.get("idle", settings.idle_limit) + 1

        if not app_name:
            return max(minimum_focus, focus_threshold)

        app_name_lower = app_name.lower()
        for candidate in settings.developer_apps:
            if candidate.lower() in app_name_lower:
                return max(minimum_focus, focus_threshold - settings.developer_focus_delta)

        return max(minimum_focus, focus_threshold)

    def _load_recent_history(self, now: datetime) -> list[dict]:
        if self.repository is None:
            return []
        seven_days_ago = now - timedelta(days=self.DEFAULT_TRAIN_WINDOW_DAYS)
        rows = self.repository.load_history(since_timestamp=seven_days_ago)
        if len(rows) >= self.MIN_TRAIN_SAMPLES:
            return self._normalize_history_rows(rows)

        fourteen_days_ago = now - timedelta(days=self.EXTENDED_TRAIN_WINDOW_DAYS)
        extended_rows = self.repository.load_history(since_timestamp=fourteen_days_ago)
        return self._normalize_history_rows(extended_rows)

    def _normalize_history_rows(self, rows) -> list[dict]:
        settings = self.settings_store.load()
        normalized: list[dict] = []
        for row in rows:
            item = dict(row)
            if "is_work_hour" not in item:
                timestamp = datetime.fromisoformat(item["timestamp"])
                item["is_work_hour"] = infer_is_work_hour(
                    timestamp=timestamp,
                    app_name=item.get("app_name"),
                    kpm_value=int(item.get("kpm_value", 0)),
                    work_time_start=settings.work_time_start,
                    work_time_end=settings.work_time_end,
                )
            else:
                item["is_work_hour"] = bool(item["is_work_hour"])
            normalized.append(item)
        return normalized

    def _refresh_work_window_if_needed(self, now: datetime) -> MonitoringSettings:
        settings = self.settings_store.load()
        if self.repository is None:
            return settings
        if not settings.auto_work_window_enabled:
            return settings

        if settings.last_work_window_update_at is not None:
            elapsed = now - settings.last_work_window_update_at
            if elapsed < timedelta(days=self.WORK_WINDOW_UPDATE_DAYS):
                return settings

        rows = self.repository.load_history(since_timestamp=now - timedelta(days=self.DEFAULT_TRAIN_WINDOW_DAYS))
        if len(rows) < self.MIN_TRAIN_SAMPLES:
            return settings

        active_minutes: list[int] = []
        for row in rows:
            kpm_value = int(row["kpm_value"])
            app_name = (row["app_name"] or "").lower()
            active_signal = kpm_value >= 25 or any(token in app_name for token in STRONG_WORK_APPS)
            if not active_signal:
                continue
            timestamp = datetime.fromisoformat(row["timestamp"])
            local = timestamp.astimezone()
            active_minutes.append(local.hour * 60 + local.minute)

        if len(active_minutes) < 300:
            return settings

        estimated_start = self._percentile(active_minutes, 0.15)
        estimated_end = self._percentile(active_minutes, 0.85)
        if estimated_end <= estimated_start:
            return settings

        current_start = parse_time_to_minutes(settings.work_time_start, fallback_minutes=(13 * 60 + 30))
        current_end = parse_time_to_minutes(settings.work_time_end, fallback_minutes=(18 * 60))
        alpha = max(0.0, min(1.0, settings.work_window_ema_alpha))

        smoothed_start = int(round(((1.0 - alpha) * current_start) + (alpha * estimated_start)))
        smoothed_end = int(round(((1.0 - alpha) * current_end) + (alpha * estimated_end)))
        if smoothed_end <= smoothed_start:
            return settings

        settings.work_time_start = minutes_to_hhmm(smoothed_start)
        settings.work_time_end = minutes_to_hhmm(smoothed_end)
        settings.last_work_window_update_at = now
        self.settings_store.save(settings)
        return settings

    def _percentile(self, values: list[int], ratio: float) -> int:
        ordered = sorted(values)
        if not ordered:
            return 0
        idx = int(round((len(ordered) - 1) * ratio))
        idx = max(0, min(len(ordered) - 1, idx))
        return ordered[idx]

    def _cluster_to_status(
        self,
        user_cluster: UserClusterLabel,
        confidence: float,
    ) -> StatusClassification:
        if user_cluster == "deep_work":
            return StatusClassification(label="Focused", confidence=confidence)
        if user_cluster == "low_energy":
            return StatusClassification(label="Relaxed", confidence=confidence)
        return StatusClassification(label="Idle", confidence=confidence)
