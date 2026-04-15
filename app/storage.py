from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
import json
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
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS habit_profile (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS decision_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    context_hash TEXT NOT NULL,
                    decision_json TEXT NOT NULL,
                    source TEXT NOT NULL,
                    token_usage_json TEXT,
                    latency_ms INTEGER NOT NULL,
                    blocked_by TEXT
                )
                """
            )
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

    def load_recent_kpm(self, minutes: int = 30) -> list[int]:
        since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        with self._lock:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT kpm_value
                    FROM monitoring_history
                    WHERE timestamp >= ?
                    ORDER BY timestamp ASC
                    """,
                    (since.isoformat(),),
                ).fetchall()
        return [int(row["kpm_value"]) for row in rows]

    def load_habit_profile(self) -> dict:
        with self._lock:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT payload FROM habit_profile WHERE id = 1"
                ).fetchone()
        if row is None:
            return {"focus_hours": [], "idle_hours": [], "updated_at": None}
        return json.loads(str(row["payload"]))

    def save_habit_profile(self, payload: Mapping[str, object]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO habit_profile (id, payload, updated_at)
                    VALUES (1, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at
                    """,
                    (json.dumps(dict(payload), ensure_ascii=False), now),
                )
                connection.commit()

    def save_decision_record(
        self,
        *,
        timestamp: datetime,
        context_hash: str,
        decision_json: str,
        source: str,
        token_usage: Mapping[str, int] | None,
        latency_ms: int,
        blocked_by: str | None,
    ) -> None:
        with self._lock:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO decision_history (
                        timestamp, context_hash, decision_json, source, token_usage_json, latency_ms, blocked_by
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        timestamp.astimezone(timezone.utc).isoformat(),
                        context_hash,
                        decision_json,
                        source,
                        json.dumps(token_usage, ensure_ascii=False) if token_usage else None,
                        latency_ms,
                        blocked_by,
                    ),
                )
                connection.commit()

    def load_decision_history(self, limit: int = 50) -> list[dict]:
        effective_limit = max(1, min(limit, 200))
        with self._lock:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT timestamp, context_hash, decision_json, source, token_usage_json, latency_ms, blocked_by
                    FROM decision_history
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (effective_limit,),
                ).fetchall()
        history: list[dict] = []
        for row in rows:
            history.append(
                {
                    "timestamp": row["timestamp"],
                    "context_hash": row["context_hash"],
                    "decision": json.loads(str(row["decision_json"])),
                    "source": row["source"],
                    "token_usage": json.loads(str(row["token_usage_json"])) if row["token_usage_json"] else None,
                    "latency_ms": row["latency_ms"],
                    "blocked_by": row["blocked_by"],
                }
            )
        return history

    def load_latest_decision(self) -> dict | None:
        with self._lock:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT timestamp, context_hash, decision_json, source, token_usage_json, latency_ms, blocked_by
                    FROM decision_history
                    ORDER BY id DESC
                    LIMIT 1
                    """
                ).fetchone()
        if row is None:
            return None
        return {
            "timestamp": row["timestamp"],
            "context_hash": row["context_hash"],
            "decision": json.loads(str(row["decision_json"])),
            "source": row["source"],
            "token_usage": json.loads(str(row["token_usage_json"])) if row["token_usage_json"] else None,
            "latency_ms": row["latency_ms"],
            "blocked_by": row["blocked_by"],
        }
