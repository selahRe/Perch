from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


StatusLabel = Literal["Idle", "Relaxed", "Focused"]
PetEmotion = Literal["happy", "eat", "play", "idle"]
GenderType = Literal["male", "female", "other", "prefer_not_to_say"]
ReminderType = Literal["hydration", "stretching", "meeting", "custom"]


class PetState(BaseModel):
    visible: bool = True
    emotion: PetEmotion = "happy"
    speak: str = ""


DecisionEmotion = Literal["happy", "eat", "play"]
DecisionSource = Literal["rule", "ai", "fallback"]


class KpmAggregate(BaseModel):
    kpm_1m: int = 0
    kpm_5m: float = 0
    kpm_30m_avg: float = 0


class AppSnapshot(BaseModel):
    active_app: str | None = None
    status_label: StatusLabel = "Idle"
    status_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    status_duration_sec: int = Field(default=0, ge=0)


class DecisionContext(BaseModel):
    timestamp: datetime
    kpm: KpmAggregate
    app: AppSnapshot
    profile: "UserProfile"
    settings: "MonitoringSettings"
    session_digest: str = ""
    recent_interactions: list[str] = Field(default_factory=list)
    recent_decisions_digest: list[str] = Field(default_factory=list)
    habit_profile: dict[str, Any] = Field(default_factory=dict)


class PetDecision(BaseModel):
    visible: bool = True
    emotion: DecisionEmotion = "happy"
    speak: str = ""
    reason: str = Field(min_length=1)
    source: DecisionSource = "rule"
    durationMs: int | None = None


class PetBehaviorRule(BaseModel):
    visible: bool = True
    emotion: PetEmotion
    speak: str


class ProtocolAdapterSettings(BaseModel):
    focused_long_kpm_threshold: int = 100
    focused_long_duration_seconds: int = 1800
    cooldown_seconds: int = 90
    cooldown_fallback_speak: str = "..."
    idle: PetBehaviorRule = Field(
        default_factory=lambda: PetBehaviorRule(visible=True, emotion="idle", speak="...")
    )
    relaxed: PetBehaviorRule = Field(
        default_factory=lambda: PetBehaviorRule(
            visible=True,
            emotion="happy",
            speak="Steady pace. You're doing well.",
        )
    )
    focused: PetBehaviorRule = Field(
        default_factory=lambda: PetBehaviorRule(
            visible=True,
            emotion="play",
            speak="Nice focus streak. Keep going!",
        )
    )
    focused_long: PetBehaviorRule = Field(
        default_factory=lambda: PetBehaviorRule(
            visible=True,
            emotion="happy",
            speak="Great job! You've been focused for {status_duration_minutes} minutes!",
        )
    )


class StatusClassification(BaseModel):
    label: StatusLabel
    confidence: float = Field(ge=0.0, le=1.0)


class MonitoringSettings(BaseModel):
    reminder_types: list[ReminderType] = Field(
        default_factory=lambda: ["hydration", "stretching", "meeting"]
    )
    hydration_reminder_interval_minutes: int = 30
    stretching_reminder_interval_minutes: int = 45
    check_interval: int = 60
    pet_visible_always: bool = True
    kpm_thresholds: dict[str, int] = Field(default_factory=lambda: {"idle": 5, "focus": 50})
    idle_limit: int = 5
    focus_threshold: int = 60
    developer_apps: list[str] = Field(
        default_factory=lambda: ["Code", "Cursor", "IntelliJ IDEA", "PyCharm", "WebStorm"]
    )
    developer_focus_delta: int = 10
    protocol_adapter: ProtocolAdapterSettings = Field(default_factory=ProtocolAdapterSettings)


class ThresholdsUpdateRequest(BaseModel):
    idle_limit: int = Field(ge=0)
    focus_threshold: int = Field(gt=0)


class ReminderPreferences(BaseModel):
    hydration: bool = True
    stretching: bool = True
    meetings: bool = True


class UserProfile(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    username: str = ""
    gender: GenderType = "prefer_not_to_say"
    free_time: str = Field(default="", alias="freeTime")
    reminders: ReminderPreferences = Field(default_factory=ReminderPreferences)
    onboarding_completed: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ConfigBundle(BaseModel):
    profile: UserProfile
    settings: MonitoringSettings


class SaveResult(BaseModel):
    success: bool
    message: str


class MonitoringState(BaseModel):
    timestamp: datetime
    kpm_value: int
    status: StatusClassification
    app_name: str | None = None
    current_minute_count: int = 0
    listener_running: bool = False
    listener_error: str | None = None
    last_key_pressed_at: datetime | None = None
    last_minute_completed_at: datetime | None = None
    sampling_interval_seconds: int = 60


class HistoryPoint(BaseModel):
    time: str
    kpm: int
    label: StatusLabel
    app_name: str | None = None


DecisionContext.model_rebuild()