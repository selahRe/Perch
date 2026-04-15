from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .models import ConfigBundle, MonitoringSettings, UserProfile
from .settings_store import SettingsStore


def get_default_perch_storage_root() -> Path:
    documents_root = Path.home() / "Documents"
    documents_candidate = documents_root / ".perch"
    if documents_root.exists():
        return documents_candidate
    return Path.home() / ".perch"


class ConfigStore:
    def __init__(self, settings_store: SettingsStore, profile_path: Path | None = None) -> None:
        self.settings_store = settings_store
        self.profile_path = profile_path or (get_default_perch_storage_root() / "profile.json")

    def load_bundle(self) -> ConfigBundle:
        return ConfigBundle(profile=self._load_profile(), settings=self.settings_store.load())

    def save_profile(self, profile: UserProfile) -> UserProfile:
        self.profile_path.parent.mkdir(parents=True, exist_ok=True)
        payload = profile.model_dump(mode="json", by_alias=True)
        self.profile_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return profile

    def save_settings(self, settings: MonitoringSettings) -> MonitoringSettings:
        return self.settings_store.save(settings)

    def _load_profile(self) -> UserProfile:
        if not self.profile_path.exists():
            return UserProfile()

        data = json.loads(self.profile_path.read_text(encoding="utf-8"))

        created_at = data.get("created_at")
        if isinstance(created_at, str):
            try:
                data["created_at"] = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            except ValueError:
                pass

        return UserProfile.model_validate(data)
