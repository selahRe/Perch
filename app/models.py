from datetime import datetime
from typing import Literal

from pydantic import BaseModel


BehaviorState = Literal["focused", "relaxed", "idle"]


class PetState(BaseModel):
    visible: bool = True
    emotion: Literal["happy", "eat", "play"] = "happy"
    speak: str = ""


class MonitoringSnapshot(BaseModel):
    captured_at: datetime
    kpm: int
    behavior_state: BehaviorState
    key_presses_last_minute: int
    total_key_presses: int
    window_seconds: int = 60


class MonitoringConfig(BaseModel):
    idle_kpm_threshold: int = 0
    focused_kpm_threshold: int = 120


class MonitoringHistoryResponse(BaseModel):
    items: list[MonitoringSnapshot]
