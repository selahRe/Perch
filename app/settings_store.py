from __future__ import annotations

import json
from pathlib import Path

from .models import MonitoringSettings


class SettingsStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> MonitoringSettings:
        if not self.path.exists():
            return MonitoringSettings()

        data = json.loads(self.path.read_text(encoding="utf-8"))
        return MonitoringSettings.model_validate(data)

    def save(self, settings: MonitoringSettings) -> MonitoringSettings:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(settings.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return settings
