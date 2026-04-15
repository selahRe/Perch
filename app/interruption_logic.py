from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from collections import deque

from .models import DecisionContext, PetDecision


@dataclass(frozen=True)
class InterruptionResult:
    allow_speak: bool
    blocked_by: str | None = None


class InterruptionLogic:
    """
    Nudge policy agent:
    - High-frequency typing => silent animation update only.
    - Input drop / stall => allow speak bubble.
    """

    def __init__(self) -> None:
        self._recent_emits: deque[datetime] = deque()
        self._priority_exceptions = {"meeting_soon", "first_meeting_of_day"}

    def evaluate(
        self,
        *,
        context: DecisionContext,
        decision: PetDecision,
        previous_kpm: int,
        now: datetime | None = None,
    ) -> InterruptionResult:
        now = now or datetime.now(timezone.utc)
        self._prune(now)

        kpm_1m = context.kpm.kpm_1m
        kpm_5m = context.kpm.kpm_5m

        # Priority exceptions: allow critical reminders even during deep work.
        if decision.reason in self._priority_exceptions:
            return InterruptionResult(allow_speak=True)

        # Deep work protection: do not interrupt high-frequency typing.
        if kpm_1m >= 95 and kpm_5m >= 85:
            return InterruptionResult(allow_speak=False, blocked_by="deep_work_protection")

        # If user just dropped from high input to low input, allow timely nudges.
        if previous_kpm >= 95 and kpm_1m <= 20:
            return InterruptionResult(allow_speak=True)

        # Idle/struggle windows can speak; otherwise preserve subtle behavior.
        if kpm_1m <= 15 or (kpm_1m <= 25 and kpm_5m <= 30):
            return InterruptionResult(allow_speak=True)

        return InterruptionResult(allow_speak=False, blocked_by="typing_active")

    def mark_emit(self, at: datetime | None = None) -> None:
        self._recent_emits.append(at or datetime.now(timezone.utc))

    def _prune(self, now: datetime) -> None:
        cutoff = now - timedelta(minutes=10)
        while self._recent_emits and self._recent_emits[0] < cutoff:
            self._recent_emits.popleft()
