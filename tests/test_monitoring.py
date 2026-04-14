from datetime import datetime, timedelta, timezone
import json

import app.main as main_module
from app.classifier import StatusClassifier
from app.models import MonitoringSettings, PetState
from app.monitoring import KeyboardMonitor
from app.settings_store import SettingsStore
from app.storage import MetricsRepository


def write_settings(path, idle_limit=5, focus_threshold=60):
    path.write_text(
        json.dumps(
            {
                "idle_limit": idle_limit,
                "focus_threshold": focus_threshold,
                "developer_apps": ["Code"],
                "developer_focus_delta": 10,
            }
        ),
        encoding="utf-8",
    )


def test_repository_ttl_cleanup_and_order(tmp_path):
    repository = MetricsRepository(tmp_path / "metrics.sqlite3")
    old_time = datetime.now(timezone.utc) - timedelta(hours=25)
    new_time = datetime.now(timezone.utc) - timedelta(minutes=10)

    repository.save_minute_record(timestamp=old_time, kpm_value=2, status_label="Idle")
    repository.save_minute_record(timestamp=new_time, kpm_value=40, status_label="Relaxed")
    repository.cleanup_older_than(hours=24)

    rows = repository.load_history(datetime.now(timezone.utc) - timedelta(hours=24))

    assert len(rows) == 1
    assert rows[0]["kpm_value"] == 40
    assert rows[0]["status_label"] == "Relaxed"


def test_status_classifier_uses_dynamic_settings_and_dev_app_adjustment(tmp_path):
    settings_path = tmp_path / "settings.json"
    write_settings(settings_path, idle_limit=5, focus_threshold=60)
    classifier = StatusClassifier(SettingsStore(settings_path))

    idle = classifier.classify(kpm_value=3, app_name="Notes")
    relaxed = classifier.classify(kpm_value=30, app_name="Notes")
    focused_dev = classifier.classify(kpm_value=50, app_name="Code")

    assert idle.label == "Idle"
    assert relaxed.label == "Relaxed"
    assert focused_dev.label == "Focused"
    assert 0.0 <= focused_dev.confidence <= 1.0


def test_route_helpers_support_period_history_and_settings(tmp_path, monkeypatch):
    settings_path = tmp_path / "settings.json"
    write_settings(settings_path, idle_limit=5, focus_threshold=60)
    monitor = KeyboardMonitor(
        db_path=tmp_path / "metrics.sqlite3",
        settings_path=settings_path,
        minute_seconds=9999,
    )
    monitor.start = lambda: None
    monitor.stop = lambda: None

    monitor.repository.save_minute_record(
        timestamp=datetime.now(timezone.utc) - timedelta(minutes=30),
        kpm_value=45,
        status_label="Relaxed",
    )
    monitor.repository.save_minute_record(
        timestamp=datetime.now(timezone.utc) - timedelta(hours=3),
        kpm_value=110,
        status_label="Focused",
    )

    monkeypatch.setattr(main_module, "keyboard_monitor", monitor)
    monkeypatch.setattr(
        main_module,
        "current_state",
        PetState(visible=False, emotion="play", speak="go"),
    )

    state = main_module.get_state()
    history_1h = main_module.get_monitoring_history(period="1h")
    history_24h = main_module.get_monitoring_history(period="24h")
    config = main_module.get_monitoring_config()
    updated = main_module.update_monitoring_config(
        MonitoringSettings(idle_limit=3, focus_threshold=55, developer_apps=["Code"], developer_focus_delta=10)
    )

    assert state.visible is False
    assert state.emotion == "play"
    assert state.speak == "go"
    assert len(history_1h) == 1
    assert history_1h[0].kpm == 45
    assert history_1h[0].label == "Relaxed"
    assert len(history_24h) == 2
    assert config.focus_threshold == 60
    assert updated.focus_threshold == 55
    assert main_module.get_monitoring_config().focus_threshold == 55
