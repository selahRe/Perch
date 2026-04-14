from datetime import datetime, timedelta, timezone
import json

import app.main as main_module
from app.config_store import ConfigStore
from app.classifier import StatusClassifier
from app.models import MonitoringSettings, PetState, UserProfile
from app.monitoring import KeyboardMonitor
from app.protocol_adapter import PetUpdateAdapter, get_pet_update
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
                "reminder_types": ["hydration", "stretching", "meeting"],
                "check_interval": 60,
                "pet_visible_always": True,
                "kpm_thresholds": {"idle": 5, "focus": 50},
                "protocol_adapter": {
                    "focused_long_kpm_threshold": 80,
                    "focused_long_duration_seconds": 600,
                    "cooldown_seconds": 120,
                    "cooldown_fallback_speak": "...",
                    "idle": {"visible": True, "emotion": "idle", "speak": "..."},
                    "relaxed": {"visible": True, "emotion": "happy", "speak": "Relaxed at {kpm} KPM"},
                    "focused": {"visible": True, "emotion": "play", "speak": "Focused now"},
                    "focused_long": {
                        "visible": True,
                        "emotion": "happy",
                        "speak": "Focused for {status_duration_minutes} minutes",
                    },
                },
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


def test_protocol_adapter_maps_kpm_and_duration_to_pet_payload():
    focused_long = get_pet_update(
        status_duration_seconds=31 * 60,
        current_kpm=110,
        status_label="Focused",
    )
    idle = get_pet_update(
        status_duration_seconds=5 * 60,
        current_kpm=0,
        status_label="Idle",
    )

    assert focused_long.emotion == "happy"
    assert "focused" in focused_long.speak.lower()
    assert idle.emotion == "idle"
    assert idle.speak == "..."


def test_protocol_adapter_reads_templates_and_applies_cooldown(tmp_path):
    settings_path = tmp_path / "settings.json"
    write_settings(settings_path)
    adapter = PetUpdateAdapter(SettingsStore(settings_path))

    first = adapter.build_update(
        status_duration_seconds=700,
        current_kpm=90,
        status_label="Focused",
        now=datetime(2026, 4, 14, 10, 0, tzinfo=timezone.utc),
    )
    second = adapter.build_update(
        status_duration_seconds=705,
        current_kpm=95,
        status_label="Focused",
        now=datetime(2026, 4, 14, 10, 1, tzinfo=timezone.utc),
    )
    after_cooldown = adapter.build_update(
        status_duration_seconds=720,
        current_kpm=100,
        status_label="Focused",
        now=datetime(2026, 4, 14, 10, 3, tzinfo=timezone.utc),
    )

    assert first.emotion == "happy"
    assert "minutes" in first.speak
    assert second.speak == "..."
    assert after_cooldown.speak != "..."


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
    adapter = PetUpdateAdapter(monitor.settings_store)
    store = ConfigStore(monitor.settings_store, profile_path=tmp_path / "profile.json")

    monkeypatch.setattr(main_module, "keyboard_monitor", monitor)
    monkeypatch.setattr(main_module, "pet_update_adapter", adapter)
    monkeypatch.setattr(main_module, "config_store", store)
    monkeypatch.setattr(
        main_module,
        "current_state",
        PetState(visible=False, emotion="play", speak="go"),
    )

    state = main_module.get_state()
    history_1h = main_module.get_monitoring_history(period="1h")
    history_24h = main_module.get_monitoring_history(period="24h")
    monkeypatch.setattr(adapter, "build_update", lambda **_: PetState(visible=True, emotion="happy", speak="cfg"))
    pet_update = main_module.get_pet_update_payload()
    bundle = main_module.load_config_bundle()
    save_profile_result = main_module.save_profile(UserProfile(username="Chloe", gender="female", onboarding_completed=True))
    save_settings_result = main_module.save_settings(MonitoringSettings())
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
    assert pet_update.visible is True
    assert pet_update.emotion in ["happy", "play", "idle", "eat"]
    assert bundle.profile.username == ""
    assert bundle.settings.pet_visible_always is True
    assert save_profile_result.success is True
    assert save_settings_result.success is True
    assert config.focus_threshold == 60
    assert updated.focus_threshold == 55
    assert main_module.get_monitoring_config().focus_threshold == 55


def test_config_store_creates_defaults_and_persists_profile_and_settings(tmp_path):
    settings_path = tmp_path / "settings.json"
    store = ConfigStore(SettingsStore(settings_path), profile_path=tmp_path / "profile.json")

    bundle = store.load_bundle()
    assert bundle.profile.username == ""
    assert bundle.profile.onboarding_completed is False
    assert bundle.settings.pet_visible_always is True
    assert bundle.settings.kpm_thresholds == {"idle": 5, "focus": 50}

    saved_profile = store.save_profile(UserProfile(username="Mika", gender="other", onboarding_completed=True))
    saved_settings = store.save_settings(MonitoringSettings(check_interval=30, pet_visible_always=False))

    assert saved_profile.username == "Mika"
    assert saved_settings.check_interval == 30
    reloaded = store.load_bundle()
    assert reloaded.profile.username == "Mika"
    assert reloaded.settings.check_interval == 30


def test_config_routes_round_trip_bundle_and_save(tmp_path, monkeypatch):
    settings_path = tmp_path / "settings.json"
    write_settings(settings_path)
    monitor = KeyboardMonitor(
        db_path=tmp_path / "metrics.sqlite3",
        settings_path=settings_path,
        minute_seconds=9999,
    )
    monitor.start = lambda: None
    monitor.stop = lambda: None
    store = ConfigStore(monitor.settings_store, profile_path=tmp_path / "profile.json")

    monkeypatch.setattr(main_module, "keyboard_monitor", monitor)
    monkeypatch.setattr(main_module, "config_store", store)

    bundle = main_module.load_config_bundle()
    profile_result = main_module.save_profile(UserProfile(username="Nora", gender="female", onboarding_completed=True))
    settings_result = main_module.save_settings(
        MonitoringSettings(reminder_types=["hydration", "meeting"], check_interval=45, pet_visible_always=False)
    )

    assert bundle.profile.username == ""
    assert bundle.settings.check_interval == 60
    assert profile_result.success is True
    assert settings_result.success is True

    reloaded = main_module.load_config_bundle()
    assert reloaded.profile.username == "Nora"
    assert reloaded.settings.check_interval == 45
    assert reloaded.settings.pet_visible_always is False


def test_pet_update_route_returns_frontend_contract(tmp_path, monkeypatch):
    settings_path = tmp_path / "settings.json"
    write_settings(settings_path)
    monitor = KeyboardMonitor(
        db_path=tmp_path / "metrics.sqlite3",
        settings_path=settings_path,
        minute_seconds=9999,
    )
    monitor.start = lambda: None
    monitor.stop = lambda: None
    adapter = PetUpdateAdapter(monitor.settings_store)
    monkeypatch.setattr(main_module, "keyboard_monitor", monitor)
    monkeypatch.setattr(main_module, "pet_update_adapter", adapter)

    payload = main_module.get_pet_update_payload()

    assert payload.visible is True
    assert payload.emotion in ["happy", "eat", "play", "idle"]
    assert isinstance(payload.speak, str)
