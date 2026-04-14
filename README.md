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
./.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Endpoints:

- `GET /state`: current pet UI state
- `GET /monitoring/state`: latest completed 60-second KPM and classification
- `GET /monitoring/history?period=1h|24h`: historical KPM points for visualization
- `GET /monitoring/config`: current classification thresholds
- `PUT /monitoring/config`: update classification thresholds
- `GET /pet/update`: protocol-adapted payload (`visible`, `emotion`, `speak`) for frontend view updates
- `GET /config/load`: load onboarding profile and settings bundle
- `POST /config/save-profile`: save onboarding profile JSON
- `POST /config/save-settings`: save settings JSON

Monitoring details:

- Global key events are captured by a non-blocking listener.
- KPM is computed every 60 seconds and triggers a callback to storage/classification.
- Data is persisted in SQLite table `monitoring_history` with 24-hour retention cleanup.
- Thresholds and pet adapter behavior are loaded from `~/.perch/settings.json` (or `~/Documents/.perch/settings.json` when available).
- `~/.perch/profile.json` stores onboarding data.
- Pet adapter behavior is configurable in `settings.json > protocol_adapter`:
  - Per-label output rules (`idle`, `relaxed`, `focused`, `focused_long`) for `visible`, `emotion`, and `speak` template.
  - Long-focus thresholds (`focused_long_kpm_threshold`, `focused_long_duration_seconds`).
  - Cooldown controls (`cooldown_seconds`, `cooldown_fallback_speak`).

Note:

- On macOS, `pynput` needs Accessibility permission for the terminal or editor to capture global keyboard events.
