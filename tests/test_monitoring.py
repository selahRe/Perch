from datetime import datetime, timezone

import app.main as main_module
from app.models import BehaviorState, MonitoringConfig, MonitoringSnapshot, PetState
from app.monitoring import KeyboardMonitor
from app.storage import MetricsRepository


def make_snapshot(
    captured_at: datetime,
    kpm: int,
    behavior_state: BehaviorState,
    total_key_presses: int,
) -> MonitoringSnapshot:
    return MonitoringSnapshot(
        captured_at=captured_at,
        kpm=kpm,
        behavior_state=behavior_state,
        key_presses_last_minute=kpm,
        total_key_presses=total_key_presses,
        window_seconds=60,
    )


def test_repository_returns_snapshots_in_chronological_order(tmp_path):
    repository = MetricsRepository(tmp_path / "metrics.sqlite3")
    first = make_snapshot(datetime(2026, 4, 14, 14, 0, tzinfo=timezone.utc), 1, "relaxed", 1)
    second = make_snapshot(datetime(2026, 4, 14, 14, 1, tzinfo=timezone.utc), 3, "focused", 3)

    repository.save_snapshot(first)
    repository.save_snapshot(second)

    items = repository.load_recent_snapshots(limit=10)

    assert [item.kpm for item in items] == [1, 3]
    assert [item.behavior_state for item in items] == ["relaxed", "focused"]


def test_keyboard_monitor_classifies_idle_relaxed_and_focused(tmp_path):
    monitor = KeyboardMonitor(db_path=tmp_path / "metrics.sqlite3", sample_interval_seconds=9999)
    monitor.update_config(MonitoringConfig(idle_kpm_threshold=0, focused_kpm_threshold=3))

    assert monitor.snapshot().behavior_state == "idle"

    monitor._on_press(None)
    monitor._on_press(None)
    assert monitor.snapshot().behavior_state == "relaxed"

    monitor._on_press(None)
    snapshot = monitor.snapshot()

    assert snapshot.kpm == 3
    assert snapshot.behavior_state == "focused"
    assert snapshot.total_key_presses == 3


def test_route_helpers_return_monitoring_state_and_history(tmp_path, monkeypatch):
    monitor = KeyboardMonitor(db_path=tmp_path / "metrics.sqlite3", sample_interval_seconds=9999)
    monitor.start = lambda: None
    monitor.stop = lambda: None

    monitor.repository.save_snapshot(
        make_snapshot(datetime(2026, 4, 14, 14, 2, tzinfo=timezone.utc), 7, "focused", 7)
    )

    monkeypatch.setattr(main_module, "keyboard_monitor", monitor)
    monkeypatch.setattr(
        main_module,
        "current_state",
        PetState(visible=False, emotion="play", speak="go"),
    )

    state = main_module.get_state()
    history = main_module.get_monitoring_history(limit=1)
    config = main_module.get_monitoring_config()
    updated = main_module.update_monitoring_config(
        MonitoringConfig(idle_kpm_threshold=0, focused_kpm_threshold=5)
    )

    assert state.visible is False
    assert state.emotion == "play"
    assert state.speak == "go"
    assert len(history.items) == 1
    assert history.items[0].kpm == 7
    assert config.focused_kpm_threshold == 120
    assert updated.focused_kpm_threshold == 5
    assert main_module.get_monitoring_config().focused_kpm_threshold == 5
