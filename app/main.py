from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query

from .models import HistoryPoint, MonitoringSettings, MonitoringState, PetState
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


@app.get("/monitoring/state", response_model=MonitoringState)
def get_monitoring_state() -> MonitoringState:
    return keyboard_monitor.snapshot()


@app.get("/monitoring/history", response_model=list[HistoryPoint])
def get_monitoring_history(period: str = Query(default="1h")) -> list[HistoryPoint]:
    try:
        return keyboard_monitor.history(period=period)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/monitoring/config", response_model=MonitoringSettings)
def get_monitoring_config() -> MonitoringSettings:
    return keyboard_monitor.config()


@app.put("/monitoring/config", response_model=MonitoringSettings)
def update_monitoring_config(config: MonitoringSettings) -> MonitoringSettings:
    return keyboard_monitor.update_config(config)
