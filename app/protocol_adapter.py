from __future__ import annotations

from datetime import datetime, timezone

from .models import PetState
from .settings_store import SettingsStore


def get_pet_update(status_duration_seconds: int, current_kpm: int, status_label: str) -> PetState:
    if status_label == "Idle":
        return PetState(visible=True, emotion="idle", speak="...")

    if (
        status_label == "Focused"
        and current_kpm >= 100
        and status_duration_seconds >= 30 * 60
    ):
        return PetState(
            visible=True,
            emotion="happy",
            speak=f"Great job! You've been focused for {status_duration_seconds // 60} minutes!",
        )

    if status_label == "Focused":
        return PetState(visible=True, emotion="play", speak="Nice focus streak. Keep going!")

    return PetState(visible=True, emotion="happy", speak="Steady pace. You're doing well.")


class PetUpdateAdapter:
    def __init__(self, settings_store: SettingsStore) -> None:
        self.settings_store = settings_store
        self._last_sent_at: datetime | None = None

    def build_update(
        self,
        status_duration_seconds: int,
        current_kpm: int,
        status_label: str,
        now: datetime | None = None,
    ) -> PetState:
        settings = self.settings_store.load()
        adapter = settings.protocol_adapter
        now = now or datetime.now(timezone.utc)

        rule_name = status_label.lower()
        if (
            status_label == "Focused"
            and current_kpm >= adapter.focused_long_kpm_threshold
            and status_duration_seconds >= adapter.focused_long_duration_seconds
        ):
            rule_name = "focused_long"

        rule = getattr(adapter, rule_name)

        if self._last_sent_at is not None:
            elapsed = (now - self._last_sent_at).total_seconds()
            if elapsed < adapter.cooldown_seconds:
                return PetState(
                    visible=rule.visible,
                    emotion=rule.emotion,
                    speak=adapter.cooldown_fallback_speak,
                )

        self._last_sent_at = now
        speak = rule.speak.format(
            kpm=current_kpm,
            status_duration_minutes=max(1, status_duration_seconds // 60),
        )
        return PetState(visible=rule.visible, emotion=rule.emotion, speak=speak)
