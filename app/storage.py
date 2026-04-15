from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock


def _status_code_from_label(status_label: str) -> int:
    if status_label == "Focused":
        return 2
    if status_label == "Relaxed":
        return 1
    return 0


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
            if "is_work_hour" not in column_names:
                connection.execute("ALTER TABLE monitoring_history ADD COLUMN is_work_hour INTEGER NOT NULL DEFAULT 0")
            if "status_code" not in column_names:
                connection.execute("ALTER TABLE monitoring_history ADD COLUMN status_code INTEGER NOT NULL DEFAULT 0")
                connection.execute(
                    """
                    UPDATE monitoring_history
                    SET status_code = CASE status_label
                        WHEN 'Focused' THEN 2
                        WHEN 'Relaxed' THEN 1
                        ELSE 0
                    END
                    """
                )
            connection.commit()

    def save_minute_record(
        self,
        timestamp: datetime,
        kpm_value: int,
        status_label: str,
        app_name: str | None = None,
        is_work_hour: bool = False,
        status_code: int | None = None,
    ) -> None:
        with self._lock:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO monitoring_history (timestamp, kpm_value, status_label, app_name, is_work_hour, status_code)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        timestamp.astimezone(timezone.utc).isoformat(),
                        kpm_value,
                        status_label,
                        app_name,
                        1 if is_work_hour else 0,
                        _status_code_from_label(status_label) if status_code is None else status_code,
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
                        status_code,
                        status_label,
                        app_name,
                        is_work_hour
                    FROM monitoring_history
                    WHERE timestamp >= ?
                    ORDER BY timestamp ASC
                    """,
                    (since_timestamp.astimezone(timezone.utc).isoformat(),),
                ).fetchall()
        return list(rows)

    def count_history(self, since_timestamp: datetime) -> int:
        with self._lock:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT COUNT(*) AS total
                    FROM monitoring_history
                    WHERE timestamp >= ?
                    """,
                    (since_timestamp.astimezone(timezone.utc).isoformat(),),
                ).fetchone()
        return int(row["total"]) if row is not None else 0

    def backfill_is_work_hour(self, detector) -> int:
        with self._lock:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT id, timestamp, kpm_value, app_name
                    FROM monitoring_history
                    """
                ).fetchall()
                updates: list[tuple[int, int]] = []
                for row in rows:
                    timestamp = datetime.fromisoformat(row["timestamp"])
                    is_work_hour = detector(
                        timestamp=timestamp,
                        app_name=row["app_name"],
                        kpm_value=int(row["kpm_value"]),
                    )
                    updates.append((1 if is_work_hour else 0, int(row["id"])))

                connection.executemany(
                    """
                    UPDATE monitoring_history
                    SET is_work_hour = ?
                    WHERE id = ?
                    """,
                    updates,
                )
                connection.commit()
        return len(updates)
