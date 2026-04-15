from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
import json
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
                    blocked_by TEXT,
                    llm_attempted INTEGER NOT NULL DEFAULT 0,
                    llm_success INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            decision_columns = connection.execute("PRAGMA table_info(decision_history)").fetchall()
            decision_column_names = {row[1] for row in decision_columns}
            if "llm_attempted" not in decision_column_names:
                connection.execute(
                    "ALTER TABLE decision_history ADD COLUMN llm_attempted INTEGER NOT NULL DEFAULT 0"
                )
            if "llm_success" not in decision_column_names:
                connection.execute(
                    "ALTER TABLE decision_history ADD COLUMN llm_success INTEGER NOT NULL DEFAULT 0"
                )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    source TEXT NOT NULL,
                    note TEXT NOT NULL,
                    window_start TEXT,
                    window_end TEXT,
                    tags_json TEXT,
                    score REAL
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
                row = connection.execute("SELECT payload FROM habit_profile WHERE id = 1").fetchone()
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
        llm_attempted: bool = False,
        llm_success: bool = False,
    ) -> None:
        with self._lock:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO decision_history (
                        timestamp, context_hash, decision_json, source, token_usage_json, latency_ms, blocked_by, llm_attempted, llm_success
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        timestamp.astimezone(timezone.utc).isoformat(),
                        context_hash,
                        decision_json,
                        source,
                        json.dumps(token_usage, ensure_ascii=False) if token_usage else None,
                        latency_ms,
                        blocked_by,
                        1 if llm_attempted else 0,
                        1 if llm_success else 0,
                    ),
                )
                connection.commit()

    def load_decision_history(self, limit: int = 50) -> list[dict]:
        effective_limit = max(1, min(limit, 200))
        with self._lock:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT timestamp, context_hash, decision_json, source, token_usage_json, latency_ms, blocked_by, llm_attempted, llm_success
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
                    "llm_attempted": bool(row["llm_attempted"]),
                    "llm_success": bool(row["llm_success"]),
                }
            )
        return history

    def load_latest_decision(self) -> dict | None:
        with self._lock:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT timestamp, context_hash, decision_json, source, token_usage_json, latency_ms, blocked_by, llm_attempted, llm_success
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
            "llm_attempted": bool(row["llm_attempted"]),
            "llm_success": bool(row["llm_success"]),
        }

    def save_memory_note(
        self,
        *,
        timestamp: datetime,
        source: str,
        note: str,
        window_start: datetime | None = None,
        window_end: datetime | None = None,
        tags: list[str] | None = None,
        score: float | None = None,
    ) -> None:
        with self._lock:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO memory_notes (
                        timestamp, source, note, window_start, window_end, tags_json, score
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        timestamp.astimezone(timezone.utc).isoformat(),
                        source,
                        note,
                        window_start.astimezone(timezone.utc).isoformat() if window_start else None,
                        window_end.astimezone(timezone.utc).isoformat() if window_end else None,
                        json.dumps(tags or [], ensure_ascii=False),
                        score,
                    ),
                )
                connection.commit()

    def load_recent_memory_notes(self, *, days: int = 7, limit: int = 5) -> list[dict]:
        effective_limit = max(1, min(limit, 50))
        since = (datetime.now(timezone.utc) - timedelta(days=max(1, days))).isoformat()
        with self._lock:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT timestamp, source, note, window_start, window_end, tags_json, score
                    FROM memory_notes
                    WHERE timestamp >= ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (since, effective_limit),
                ).fetchall()
        result: list[dict] = []
        for row in rows:
            result.append(
                {
                    "timestamp": row["timestamp"],
                    "source": row["source"],
                    "note": row["note"],
                    "window_start": row["window_start"],
                    "window_end": row["window_end"],
                    "tags": json.loads(str(row["tags_json"])) if row["tags_json"] else [],
                    "score": row["score"],
                }
            )
        return result

    def load_latest_memory_note(self) -> dict | None:
        with self._lock:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT timestamp, source, note, window_start, window_end, tags_json, score
                    FROM memory_notes
                    ORDER BY id DESC
                    LIMIT 1
                    """
                ).fetchone()
        if row is None:
            return None
        return {
            "timestamp": row["timestamp"],
            "source": row["source"],
            "note": row["note"],
            "window_start": row["window_start"],
            "window_end": row["window_end"],
            "tags": json.loads(str(row["tags_json"])) if row["tags_json"] else [],
            "score": row["score"],
        }
