from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


StatusLabel = Literal["Idle", "Relaxed", "Focused"]


class PetState(BaseModel):
    visible: bool = True
    emotion: Literal["happy", "eat", "play"] = "happy"
    speak: str = ""


class StatusClassification(BaseModel):
    label: StatusLabel
    confidence: float = Field(ge=0.0, le=1.0)


class MonitoringSettings(BaseModel):
    idle_limit: int = 5
    focus_threshold: int = 60
    developer_apps: list[str] = ["Code", "Cursor", "IntelliJ IDEA", "PyCharm", "WebStorm"]
    developer_focus_delta: int = 10


class MonitoringState(BaseModel):
    timestamp: datetime
    kpm_value: int
    status: StatusClassification
    app_name: str | None = None


class HistoryPoint(BaseModel):
    time: str
    kpm: int
    label: StatusLabel
