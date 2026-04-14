from __future__ import annotations

import logging
import threading
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from pynput import keyboard

from .models import BehaviorState, MonitoringConfig, MonitoringSnapshot
from .storage import MetricsRepository


LOGGER = logging.getLogger(__name__)

WINDOW_SECONDS = 60
SAMPLE_INTERVAL_SECONDS = 5
FOCUSED_KPM_THRESHOLD = 120
IDLE_KPM_THRESHOLD = 0


class KeyboardMonitor:
    def __init__(
        self,
        db_path: Path | None = None,
        window_seconds: int = WINDOW_SECONDS,
        sample_interval_seconds: int = SAMPLE_INTERVAL_SECONDS,
        focused_threshold: int = FOCUSED_KPM_THRESHOLD,
        idle_threshold: int = IDLE_KPM_THRESHOLD,
    ) -> None:
        project_root = Path(__file__).resolve().parents[1]
        self.db_path = db_path or (project_root / "perch_metrics.sqlite3")
        self.window_seconds = window_seconds
        self.sample_interval_seconds = sample_interval_seconds
        self._config = MonitoringConfig(
            idle_kpm_threshold=idle_threshold,
            focused_kpm_threshold=focused_threshold,
        )
        self.repository = MetricsRepository(self.db_path)

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._listener: keyboard.Listener | None = None
        self._sampler_thread: threading.Thread | None = None
        self._key_timestamps: deque[float] = deque()
        self._total_key_presses = 0
        self._started = False

    def start(self) -> None:
        if self._started:
            return

        self._stop_event.clear()
        self._start_listener()
        self._sampler_thread = threading.Thread(target=self._sampling_loop, daemon=True)
        self._sampler_thread.start()
        self._started = True
        self._persist_snapshot()

    def stop(self) -> None:
        self._stop_event.set()
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:  # pragma: no cover - best effort shutdown
                LOGGER.exception("Failed to stop keyboard listener cleanly")
            self._listener = None
        self._started = False

    def snapshot(self) -> MonitoringSnapshot:
        with self._lock:
            self._trim_old_keys_locked()
            key_presses_last_minute = len(self._key_timestamps)
            kpm = key_presses_last_minute
            behavior_state = self._classify(kpm)
            total_key_presses = self._total_key_presses

        return MonitoringSnapshot(
            captured_at=datetime.now(timezone.utc),
            kpm=kpm,
            behavior_state=behavior_state,
            key_presses_last_minute=key_presses_last_minute,
            total_key_presses=total_key_presses,
            window_seconds=self.window_seconds,
        )

    def config(self) -> MonitoringConfig:
        with self._lock:
            return self._config.model_copy()

    def update_config(self, config: MonitoringConfig) -> MonitoringConfig:
        with self._lock:
            self._config = config.model_copy()
            return self._config.model_copy()

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
            timestamp = datetime.now(timezone.utc).timestamp()
            self._key_timestamps.append(timestamp)
            self._total_key_presses += 1
            self._trim_old_keys_locked(timestamp)

    def _trim_old_keys_locked(self, now_timestamp: float | None = None) -> None:
        current_timestamp = now_timestamp or datetime.now(timezone.utc).timestamp()
        cutoff = current_timestamp - self.window_seconds
        while self._key_timestamps and self._key_timestamps[0] < cutoff:
            self._key_timestamps.popleft()

    def _classify(self, kpm: int) -> BehaviorState:
        if kpm <= self._config.idle_kpm_threshold:
            return "idle"
        if kpm >= self._config.focused_kpm_threshold:
            return "focused"
        return "relaxed"

    def _sampling_loop(self) -> None:
        while not self._stop_event.wait(self.sample_interval_seconds):
            self._persist_snapshot()

    def _persist_snapshot(self) -> None:
        snapshot = self.snapshot()
        try:
            self.repository.save_snapshot(snapshot)
        except Exception:
            LOGGER.exception("Failed to persist keyboard metrics snapshot")
