from contextlib import asynccontextmanager
from pathlib import Path
import threading

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from .agent_runtime import AgentRuntime
from .config_store import ConfigStore
from .env_loader import load_env_file
from .models import (
    ConfigBundle,
    HistoryPoint,
    MonitoringSettings,
    MonitoringState,
    PetDecision,
    PetState,
    PetUpdatePayload,
    SaveResult,
    ThresholdsUpdateRequest,
    UserProfile,
)
from .monitoring import KeyboardMonitor, RETENTION_HOURS
from .protocol_adapter import PetUpdateAdapter
from .reminder_manager import ReminderManager

load_env_file(Path(__file__).resolve().parents[1] / ".env")


keyboard_monitor: KeyboardMonitor | None = None
pet_update_adapter: PetUpdateAdapter | None = None
config_store: ConfigStore | None = None
reminder_manager: ReminderManager | None = None
agent_runtime: AgentRuntime | None = None
_runtime_lock = threading.Lock()


def _ensure_runtime() -> tuple[KeyboardMonitor, PetUpdateAdapter, ConfigStore, ReminderManager, AgentRuntime]:
    global keyboard_monitor, pet_update_adapter, config_store, reminder_manager, agent_runtime
    with _runtime_lock:
        if keyboard_monitor is None:
            keyboard_monitor = KeyboardMonitor()
        if reminder_manager is None:
            reminder_manager = ReminderManager(keyboard_monitor.settings_store)
            active_reminder_manager = reminder_manager
            monitor = keyboard_monitor

            def on_minute_complete(state: MonitoringState) -> None:
                monitor.repository.save_minute_record(
                    timestamp=state.timestamp,
                    kpm_value=state.kpm_value,
                    status_label=state.status.label,
                    app_name=state.app_name,
                )
                monitor.repository.cleanup_older_than(hours=RETENTION_HOURS)
                active_reminder_manager.process_minute(state)

            keyboard_monitor.on_minute_complete = on_minute_complete
        if pet_update_adapter is None:
            pet_update_adapter = PetUpdateAdapter(keyboard_monitor.settings_store)
        if config_store is None:
            config_store = ConfigStore(keyboard_monitor.settings_store)
        if agent_runtime is None:
            agent_runtime = AgentRuntime(keyboard_monitor.repository)
        return keyboard_monitor, pet_update_adapter, config_store, reminder_manager, agent_runtime


@asynccontextmanager
async def lifespan(app: FastAPI):
    monitor, _, _, _, _ = _ensure_runtime()
    monitor.start()
    yield
    monitor.stop()


app = FastAPI(title="Perch Local API", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory state for local Electron integration.
current_state = PetState()


@app.get("/state", response_model=PetState)
def get_state() -> PetState:
    return current_state


@app.get("/monitoring/state", response_model=MonitoringState)
def get_monitoring_state() -> MonitoringState:
    monitor, _, _, _, _ = _ensure_runtime()
    return monitor.snapshot()


@app.get("/pet/update", response_model=PetUpdatePayload)
def get_pet_update_payload() -> PetUpdatePayload:
    monitor, _, store, reminders, runtime = _ensure_runtime()
    reminder_update = reminders.pop_pending_update()
    if reminder_update is not None:
        return PetUpdatePayload(
            visible=reminder_update.visible,
            emotion="happy" if reminder_update.emotion == "idle" else reminder_update.emotion,
            speak=reminder_update.speak,
            reason="reminder_pending",
            durationMs=4000,
        )

    state = monitor.snapshot()
    bundle = store.load_bundle()
    decision = runtime.run_cycle(
        state=state,
        profile=bundle.profile,
        settings=bundle.settings,
    )
    return runtime.as_pet_update_payload(decision)


@app.get("/monitoring/history", response_model=list[HistoryPoint])
def get_monitoring_history(period: str = Query(default="1h")) -> list[HistoryPoint]:
    monitor, _, _, _, _ = _ensure_runtime()
    try:
        return monitor.history(period=period)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/monitoring/config", response_model=MonitoringSettings)
def get_monitoring_config() -> MonitoringSettings:
    monitor, _, _, _, _ = _ensure_runtime()
    return monitor.config()


@app.put("/monitoring/config", response_model=MonitoringSettings)
def update_monitoring_config(config: MonitoringSettings) -> MonitoringSettings:
    monitor, _, _, _, _ = _ensure_runtime()
    return monitor.update_config(config)


@app.put("/settings/thresholds", response_model=MonitoringSettings)
def update_thresholds(payload: ThresholdsUpdateRequest) -> MonitoringSettings:
    monitor, _, _, _, _ = _ensure_runtime()
    settings = monitor.config()
    settings.idle_limit = payload.idle_limit
    settings.focus_threshold = payload.focus_threshold
    settings.kpm_thresholds["idle"] = payload.idle_limit
    settings.kpm_thresholds["focus"] = payload.focus_threshold
    return monitor.update_config(settings)


@app.get("/config/load", response_model=ConfigBundle)
def load_config_bundle() -> ConfigBundle:
    _, _, store, _, _ = _ensure_runtime()
    return store.load_bundle()


@app.post("/config/save-profile", response_model=SaveResult)
def save_profile(profile: UserProfile) -> SaveResult:
    _, _, store, _, _ = _ensure_runtime()
    store.save_profile(profile)
    return SaveResult(success=True, message="profile saved")


@app.post("/config/save-settings", response_model=SaveResult)
def save_settings(settings: MonitoringSettings) -> SaveResult:
    monitor, _, _, _, _ = _ensure_runtime()
    monitor.update_config(settings)
    return SaveResult(success=True, message="settings saved")


@app.get("/ai/decision/latest", response_model=PetDecision | None)
def get_latest_decision() -> PetDecision | None:
    monitor, _, _, _, _ = _ensure_runtime()
    latest = monitor.repository.load_latest_decision()
    if latest is None:
        return None
    return PetDecision.model_validate(latest["decision"])


@app.get("/ai/decision/history")
def get_decision_history(limit: int = Query(default=50, ge=1, le=200)) -> list[dict]:
    monitor, _, _, _, _ = _ensure_runtime()
    return monitor.repository.load_decision_history(limit=limit)


@app.post("/ai/demo/reset-session", response_model=SaveResult)
def reset_ai_demo_session() -> SaveResult:
    _, _, _, _, runtime = _ensure_runtime()
    runtime.reset_demo_session()
    return SaveResult(success=True, message="ai demo session reset")


@app.get("/debug/thresholds", response_class=HTMLResponse)
def debug_thresholds_page() -> HTMLResponse:
        html = """
<!doctype html>
<html lang="en">
    <head>
        <meta charset="UTF-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0" />
        <title>Perch Threshold Tuner</title>
        <style>
            :root {
                --bg: #f6f7fb;
                --card: #ffffff;
                --text: #23263a;
                --muted: #68708a;
                --accent: #2f6bff;
                --border: #e4e8f3;
            }
            * { box-sizing: border-box; }
            body {
                margin: 0;
                font-family: ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
                background: radial-gradient(circle at top right, #e8eeff 0%, var(--bg) 45%);
                color: var(--text);
            }
            .wrap {
                width: min(900px, calc(100vw - 32px));
                margin: 24px auto;
                display: grid;
                gap: 16px;
            }
            .card {
                background: var(--card);
                border: 1px solid var(--border);
                border-radius: 16px;
                padding: 16px;
                box-shadow: 0 8px 20px rgba(0, 0, 0, 0.04);
            }
            h1 {
                margin: 0 0 8px;
                font-size: 24px;
            }
            .hint {
                color: var(--muted);
                margin: 0;
            }
            .grid {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 16px;
            }
            .row {
                display: grid;
                gap: 8px;
                margin-bottom: 14px;
            }
            label {
                font-weight: 600;
            }
            input[type='range'] {
                width: 100%;
            }
            .value {
                font-size: 14px;
                color: var(--muted);
            }
            .pill {
                display: inline-block;
                padding: 4px 10px;
                border-radius: 999px;
                font-weight: 700;
            }
            .Idle { background: #eceff8; color: #4c5777; }
            .Relaxed { background: #eaf7ea; color: #237f3c; }
            .Focused { background: #e8efff; color: #1f55d6; }
            .metric {
                display: grid;
                gap: 8px;
                font-size: 15px;
            }
            .metric span { color: var(--muted); }
            .small {
                font-size: 13px;
                color: var(--muted);
            }
            @media (max-width: 720px) {
                .grid { grid-template-columns: 1fr; }
            }
        </style>
    </head>
    <body>
        <div class="wrap">
            <div class="card">
                <h1>Perch State Classification Tuner</h1>
                <p class="hint">Slide thresholds and watch status updates in real time. Changes are persisted via <code>PUT /settings/thresholds</code>.</p>
            </div>

            <div class="grid">
                <div class="card">
                    <div class="row">
                        <label for="idleRange">Idle limit</label>
                        <input id="idleRange" type="range" min="0" max="30" value="5" />
                        <div id="idleValue" class="value">5</div>
                    </div>

                    <div class="row">
                        <label for="focusRange">Focus threshold</label>
                        <input id="focusRange" type="range" min="10" max="250" value="60" />
                        <div id="focusValue" class="value">60</div>
                    </div>

                    <div class="small" id="saveStatus">Waiting for change...</div>
                </div>

                <div class="card">
                    <div class="metric">
                        <div>Status: <span id="statusPill" class="pill Idle">Idle</span></div>
                        <div>KPM: <strong id="kpmText">0</strong></div>
                        <div>App: <strong id="appText">unknown</strong></div>
                        <div>Listener: <strong id="listenerText">unknown</strong></div>
                        <div>Confidence: <strong id="confidenceText">0.000</strong></div>
                        <div>Last sample: <strong id="sampleText">-</strong></div>
                        <div>Rule explain: <strong id="ruleExplainText">KPM=0, idle&lt;5, focus&gt;=60 -> Idle</strong></div>
                    </div>
                </div>

                <div class="card">
                    <div class="metric">
                        <div>Pet visible: <strong id="petVisibleText">true</strong></div>
                        <div>Pet emotion: <strong id="petEmotionText">happy</strong></div>
                        <div>Pet speak: <strong id="petSpeakText">...</strong></div>
                    </div>
                </div>
            </div>
        </div>

        <script>
            const idleRange = document.getElementById('idleRange');
            const focusRange = document.getElementById('focusRange');
            const idleValue = document.getElementById('idleValue');
            const focusValue = document.getElementById('focusValue');
            const saveStatus = document.getElementById('saveStatus');

            const statusPill = document.getElementById('statusPill');
            const kpmText = document.getElementById('kpmText');
            const appText = document.getElementById('appText');
            const listenerText = document.getElementById('listenerText');
            const confidenceText = document.getElementById('confidenceText');
            const sampleText = document.getElementById('sampleText');
            const ruleExplainText = document.getElementById('ruleExplainText');

            const petVisibleText = document.getElementById('petVisibleText');
            const petEmotionText = document.getElementById('petEmotionText');
            const petSpeakText = document.getElementById('petSpeakText');

            let saveTimer = null;

            function bindRangeLabels() {
                idleValue.textContent = idleRange.value;
                focusValue.textContent = focusRange.value;
            }

            async function loadInitialConfig() {
                try {
                    const response = await fetch('/monitoring/config');
                    if (!response.ok) return;
                    const cfg = await response.json();
                    const idle = cfg.idle_limit ?? cfg.kpm_thresholds?.idle ?? 5;
                    const focus = cfg.focus_threshold ?? cfg.kpm_thresholds?.focus ?? 60;
                    idleRange.value = String(idle);
                    focusRange.value = String(focus);
                    bindRangeLabels();
                } catch (_) {
                    saveStatus.textContent = 'Failed to load config.';
                }
            }

            async function saveThresholds() {
                const payload = {
                    idle_limit: Number(idleRange.value),
                    focus_threshold: Number(focusRange.value),
                };
                saveStatus.textContent = 'Saving...';
                try {
                    const response = await fetch('/settings/thresholds', {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload),
                    });
                    if (!response.ok) {
                        saveStatus.textContent = 'Save failed.';
                        return;
                    }
                    saveStatus.textContent = `Saved idle=${payload.idle_limit}, focus=${payload.focus_threshold}`;
                } catch (_) {
                    saveStatus.textContent = 'Save failed.';
                }
            }

            function scheduleSave() {
                bindRangeLabels();
                if (saveTimer) {
                    clearTimeout(saveTimer);
                }
                saveTimer = setTimeout(saveThresholds, 180);
            }

            async function refreshState() {
                try {
                    const [stateResponse, petResponse] = await Promise.all([
                        fetch('/monitoring/state'),
                        fetch('/pet/update'),
                    ]);

                    if (!stateResponse.ok) return;
                    const state = await stateResponse.json();

                    const label = state?.status?.label || 'Idle';
                    statusPill.textContent = label;
                    statusPill.className = `pill ${label}`;
                    kpmText.textContent = String(state?.kpm_value ?? 0);
                    appText.textContent = state?.app_name || 'unknown';
                    listenerText.textContent = state?.listener_running ? 'running' : 'stopped';
                    confidenceText.textContent = Number(state?.status?.confidence ?? 0).toFixed(3);
                    sampleText.textContent = state?.last_minute_completed_at || '-';

                    const kpm = Number(state?.kpm_value ?? 0);
                    const idle = Number(idleRange.value);
                    const focus = Number(focusRange.value);
                    const labelFromState = state?.status?.label || 'Idle';
                    ruleExplainText.textContent = `KPM=${kpm}, idle<${idle}, focus>=${focus} -> ${labelFromState}`;

                    if (petResponse.ok) {
                        const pet = await petResponse.json();
                        petVisibleText.textContent = String(Boolean(pet?.visible));
                        petEmotionText.textContent = pet?.emotion || 'unknown';
                        petSpeakText.textContent = pet?.speak === '' ? '(empty)' : (pet?.speak || '(none)');
                    }
                } catch (_) {
                    listenerText.textContent = 'unreachable';
                }
            }

            idleRange.addEventListener('input', scheduleSave);
            focusRange.addEventListener('input', scheduleSave);

            loadInitialConfig();
            refreshState();
            setInterval(refreshState, 1000);
        </script>
    </body>
</html>
        """
        return HTMLResponse(content=html)