from __future__ import annotations

import json
from pathlib import Path
from threading import Lock

from .models import ConfigBundle, MonitoringSettings, UserProfile
from .settings_store import SettingsStore


def get_default_perch_storage_root() -> Path:
    documents_dir = Path.home() / "Documents"
    if documents_dir.exists():
        return documents_dir / ".perch"
    return Path.home() / ".perch"


class ConfigStore:
    def __init__(self, settings_store: SettingsStore, profile_path: Path | None = None) -> None:
        self.settings_store = settings_store
        self.profile_path = profile_path or (self.settings_store.settings_path.parent / "profile.json")
        self._lock = Lock()
        self._ensure_profile_file()

    def _ensure_profile_file(self) -> None:
        if self.profile_path.exists():
            return
        self.profile_path.parent.mkdir(parents=True, exist_ok=True)
        default_profile = UserProfile()
        self.profile_path.write_text(default_profile.model_dump_json(indent=2), encoding="utf-8")

    def load_profile(self) -> UserProfile:
        with self._lock:
            payload = json.loads(self.profile_path.read_text(encoding="utf-8"))
            return UserProfile(**payload)

    def save_profile(self, profile: UserProfile) -> UserProfile:
        with self._lock:
            self.profile_path.write_text(profile.model_dump_json(indent=2), encoding="utf-8")
            return profile

    def load_settings(self) -> MonitoringSettings:
        return self.settings_store.load()

    def save_settings(self, settings: MonitoringSettings) -> MonitoringSettings:
        return self.settings_store.save(settings)

    def load_bundle(self) -> ConfigBundle:
        return ConfigBundle(profile=self.load_profile(), settings=self.load_settings())
