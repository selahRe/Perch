from __future__ import annotations

import logging
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from pynput import keyboard

from .config_store import get_default_perch_storage_root
from .classifier import StatusClassifier
from .models import HistoryPoint, MonitoringSettings, MonitoringState, StatusClassification
from .settings_store import SettingsStore
from .storage import MetricsRepository
from .work_hours import infer_is_work_hour


LOGGER = logging.getLogger(__name__)

MINUTE_SECONDS = 60
APP_SAMPLING_SECONDS = 1.0
RETENTION_HOURS = 14 * 24

MinuteCallback = Callable[[MonitoringState], None]


class KeyboardMonitor:
    def __init__(
        self,
        db_path: Path | None = None,
        settings_path: Path | None = None,
        minute_seconds: int = MINUTE_SECONDS,
        on_minute_complete: MinuteCallback | None = None,
    ) -> None:
        project_root = Path(__file__).resolve().parents[1]
        default_storage_root = get_default_perch_storage_root()
        self.db_path = db_path or (project_root / "perch_metrics.sqlite3")
        self.settings_store = SettingsStore(settings_path or (default_storage_root / "settings.json"))
        self.minute_seconds = minute_seconds
        self.repository = MetricsRepository(self.db_path)
        self.classifier = StatusClassifier(self.settings_store, repository=self.repository)
        self.on_minute_complete = on_minute_complete or self._default_minute_callback

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._listener: keyboard.Listener | None = None
        self._sampler_thread: threading.Thread | None = None
        self._current_minute_count = 0
        self._current_app_name: str | None = None
        self._app_durations_seconds: dict[str, float] = {}
        self._minute_started_monotonic = time.monotonic()
        self._last_key_pressed_at: datetime | None = None
        self._last_minute_completed_at: datetime | None = None
        self._listener_error: str | None = None
        self._latest_state = MonitoringState(
            timestamp=datetime.now(timezone.utc),
            kpm_value=0,
            status_code=0,
            status=StatusClassification(label="Idle", confidence=1.0),
            user_cluster="offline_rest",
            app_name=None,
        )
        self._status_started_at = self._latest_state.timestamp
        self._started = False

    def start(self) -> None:
        if self._started:
            return

        self._stop_event.clear()
        with self._lock:
            self._minute_started_monotonic = time.monotonic()
            self._app_durations_seconds = {}
            self._current_app_name = None
        self._start_listener()
        self._sampler_thread = threading.Thread(target=self._sampling_loop, daemon=True)
        self._sampler_thread.start()
        self._started = True

    def stop(self) -> None:
        self._stop_event.set()
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:  # pragma: no cover - best effort shutdown
                LOGGER.exception("Failed to stop keyboard listener cleanly")
            self._listener = None
        self._started = False

    def snapshot(self) -> MonitoringState:
        with self._lock:
            listener_running = bool(self._listener and self._listener.is_alive())
            current_app_name = self._current_app_name or self._latest_state.app_name
            return self._latest_state.model_copy(
                update={
                    "app_name": current_app_name,
                    "current_minute_count": self._current_minute_count,
                    "listener_running": listener_running,
                    "listener_error": self._listener_error,
                    "last_key_pressed_at": self._last_key_pressed_at,
                    "last_minute_completed_at": self._last_minute_completed_at,
                    "sampling_interval_seconds": self.minute_seconds,
                }
            )

    def config(self) -> MonitoringSettings:
        return self.settings_store.load()

    def update_config(self, config: MonitoringSettings) -> MonitoringSettings:
        return self.settings_store.save(config)

    def history(self, period: str = "1h") -> list[HistoryPoint]:
        since = self._parse_period(period)
        rows = self.repository.load_history(since_timestamp=since)
        return [
            HistoryPoint(
                time=datetime.fromisoformat(row["timestamp"]).astimezone().strftime("%H:%M"),
                kpm=row["kpm_value"],
                label=row["status_label"],
                app_name=row["app_name"],
            )
            for row in rows
        ]

    def current_status_duration_seconds(self) -> int:
        with self._lock:
            started_at = self._status_started_at
        return max(0, int((datetime.now(timezone.utc) - started_at).total_seconds()))

    def _start_listener(self) -> None:
        try:
            self._listener = keyboard.Listener(on_press=self._on_press)
            self._listener.start()
            # Give the listener thread a brief moment to initialize before checking status.
            time.sleep(0.1)
            if self._listener.is_alive():
                self._listener_error = None
                LOGGER.info(
                    "Keyboard listener started; sampling every %s seconds. Accessibility permission is required on macOS.",
                    self.minute_seconds,
                )
            else:
                self._listener_error = (
                    "Keyboard listener did not enter running state. "
                    "Grant Accessibility and Input Monitoring to the app launching Python (VS Code/Terminal)."
                )
                LOGGER.warning(self._listener_error)
        except Exception:
            self._listener = None
            self._listener_error = (
                "Keyboard listener failed to start. Grant Accessibility and Input Monitoring to the app launching "
                "Python (VS Code/Terminal)."
            )
            LOGGER.exception(
                "Keyboard listener failed to start. On macOS, grant Accessibility permission to the terminal or editor."
            )

    def _on_press(self, _: keyboard.Key | keyboard.KeyCode | None) -> None:
        with self._lock:
            self._current_minute_count += 1
            self._last_key_pressed_at = datetime.now(timezone.utc)

    def _sampling_loop(self) -> None:
        while not self._stop_event.wait(APP_SAMPLING_SECONDS):
            self._sample_active_app()
            with self._lock:
                elapsed_seconds = time.monotonic() - self._minute_started_monotonic
            if elapsed_seconds >= self.minute_seconds:
                self._complete_minute()

    def _sample_active_app(self) -> None:
        app_name = self._get_active_app_name()
        if app_name is None:
            return

        with self._lock:
            self._current_app_name = app_name
            self._app_durations_seconds[app_name] = self._app_durations_seconds.get(app_name, 0.0) + APP_SAMPLING_SECONDS

    def _pick_dominant_app(self, app_durations_seconds: dict[str, float]) -> str | None:
        if not app_durations_seconds:
            return None

        return max(app_durations_seconds.items(), key=lambda item: item[1])[0]

    def _complete_minute(self) -> None:
        self._sample_active_app()
        with self._lock:
            kpm_value = self._current_minute_count
            self._current_minute_count = 0
            previous_label = self._latest_state.status.label
            last_key_pressed_at = self._last_key_pressed_at
            app_durations_seconds = dict(self._app_durations_seconds)
            self._app_durations_seconds = {}
            self._minute_started_monotonic = time.monotonic()

        app_name = self._pick_dominant_app(app_durations_seconds)

        classification = self.classifier.classify_with_cluster(kpm_value=kpm_value, app_name=app_name)
        timestamp = datetime.now(timezone.utc)
        settings = self.settings_store.load()
        is_work_hour = infer_is_work_hour(
            timestamp=timestamp,
            app_name=app_name,
            kpm_value=kpm_value,
            work_time_start=settings.work_time_start,
            work_time_end=settings.work_time_end,
        )
        state = MonitoringState(
            timestamp=timestamp,
            kpm_value=kpm_value,
            status_code=self._status_code_from_label(classification.status.label),
            status=classification.status,
            user_cluster=classification.user_cluster,
            app_name=app_name,
            current_minute_count=0,
            listener_running=bool(self._listener and self._listener.is_alive()),
            listener_error=self._listener_error,
            last_key_pressed_at=last_key_pressed_at,
            last_minute_completed_at=timestamp,
            sampling_interval_seconds=self.minute_seconds,
        )

        with self._lock:
            if classification.status.label != previous_label:
                self._status_started_at = timestamp
            self._latest_state = state
            self._last_minute_completed_at = timestamp

        LOGGER.info(
            "Minute sample completed: kpm=%s status=%s app=%s listener_running=%s listener_error=%s app_seconds=%s",
            kpm_value,
            classification.status.label,
            app_name or "unknown",
            bool(self._listener and self._listener.is_alive()),
            self._listener_error or "none",
            app_durations_seconds,
        )

        try:
            self.on_minute_complete(state)
        except Exception:
            LOGGER.exception("Failed to process 60-second monitoring callback")

    def _default_minute_callback(self, state: MonitoringState) -> None:
        self.repository.save_minute_record(
            timestamp=state.timestamp,
            kpm_value=state.kpm_value,
            status_label=state.status.label,
            app_name=state.app_name,
            is_work_hour=infer_is_work_hour(
                timestamp=state.timestamp,
                app_name=state.app_name,
                kpm_value=state.kpm_value,
                work_time_start=self.settings_store.load().work_time_start,
                work_time_end=self.settings_store.load().work_time_end,
            ),
            status_code=state.status_code,
        )
        self.repository.cleanup_older_than(hours=RETENTION_HOURS)

    def _parse_period(self, period: str) -> datetime:
        normalized = period.strip().lower()
        now = datetime.now(timezone.utc)
        if normalized == "1h":
            return now - timedelta(hours=1)
        if normalized == "24h":
            return now - timedelta(hours=24)
        raise ValueError("period must be '1h' or '24h'")

    def _get_active_app_name(self) -> str | None:
        if sys.platform != "darwin":
            return None

        if not hasattr(subprocess, "run"):
            return None

        try:
            script = (
                'tell application "System Events" to '
                'get name of first process whose frontmost is true'
            )
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=1,
                check=False,
            )
            if result.returncode != 0:
                LOGGER.warning(
                    "Failed to read frontmost app via osascript (code=%s): %s",
                    result.returncode,
                    (result.stderr or "").strip() or "unknown error",
                )
                return None
            app_name = result.stdout.strip()
            if not app_name and result.stderr.strip():
                LOGGER.warning("osascript returned empty app name: %s", result.stderr.strip())
            return app_name or None
        except Exception:
            LOGGER.exception("Unexpected error while reading active app name")
            return None

    def _status_code_from_label(self, label: str) -> int:
        if label == "Focused":
            return 2
        if label == "Relaxed":
            return 1
        return 0
