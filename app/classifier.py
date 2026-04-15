from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .models import ClusterClassification, MonitoringSettings, StatusClassification, UserClusterLabel
from .settings_store import SettingsStore
from .storage import MetricsRepository
from .user_cluster import UserClusterEngine


class StatusClassifier:
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
        history_rows = self._load_recent_history(now)
        self.cluster_engine.ensure_model(history_rows=history_rows, now=now)
        user_cluster, cluster_confidence = self.cluster_engine.predict(
            kpm_value=kpm_value,
            app_name=app_name,
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
        rows = self.repository.load_history(since_timestamp=now - timedelta(days=7))
        return [dict(row) for row in rows]

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
