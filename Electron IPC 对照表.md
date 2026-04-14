# Electron IPC

This document is the frontend handoff reference for Perch's backend APIs and IPC-style payloads.

## 1. Source of Truth

- Backend runtime: Python FastAPI service in this repository.
- Frontend expectation: Electron renderer consumes JSON payloads and maps them to UI state.
- Shared pet UI contract:
  - `visible`: show or hide the pet.
  - `emotion`: `happy` | `eat` | `play` | `idle`.
  - `speak`: empty string means hide the bubble.

## 2. Recommended Frontend API Flow

1. Renderer starts and emits `app:ready`.
2. Backend returns initial config bundle and current pet payload.
3. Renderer listens for `pet:update` and applies UI changes.
4. Renderer saves onboarding and settings through config endpoints.

## 3. Backend Endpoints

| Endpoint | Method | Direction | Purpose | Response |
|---|---:|---|---|---|
| `/state` | GET | Backend -> Frontend | Current base pet state | `PetState` |
| `/monitoring/state` | GET | Backend -> Frontend | Latest completed 60-second monitoring snapshot | `MonitoringState` |
| `/monitoring/history?period=1h|24h` | GET | Backend -> Frontend | Historical KPM points for charts | `HistoryPoint[]` |
| `/monitoring/config` | GET | Backend -> Frontend | Current monitoring thresholds | `MonitoringSettings` |
| `/monitoring/config` | PUT | Frontend -> Backend | Update monitoring thresholds | `MonitoringSettings` |
| `/pet/update` | GET | Backend -> Frontend | Protocol-adapted payload for UI updates | `PetState` |
| `/config/load` | GET | Backend -> Frontend | Load onboarding profile + settings | `ConfigBundle` |
| `/config/save-profile` | POST | Frontend -> Backend | Save onboarding profile | `SaveResult` |
| `/config/save-settings` | POST | Frontend -> Backend | Save settings | `SaveResult` |

## 4. IPC/JSON Contract

### 4.1 `pet:update`

Use this as the primary UI update payload.

```json
{
  "visible": true,
  "emotion": "play",
  "speak": "来玩吧！"
}
```

Rules:

- `visible = true` shows the pet.
- `visible = false` hides the pet.
- `emotion` controls the animation state.
- `speak = ""` hides the bubble.

### 4.2 `app:ready`

Frontend bootstraps and requests initial state.

```json
{
  "timestamp": 1710000000000
}
```

Expected backend follow-up payloads:

- `ConfigBundle` from `/config/load`
- `PetState` from `/pet/update`

### 4.3 `profile:save`

Used by onboarding UI.

```json
{
  "username": "Chloe",
  "gender": "female",
  "onboarding_completed": true,
  "created_at": "2026-04-14T10:00:00Z"
}
```

### 4.4 `settings:save`

Used by settings panel.

```json
{
  "reminder_types": ["hydration", "stretching"],
  "check_interval": 60,
  "pet_visible_always": true,
  "kpm_thresholds": {
    "idle": 5,
    "focus": 50
  }
}
```

## 5. `pet:update` Mapping Guide

| Condition | UI Result |
|---|---|
| `visible = true` | Show pet |
| `visible = false` | Hide pet |
| `emotion = happy` | Happy animation |
| `emotion = eat` | Eat animation |
| `emotion = play` | Play animation |
| `emotion = idle` | Idle animation |
| `speak != ""` | Show bubble text |
| `speak = ""` | Hide bubble |

## 6. Config Storage

- Profile file: `.perch/profile.json`
- Settings file: `.perch/settings.json`
- Default location: `~/Documents/.perch/` when available, otherwise `~/.perch/`

## 7. Minimal Frontend API Surface

Suggested preload API:

```ts
window.electronAPI = {
  sendAppReady(payload),
  saveProfile(profile),
  saveSettings(settings),
  onPetUpdate(callback),
  onConfigLoaded(callback),
}
```

## 8. Notes for Frontend Implementers

- Treat `pet:update` as the only required real-time event for MVP.
- Use `/config/load` on startup to hydrate renderer state.
- Use `/config/save-profile` and `/config/save-settings` for persistence.
- Use `/monitoring/history?period=1h` for chart preview and `/monitoring/history?period=24h` for daily trends.
