from contextlib import asynccontextmanager

from fastapi import FastAPI

from .models import MonitoringConfig, MonitoringHistoryResponse, MonitoringSnapshot, PetState
from .monitoring import KeyboardMonitor


keyboard_monitor = KeyboardMonitor()


@asynccontextmanager
async def lifespan(app: FastAPI):
    keyboard_monitor.start()
    app.state.keyboard_monitor = keyboard_monitor
    yield
    keyboard_monitor.stop()


app = FastAPI(title="Perch Local API", version="0.2.0", lifespan=lifespan)

# In-memory state for local Electron integration.
current_state = PetState()


@app.get("/state", response_model=PetState)
def get_state() -> PetState:
    return current_state


@app.get("/monitoring/state", response_model=MonitoringSnapshot)
def get_monitoring_state() -> MonitoringSnapshot:
    return keyboard_monitor.snapshot()


@app.get("/monitoring/history", response_model=MonitoringHistoryResponse)
def get_monitoring_history(limit: int = 60) -> MonitoringHistoryResponse:
    return MonitoringHistoryResponse(items=keyboard_monitor.repository.load_recent_snapshots(limit=limit))


@app.get("/monitoring/config", response_model=MonitoringConfig)
def get_monitoring_config() -> MonitoringConfig:
    return keyboard_monitor.config()


@app.put("/monitoring/config", response_model=MonitoringConfig)
def update_monitoring_config(config: MonitoringConfig) -> MonitoringConfig:
    return keyboard_monitor.update_config(config)
