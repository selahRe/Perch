from __future__ import annotations

from .models import MonitoringSettings, StatusClassification
from .settings_store import SettingsStore


class StatusClassifier:
    def __init__(self, settings_store: SettingsStore) -> None:
        self.settings_store = settings_store

    def classify(self, kpm_value: int, app_name: str | None = None) -> StatusClassification:
        settings = self.settings_store.load()
        effective_focus_threshold = self._effective_focus_threshold(settings, app_name)

        if kpm_value < settings.idle_limit:
            confidence = min(1.0, (settings.idle_limit - kpm_value) / max(1, settings.idle_limit))
            return StatusClassification(label="Idle", confidence=round(confidence, 3))

        if kpm_value >= effective_focus_threshold:
            confidence = min(1.0, (kpm_value - effective_focus_threshold + 1) / max(1, effective_focus_threshold))
            return StatusClassification(label="Focused", confidence=round(confidence, 3))

        relaxed_band = max(1, effective_focus_threshold - settings.idle_limit)
        midpoint = settings.idle_limit + (relaxed_band / 2)
        distance = abs(kpm_value - midpoint)
        confidence = max(0.5, 1.0 - (distance / relaxed_band))
        return StatusClassification(label="Relaxed", confidence=round(confidence, 3))

    def _effective_focus_threshold(self, settings: MonitoringSettings, app_name: str | None) -> int:
        if not app_name:
            return max(settings.idle_limit + 1, settings.focus_threshold)

        app_name_lower = app_name.lower()
        for candidate in settings.developer_apps:
            if candidate.lower() in app_name_lower:
                return max(settings.idle_limit + 1, settings.focus_threshold - settings.developer_focus_delta)

        return max(settings.idle_limit + 1, settings.focus_threshold)
