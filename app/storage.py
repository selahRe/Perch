from __future__ import annotations

import sqlite3
from pathlib import Path
from threading import Lock
from typing import Iterable

from .models import MonitoringSnapshot


class MetricsRepository:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._lock = Lock()
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _ensure_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS keyboard_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    captured_at TEXT NOT NULL,
                    kpm INTEGER NOT NULL,
                    behavior_state TEXT NOT NULL,
                    key_presses_last_minute INTEGER NOT NULL,
                    total_key_presses INTEGER NOT NULL,
                    window_seconds INTEGER NOT NULL
                )
                """
            )
            connection.commit()

    def save_snapshot(self, snapshot: MonitoringSnapshot) -> None:
        with self._lock:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO keyboard_metrics (
                        captured_at,
                        kpm,
                        behavior_state,
                        key_presses_last_minute,
                        total_key_presses,
                        window_seconds
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        snapshot.captured_at.isoformat(),
                        snapshot.kpm,
                        snapshot.behavior_state,
                        snapshot.key_presses_last_minute,
                        snapshot.total_key_presses,
                        snapshot.window_seconds,
                    ),
                )
                connection.commit()

    def load_recent_snapshots(self, limit: int = 60) -> list[MonitoringSnapshot]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    captured_at,
                    kpm,
                    behavior_state,
                    key_presses_last_minute,
                    total_key_presses,
                    window_seconds
                FROM keyboard_metrics
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        snapshots = [
            MonitoringSnapshot(
                captured_at=row["captured_at"],
                kpm=row["kpm"],
                behavior_state=row["behavior_state"],
                key_presses_last_minute=row["key_presses_last_minute"],
                total_key_presses=row["total_key_presses"],
                window_seconds=row["window_seconds"],
            )
            for row in rows
        ]
        return list(reversed(snapshots))
