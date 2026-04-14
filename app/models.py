from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


StatusLabel = Literal["Idle", "Relaxed", "Focused"]
PetEmotion = Literal["happy", "eat", "play", "idle"]


class PetState(BaseModel):
    visible: bool = True
    emotion: PetEmotion = "happy"
    speak: str = ""


class PetBehaviorRule(BaseModel):
    visible: bool = True
    emotion: PetEmotion
    speak: str


class ProtocolAdapterSettings(BaseModel):
    focused_long_kpm_threshold: int = 100
    focused_long_duration_seconds: int = 1800
    cooldown_seconds: int = 90
    cooldown_fallback_speak: str = "..."
    idle: PetBehaviorRule = PetBehaviorRule(visible=True, emotion="idle", speak="...")
    relaxed: PetBehaviorRule = PetBehaviorRule(
        visible=True,
        emotion="happy",
        speak="Steady pace. You're doing well.",
    )
    focused: PetBehaviorRule = PetBehaviorRule(
        visible=True,
        emotion="play",
        speak="Nice focus streak. Keep going!",
    )
    focused_long: PetBehaviorRule = PetBehaviorRule(
        visible=True,
        emotion="happy",
        speak="Great job! You've been focused for {status_duration_minutes} minutes!",
    )


class StatusClassification(BaseModel):
    label: StatusLabel
    confidence: float = Field(ge=0.0, le=1.0)


class MonitoringSettings(BaseModel):
    idle_limit: int = 5
    focus_threshold: int = 60
    developer_apps: list[str] = ["Code", "Cursor", "IntelliJ IDEA", "PyCharm", "WebStorm"]
    developer_focus_delta: int = 10
    protocol_adapter: ProtocolAdapterSettings = ProtocolAdapterSettings()


class MonitoringState(BaseModel):
    timestamp: datetime
    kpm_value: int
    status: StatusClassification
    app_name: str | None = None


class HistoryPoint(BaseModel):
    time: str
    kpm: int
    label: StatusLabel
