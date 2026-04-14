from __future__ import annotations

from threading import Lock

from .models import MonitoringState, PetState
from .settings_store import SettingsStore

FREETIME_MINUTES = 5


class ReminderManager:
    def __init__(self, settings_store: SettingsStore) -> None:
        self.settings_store = settings_store
        self._lock = Lock()
        self._focused_minutes = 0
        self._idle_minutes = 0
        self._in_freetime = False
        self._pending_update: PetState | None = None

    def process_minute(self, state: MonitoringState) -> None:
        settings = self.settings_store.load()
        idle_threshold = settings.kpm_thresholds.get("idle", 5)

        with self._lock:
            self._update_freetime(state=state, idle_threshold=idle_threshold)
            self._update_focus_reminders(state=state, settings=settings)

    def pop_pending_update(self) -> PetState | None:
        with self._lock:
            pending = self._pending_update
            self._pending_update = None
            return pending

    def _update_freetime(self, state: MonitoringState, idle_threshold: int) -> None:
        if state.kpm_value < idle_threshold:
            self._idle_minutes += 1
        else:
            self._idle_minutes = 0
            self._in_freetime = False

        if self._idle_minutes >= FREETIME_MINUTES and not self._in_freetime:
            self._in_freetime = True
            self._queue_update(
                PetState(
                    visible=True,
                    emotion="play",
                    speak="Looks like you are in free time. Want to play for a bit?",
                )
            )

    def _update_focus_reminders(self, state: MonitoringState, settings) -> None:
        if state.status.label != "Focused":
            self._focused_minutes = 0
            return

        self._focused_minutes += 1

        reminder_types = set(settings.reminder_types)
        hydration_interval = settings.hydration_reminder_interval_minutes
        stretching_interval = settings.stretching_reminder_interval_minutes

        if (
            "hydration" in reminder_types
            and hydration_interval > 0
            and self._focused_minutes % hydration_interval == 0
        ):
            self._queue_update(
                PetState(
                    visible=True,
                    emotion="happy",
                    speak="Drink some water! You've been working for a while.",
                )
            )
            return

        if (
            "stretching" in reminder_types
            and stretching_interval > 0
            and self._focused_minutes % stretching_interval == 0
        ):
            self._queue_update(
                PetState(
                    visible=True,
                    emotion="happy",
                    speak="Time to stretch! A quick break helps you stay sharp.",
                )
            )

    def _queue_update(self, payload: PetState) -> None:
        self._pending_update = payload
