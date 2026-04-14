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
- `GET /monitoring/state`: current KPM and behavior classification
- `GET /monitoring/history?limit=60`: historical KPM snapshots for charts
- `GET /monitoring/config`: current classification thresholds
- `PUT /monitoring/config`: update classification thresholds

Note:

- On macOS, `pynput` needs Accessibility permission for the terminal or editor to capture global keyboard events.
