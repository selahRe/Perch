from __future__ import annotations

import logging
import subprocess
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from pynput import keyboard

from .classifier import StatusClassifier
from .models import HistoryPoint, MonitoringSettings, MonitoringState, StatusClassification
from .settings_store import SettingsStore
from .storage import MetricsRepository


LOGGER = logging.getLogger(__name__)

MINUTE_SECONDS = 60
RETENTION_HOURS = 24

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
        self.db_path = db_path or (project_root / "perch_metrics.sqlite3")
        self.settings_store = SettingsStore(settings_path or (project_root / "settings.json"))
        self.classifier = StatusClassifier(self.settings_store)
        self.minute_seconds = minute_seconds
        self.repository = MetricsRepository(self.db_path)
        self.on_minute_complete = on_minute_complete or self._default_minute_callback

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._listener: keyboard.Listener | None = None
        self._sampler_thread: threading.Thread | None = None
        self._current_minute_count = 0
        self._total_key_presses = 0
        self._latest_state = MonitoringState(
            timestamp=datetime.now(timezone.utc),
            kpm_value=0,
            status=StatusClassification(label="Idle", confidence=1.0),
            app_name=None,
        )
        self._started = False

    def start(self) -> None:
        if self._started:
            return

        self._stop_event.clear()
        self._start_listener()
        self._sampler_thread = threading.Thread(target=self._sampling_loop, daemon=True)
        self._sampler_thread.start()
        self._started = True
        self._complete_minute()

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
            return self._latest_state.model_copy()

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
            )
            for row in rows
        ]

    def _start_listener(self) -> None:
        try:
            self._listener = keyboard.Listener(on_press=self._on_press)
            self._listener.start()
        except Exception:
            self._listener = None
            LOGGER.exception(
                "Keyboard listener failed to start. On macOS, grant Accessibility permission to the terminal or editor."
            )

    def _on_press(self, _: keyboard.Key | keyboard.KeyCode | None) -> None:
        with self._lock:
            self._current_minute_count += 1
            self._total_key_presses += 1

    def _sampling_loop(self) -> None:
        while not self._stop_event.wait(self.minute_seconds):
            self._complete_minute()

    def _complete_minute(self) -> None:
        with self._lock:
            kpm_value = self._current_minute_count
            self._current_minute_count = 0
            app_name = self._get_active_app_name()

        classification = self.classifier.classify(kpm_value=kpm_value, app_name=app_name)
        state = MonitoringState(
            timestamp=datetime.now(timezone.utc),
            kpm_value=kpm_value,
            status=classification,
            app_name=app_name,
        )

        with self._lock:
            self._latest_state = state

        try:
            self.on_minute_complete(state)
        except Exception:
            LOGGER.exception("Failed to process 60-second monitoring callback")

    def _default_minute_callback(self, state: MonitoringState) -> None:
        self.repository.save_minute_record(
            timestamp=state.timestamp,
            kpm_value=state.kpm_value,
            status_label=state.status.label,
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
            app_name = result.stdout.strip()
            return app_name or None
        except Exception:
            return None
