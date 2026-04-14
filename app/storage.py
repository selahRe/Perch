from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock

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
                CREATE TABLE IF NOT EXISTS monitoring_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    kpm_value INTEGER NOT NULL,
                    status_label TEXT NOT NULL,
                    app_name TEXT
                )
                """
            )
            columns = connection.execute("PRAGMA table_info(monitoring_history)").fetchall()
            column_names = {row[1] for row in columns}
            if "app_name" not in column_names:
                connection.execute("ALTER TABLE monitoring_history ADD COLUMN app_name TEXT")
            connection.commit()

    def save_minute_record(
        self,
        timestamp: datetime,
        kpm_value: int,
        status_label: str,
        app_name: str | None = None,
    ) -> None:
        with self._lock:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO monitoring_history (timestamp, kpm_value, status_label, app_name)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        timestamp.astimezone(timezone.utc).isoformat(),
                        kpm_value,
                        status_label,
                        app_name,
                    ),
                )
                connection.commit()

    def cleanup_older_than(self, hours: int = 24) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        with self._lock:
            with self._connect() as connection:
                connection.execute(
                    """
                    DELETE FROM monitoring_history
                    WHERE timestamp < ?
                    """,
                    (cutoff.isoformat(),),
                )
                connection.commit()

    def load_history(self, since_timestamp: datetime) -> list[sqlite3.Row]:
        with self._lock:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT
                        id,
                        timestamp,
                        kpm_value,
                        status_label,
                        app_name
                    FROM monitoring_history
                    WHERE timestamp >= ?
                    ORDER BY timestamp ASC
                    """,
                    (since_timestamp.astimezone(timezone.utc).isoformat(),),
                ).fetchall()
        return list(rows)
