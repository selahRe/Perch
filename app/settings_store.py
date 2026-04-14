from __future__ import annotations

import json
from pathlib import Path
from threading import Lock

from .models import MonitoringSettings


class SettingsStore:
    def __init__(self, settings_path: Path) -> None:
        self.settings_path = settings_path
        self._lock = Lock()
        self._ensure_file()

    def _ensure_file(self) -> None:
        if self.settings_path.exists():
            return
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings_path.write_text(
            MonitoringSettings().model_dump_json(indent=2),
            encoding="utf-8",
        )

    def load(self) -> MonitoringSettings:
        with self._lock:
            raw = self.settings_path.read_text(encoding="utf-8")
            payload = json.loads(raw)
            return MonitoringSettings(**payload)

    def save(self, settings: MonitoringSettings) -> MonitoringSettings:
        with self._lock:
            self.settings_path.write_text(
                settings.model_dump_json(indent=2),
                encoding="utf-8",
            )
            return settings
