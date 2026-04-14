from contextlib import asynccontextmanager
import threading

from fastapi import FastAPI, HTTPException, Query

from .config_store import ConfigStore
from .models import ConfigBundle, HistoryPoint, MonitoringSettings, MonitoringState, PetState, SaveResult, UserProfile
from .monitoring import KeyboardMonitor
from .protocol_adapter import PetUpdateAdapter


keyboard_monitor: KeyboardMonitor | None = None
pet_update_adapter: PetUpdateAdapter | None = None
config_store: ConfigStore | None = None
_runtime_lock = threading.Lock()


def _ensure_runtime() -> tuple[KeyboardMonitor, PetUpdateAdapter, ConfigStore]:
    global keyboard_monitor, pet_update_adapter, config_store
    with _runtime_lock:
        if keyboard_monitor is None:
            keyboard_monitor = KeyboardMonitor()
        if pet_update_adapter is None:
            pet_update_adapter = PetUpdateAdapter(keyboard_monitor.settings_store)
        if config_store is None:
            config_store = ConfigStore(keyboard_monitor.settings_store)
        return keyboard_monitor, pet_update_adapter, config_store


@asynccontextmanager
async def lifespan(app: FastAPI):
    monitor, _, _ = _ensure_runtime()
    monitor.start()
    yield
    monitor.stop()


app = FastAPI(title="Perch Local API", version="0.2.0", lifespan=lifespan)

# In-memory state for local Electron integration.
current_state = PetState()


@app.get("/state", response_model=PetState)
def get_state() -> PetState:
    return current_state


@app.get("/monitoring/state", response_model=MonitoringState)
def get_monitoring_state() -> MonitoringState:
    monitor, _, _ = _ensure_runtime()
    return monitor.snapshot()


@app.get("/pet/update", response_model=PetState)
def get_pet_update_payload() -> PetState:
    monitor, adapter, _ = _ensure_runtime()
    state = monitor.snapshot()
    status_duration_seconds = monitor.current_status_duration_seconds()
    return adapter.build_update(
        status_duration_seconds=status_duration_seconds,
        current_kpm=state.kpm_value,
        status_label=state.status.label,
    )


@app.get("/monitoring/history", response_model=list[HistoryPoint])
def get_monitoring_history(period: str = Query(default="1h")) -> list[HistoryPoint]:
    monitor, _, _ = _ensure_runtime()
    try:
        return monitor.history(period=period)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/monitoring/config", response_model=MonitoringSettings)
def get_monitoring_config() -> MonitoringSettings:
    monitor, _, _ = _ensure_runtime()
    return monitor.config()


@app.put("/monitoring/config", response_model=MonitoringSettings)
def update_monitoring_config(config: MonitoringSettings) -> MonitoringSettings:
    monitor, _, _ = _ensure_runtime()
    return monitor.update_config(config)


@app.get("/config/load", response_model=ConfigBundle)
def load_config_bundle() -> ConfigBundle:
    _, _, store = _ensure_runtime()
    return store.load_bundle()


@app.post("/config/save-profile", response_model=SaveResult)
def save_profile(profile: UserProfile) -> SaveResult:
    _, _, store = _ensure_runtime()
    store.save_profile(profile)
    return SaveResult(success=True, message="profile saved")


@app.post("/config/save-settings", response_model=SaveResult)
def save_settings(settings: MonitoringSettings) -> SaveResult:
    monitor, _, _ = _ensure_runtime()
    monitor.update_config(settings)
    return SaveResult(success=True, message="settings saved")
