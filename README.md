# Perch

## Python Backend

The local FastAPI backend now lives at the repository root.

Setup:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Run:

```bash
./.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## Electron Bridge (Issue #5)

`frontend/electron/main.js` now manages a bridge between Electron main process and backend process.

Command flow:

- Startup: Electron launches backend by `spawn(...)`.
- Handshake: backend launcher chooses an available port (starting from `8000`) and emits a ready signal on stdout.
- Loop: backend emits `pet:update` and `monitoring:state` events on stdout.
- Render: Electron forwards those events via `mainWindow.webContents.send(...)` to React.

- Lifecycle guardianship:
  - On app startup, Electron checks `GET /monitoring/state` first.
  - If backend is already up, Electron reuses it and does not spawn a second backend process.
  - If Electron spawned backend itself, it terminates that managed process on app quit.
- Environment switching:
  - Development mode (`!app.isPackaged` or `NODE_ENV=development`): runs `python backend/main.py`.
  - Production mode: runs packaged backend executable.
  - About `.exe`: this suffix is Windows-only. On macOS/Linux it is typically `backend` without `.exe`.
- Optional overrides:
  - `PERCH_BACKEND_PYTHON`: python command path used in development.
  - `PERCH_BACKEND_SCRIPT_PATH`: backend script path used in development.
  - `PERCH_BACKEND_EXECUTABLE_PATH`: explicit backend executable path used in production.

Default development script entry is `backend/main.py`.

Endpoints:

- `GET /state`: current pet UI state
- `GET /monitoring/state`: live monitoring snapshot (KPM, status label, confidence, app, listener info)
- `GET /monitoring/history?period=1h|24h`: historical KPM points for visualization
- `GET /monitoring/config`: current classification thresholds
- `PUT /monitoring/config`: update classification thresholds
- `PUT /settings/thresholds`: update only `idle_limit` and `focus_threshold` (and synced `kpm_thresholds`)
- `GET /pet/update`: protocol-adapted payload (`visible`, `emotion`, `speak`) for frontend view updates
- `GET /config/load`: load onboarding profile and settings bundle
- `POST /config/save-profile`: save onboarding profile JSON
- `POST /config/save-settings`: save settings JSON
- `GET /ai/decision/latest`: latest AI/rule decision payload
- `GET /ai/decision/history?limit=50`: recent decision history with observability fields (`source`, `llm_attempted`, `llm_success`, `blocked_by`)
- `POST /ai/demo/reset-session`: reset first-greeting/demo session state
- `GET /ai/calendar/next`: inspect next meeting from configured calendar provider
- `WS /ws/pet/update`: websocket push channel for pet updates
- `GET /debug/thresholds`: built-in HTML tuner page for live threshold adjustment

State classification output:

- Current states are exactly: `Idle`, `Relaxed`, `Focused`.
- The classifier returns a standardized object:
  - `label`
  - `confidence` (0.0 to 1.0)

Pet status output:

- Yes, the project outputs pet state for frontend rendering.
- Use `GET /pet/update`, which returns:
  - `visible`
  - `emotion`
  - `speak`

Debug threshold page behavior:

- Open `http://127.0.0.1:8000/debug/thresholds`.
- Sliding `Idle limit` and `Focus threshold` triggers `PUT /settings/thresholds` automatically.
- Threshold changes are persisted by the backend settings store (not just in-memory), so they affect later classification requests.
- The page also polls `GET /monitoring/state` every second to show status changes in real time.

Monitoring details:

- Global key events are captured by a non-blocking listener.
- KPM is computed every 60 seconds and triggers a callback to storage/classification.
- Data is persisted in SQLite table `monitoring_history` with 24-hour retention cleanup.
- Historical response format used by visualization endpoint:
  - `[{"time": "10:01", "kpm": 45, "label": "Relaxed", "app_name": "Code"}, ...]`
- Thresholds and pet adapter behavior are loaded from `~/.perch/settings.json` (or `~/Documents/.perch/settings.json` when available).
- `~/.perch/profile.json` stores onboarding data.
- Pet adapter behavior is configurable in `settings.json > protocol_adapter`:
  - Per-label output rules (`idle`, `relaxed`, `focused`, `focused_long`) for `visible`, `emotion`, and `speak` template.
  - Long-focus thresholds (`focused_long_kpm_threshold`, `focused_long_duration_seconds`).
  - Cooldown controls (`cooldown_seconds`, `cooldown_fallback_speak`).

Note:

- On macOS, `pynput` needs Accessibility permission for the terminal or editor to capture global keyboard events.

## AI Runtime Extras

### Interruption policy (Issue #8)

- Busy typing (high KPM) defaults to silent updates (`speak=""`) to protect deep work.
- Input drop / low-frequency windows can emit nudges.
- Meeting reminders are priority exceptions and can still speak during deep work.

### Mock calendar provider (Issue #9)

Enable calendar simulation in `.env`:

```bash
PERCH_CALENDAR_MOCK_ENABLED=true
PERCH_CALENDAR_MOCK_NEXT_MEETING_IN_MINUTES=5
PERCH_CALENDAR_MOCK_NEXT_MEETING_TITLE=Design Sync
```

Or point to a JSON file:

```bash
PERCH_CALENDAR_MOCK_ENABLED=true
PERCH_CALENDAR_MOCK_FILE=/absolute/path/to/calendar_mock.json
```

See `calendar_mock.example.json` for schema.

### Demo chat mode

For classroom demos, disable chat cooldown/limits:

```bash
PERCH_DEMO_CHAT_MODE=true
```
