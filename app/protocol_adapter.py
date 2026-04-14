from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock

from .models import PetBehaviorRule, PetState, ProtocolAdapterSettings, StatusLabel
from .settings_store import SettingsStore


class PetUpdateAdapter:
    def __init__(self, settings_store: SettingsStore) -> None:
        self.settings_store = settings_store
        self._lock = Lock()
        self._last_spoken_at: datetime | None = None
        self._last_label: StatusLabel | None = None

    def build_update(
        self,
        status_duration_seconds: int,
        current_kpm: int,
        status_label: StatusLabel,
        now: datetime | None = None,
    ) -> PetState:
        settings = self.settings_store.load().protocol_adapter
        current_time = now or datetime.now(timezone.utc)
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=timezone.utc)
        else:
            current_time = current_time.astimezone(timezone.utc)

        rule = self._select_rule(
            settings=settings,
            status_label=status_label,
            status_duration_seconds=status_duration_seconds,
            current_kpm=current_kpm,
        )
        should_cooldown = False
        if settings.cooldown_seconds > 0:
            with self._lock:
                if self._last_spoken_at is not None and self._last_label == status_label:
                    elapsed_seconds = (current_time - self._last_spoken_at).total_seconds()
                    should_cooldown = elapsed_seconds < settings.cooldown_seconds
                if not should_cooldown:
                    self._last_spoken_at = current_time
                    self._last_label = status_label

        speak = settings.cooldown_fallback_speak if should_cooldown else self._render_speak(
            rule=rule,
            status_duration_seconds=status_duration_seconds,
            current_kpm=current_kpm,
            status_label=status_label,
        )

        return PetState(
            visible=rule.visible,
            emotion=rule.emotion,
            speak=speak,
        )

    def _select_rule(
        self,
        settings: ProtocolAdapterSettings,
        status_label: StatusLabel,
        status_duration_seconds: int,
        current_kpm: int,
    ) -> PetBehaviorRule:
        focused_long_enough = (
            status_label == "Focused"
            and current_kpm >= settings.focused_long_kpm_threshold
            and status_duration_seconds >= settings.focused_long_duration_seconds
        )
        if focused_long_enough:
            return settings.focused_long

        if status_label == "Focused":
            return settings.focused

        if status_label == "Relaxed":
            return settings.relaxed

        return settings.idle

    def _render_speak(
        self,
        rule: PetBehaviorRule,
        status_duration_seconds: int,
        current_kpm: int,
        status_label: StatusLabel,
    ) -> str:
        try:
            return rule.speak.format(
                kpm=current_kpm,
                status_label=status_label,
                status_duration_seconds=status_duration_seconds,
                status_duration_minutes=max(1, status_duration_seconds // 60),
            )
        except Exception:
            return rule.speak


def get_pet_update(
    status_duration_seconds: int,
    current_kpm: int,
    status_label: StatusLabel,
    protocol_settings: ProtocolAdapterSettings | None = None,
) -> PetState:
    settings = protocol_settings or ProtocolAdapterSettings()
    focused_long_enough = (
        status_label == "Focused"
        and current_kpm >= settings.focused_long_kpm_threshold
        and status_duration_seconds >= settings.focused_long_duration_seconds
    )
    if focused_long_enough:
        rule = settings.focused_long
    elif status_label == "Focused":
        rule = settings.focused
    elif status_label == "Relaxed":
        rule = settings.relaxed
    else:
        rule = settings.idle

    try:
        speak = rule.speak.format(
            kpm=current_kpm,
            status_label=status_label,
            status_duration_seconds=status_duration_seconds,
            status_duration_minutes=max(1, status_duration_seconds // 60),
        )
    except Exception:
        speak = rule.speak

    return PetState(visible=rule.visible, emotion=rule.emotion, speak=speak)
