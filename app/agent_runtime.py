from __future__ import annotations

import hashlib
import json
import math
import os
import time
import asyncio
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx

from .models import AppSnapshot, DecisionContext, KpmAggregate, MonitoringState, PetDecision, PetState, UserProfile
from .storage import MetricsRepository

OBSERVATION_WINDOW_MINUTES = 30
SESSION_DIGEST_INTERVAL_MINUTES = 30
MAX_RECENT_DECISION_DIGESTS = 5
MAX_RECENT_INTERACTIONS = 10

INPUT_TOKEN_BUDGET = 800
OUTPUT_TOKEN_BUDGET = 120
MAX_AI_CALLS_PER_HOUR = 30
MAX_AI_TOKENS_PER_HOUR = 20_000
AI_TIMEOUT_SECONDS = 2.5
DECISION_MIN_INTERVAL_SECONDS = 15
SAME_REASON_COOLDOWN_SECONDS = 90
MAX_SPEAK_PER_10MIN = 6

AI_GAIN_REASONS = {"focused_long", "afternoon_idle_pattern", "encourage"}

TEMPLATE_LIBRARY: dict[str, str] = {
    "idle": "先休息一下也不错，准备好再继续。",
    "focused_long": "你已经连续专注很久了，喝口水伸展一下会更稳。",
    "afternoon_idle_pattern": "最近你常在下午放慢节奏，要不要先拆个小任务热身？",
    "encourage": "你已经在稳定推进了，保持这个节奏就很好。",
    "hydration_urgent": "补充点水分吧，身体会感谢你。",
}


@dataclass
class Observation:
    timestamp: datetime
    state: MonitoringState


def _estimate_tokens(text: str) -> int:
    return max(1, math.ceil(len(text) / 4))


class ObservationStore:
    def __init__(self) -> None:
        self._items: deque[Observation] = deque()

    def add(self, state: MonitoringState) -> None:
        now = state.timestamp.astimezone(timezone.utc)
        self._items.append(Observation(timestamp=now, state=state))
        cutoff = now - timedelta(minutes=OBSERVATION_WINDOW_MINUTES)
        while self._items and self._items[0].timestamp < cutoff:
            self._items.popleft()

    def all(self) -> list[Observation]:
        return list(self._items)

    def kpm_values(self, window_minutes: int) -> list[int]:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
        return [item.state.kpm_value for item in self._items if item.timestamp >= cutoff]


class SessionDigest:
    def __init__(self) -> None:
        self._last_digest_at: datetime | None = None
        self._latest_digest: str = ""

    def maybe_update(self, observations: list[Observation], habit_profile: dict) -> str:
        if not observations:
            return self._latest_digest
        now = datetime.now(timezone.utc)
        if self._last_digest_at and (now - self._last_digest_at) < timedelta(
            minutes=SESSION_DIGEST_INTERVAL_MINUTES
        ):
            return self._latest_digest
        focus_minutes = sum(1 for item in observations if item.state.status.label == "Focused")
        idle_minutes = sum(1 for item in observations if item.state.status.label == "Idle")
        app_name = observations[-1].state.app_name or "未知应用"
        focus_hours = ",".join(str(hour) for hour in habit_profile.get("focus_hours", [])[:3]) or "无"
        digest = (
            f"近30分钟专注{focus_minutes}分，空闲{idle_minutes}分；主要在{app_name}。"
            f"常见高效时段:{focus_hours}。"
        )
        self._latest_digest = digest[:50]
        self._last_digest_at = now
        return self._latest_digest


class HabitProfile:
    def __init__(self, repository: MetricsRepository) -> None:
        self._repository = repository
        self._profile = repository.load_habit_profile()
        self._last_persisted_at: datetime | None = None

    def update(self, state: MonitoringState) -> dict:
        hour = state.timestamp.astimezone().hour
        focus = set(self._profile.get("focus_hours", []))
        idle = set(self._profile.get("idle_hours", []))
        if state.status.label == "Focused":
            focus.add(hour)
        if state.status.label == "Idle":
            idle.add(hour)
        self._profile = {
            "focus_hours": sorted(focus)[:24],
            "idle_hours": sorted(idle)[:24],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        now = datetime.now(timezone.utc)
        if self._last_persisted_at is None or (now - self._last_persisted_at) >= timedelta(minutes=5):
            self._repository.save_habit_profile(self._profile)
            self._last_persisted_at = now
        return self._profile

    @property
    def payload(self) -> dict:
        return self._profile


class AgentRuntime:
    def __init__(self, repository: MetricsRepository) -> None:
        self._repository = repository
        self._observation_store = ObservationStore()
        self._session_digest = SessionDigest()
        self._habit_profile = HabitProfile(repository)
        self._recent_decisions: deque[PetDecision] = deque(maxlen=MAX_RECENT_DECISION_DIGESTS)
        self._recent_interactions: deque[str] = deque(maxlen=MAX_RECENT_INTERACTIONS)
        self._decision_timestamps: deque[datetime] = deque()
        self._ai_call_timestamps: deque[datetime] = deque()
        self._ai_token_usage: deque[tuple[datetime, int]] = deque()
        self._last_emit_at: datetime | None = None
        self._last_reason_at: dict[str, datetime] = {}

    def run_cycle(self, state: MonitoringState, profile: UserProfile, settings) -> PetDecision:
        started = time.perf_counter()
        blocked_by: str | None = None
        source = "rule"
        token_usage: dict[str, int] | None = None

        context = self._collect(state=state, profile=profile, settings=settings)
        reason = self._classify(context)
        reason = self._remind(reason)
        decision = self._decide_from_rules(context, reason)

        if self._should_call_llm(context=context, reason=reason):
            ai_result = asyncio.run(
                self._decide_with_llm(context=context, base_decision=decision, reason=reason)
            )
            if ai_result is not None:
                decision, token_usage = ai_result
                source = "ai"
            else:
                source = "fallback"
                blocked_by = "llm_fallback"
                decision = self._fallback_decision(reason=reason, emotion=decision.emotion)

        emitted = self._emit(decision)
        if not emitted:
            blocked_by = blocked_by or "cooldown"
            decision = PetDecision(
                visible=True,
                emotion=decision.emotion,
                speak="...",
                reason="cooldown_suppressed",
                source="rule",
                durationMs=2000,
            )

        latency_ms = int((time.perf_counter() - started) * 1000)
        context_hash = hashlib.sha1(
            json.dumps(context.model_dump(mode="json"), ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:12]
        self._repository.save_decision_record(
            timestamp=datetime.now(timezone.utc),
            context_hash=context_hash,
            decision_json=json.dumps(decision.model_dump(mode="json"), ensure_ascii=False),
            source=source if emitted else "rule",
            token_usage=token_usage,
            latency_ms=latency_ms,
            blocked_by=blocked_by,
        )
        self._recent_decisions.append(decision)
        return decision

    def _collect(self, *, state: MonitoringState, profile: UserProfile, settings) -> DecisionContext:
        self._observation_store.add(state)
        habit_profile = self._habit_profile.update(state)
        observations = self._observation_store.all()
        digest = self._session_digest.maybe_update(observations=observations, habit_profile=habit_profile)
        kpm_5m_values = self._observation_store.kpm_values(5)
        kpm_30m_values = self._observation_store.kpm_values(30) or self._repository.load_recent_kpm(30)
        return DecisionContext(
            timestamp=state.timestamp,
            kpm=KpmAggregate(
                kpm_1m=state.kpm_value,
                kpm_5m=(sum(kpm_5m_values) / len(kpm_5m_values)) if kpm_5m_values else state.kpm_value,
                kpm_30m_avg=(sum(kpm_30m_values) / len(kpm_30m_values)) if kpm_30m_values else state.kpm_value,
            ),
            app=AppSnapshot(
                active_app=state.app_name,
                status_label=state.status.label,
                status_confidence=state.status.confidence,
                status_duration_sec=0,
            ),
            profile=profile,
            settings=settings,
            session_digest=digest,
            recent_interactions=list(self._recent_interactions),
            recent_decisions_digest=[
                f"{item.reason}:{item.speak[:30]}"
                for item in list(self._recent_decisions)[-MAX_RECENT_DECISION_DIGESTS:]
            ],
            habit_profile=habit_profile,
        )

    def _classify(self, context: DecisionContext) -> str:
        if context.kpm.kpm_30m_avg <= 1:
            return "idle"
        if context.kpm.kpm_1m <= 0 and context.kpm.kpm_30m_avg <= 5:
            return "idle"
        if context.kpm.kpm_30m_avg >= max(80, context.settings.focus_threshold):
            return "focused_long"
        now_hour = datetime.now().hour
        if now_hour in set(context.habit_profile.get("idle_hours", [])) and context.kpm.kpm_5m < 8:
            return "afternoon_idle_pattern"

        cluster = self._simple_kmeans_1d([context.kpm.kpm_1m, int(context.kpm.kpm_5m), int(context.kpm.kpm_30m_avg)])
        if cluster == "low":
            return "idle"
        return "encourage"

    def _remind(self, reason: str) -> str:
        if reason == "focused_long":
            now = datetime.now(timezone.utc)
            history = [ts for ts in self._decision_timestamps if (now - ts) <= timedelta(minutes=50)]
            if len(history) >= 2:
                return "hydration_urgent"
        return reason

    def _decide_from_rules(self, context: DecisionContext, reason: str) -> PetDecision:
        emotion_map = {
            "idle": "eat",
            "focused_long": "play",
            "afternoon_idle_pattern": "eat",
            "encourage": "happy",
            "hydration_urgent": "happy",
        }
        speak = TEMPLATE_LIBRARY.get(reason, TEMPLATE_LIBRARY["encourage"])
        if reason == "encourage" and context.session_digest:
            speak = f"{context.session_digest} {speak}"[:90]
        return PetDecision(
            visible=True,
            emotion=emotion_map.get(reason, "happy"),
            speak=speak,
            reason=reason,
            source="rule",
            durationMs=4000,
        )

    def _should_call_llm(self, *, context: DecisionContext, reason: str) -> bool:
        if reason not in AI_GAIN_REASONS:
            return False
        now = datetime.now(timezone.utc)
        self._prune_window_queues(now)
        if len(self._ai_call_timestamps) >= MAX_AI_CALLS_PER_HOUR:
            return False
        if sum(tokens for _, tokens in self._ai_token_usage) >= MAX_AI_TOKENS_PER_HOUR:
            return False
        payload = self._build_llm_payload(context=context, reason=reason)
        if _estimate_tokens(json.dumps(payload, ensure_ascii=False)) > INPUT_TOKEN_BUDGET:
            return False
        api_key = os.getenv("OPENAI_API_KEY") or os.getenv("DEEPSEEK_API_KEY")
        return bool(api_key)

    async def _decide_with_llm(
        self,
        *,
        context: DecisionContext,
        base_decision: PetDecision,
        reason: str,
    ) -> tuple[PetDecision, dict[str, int]] | None:
        api_key = os.getenv("OPENAI_API_KEY") or os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            return None
        url = os.getenv("LLM_API_URL", "https://api.openai.com/v1/chat/completions")
        model = os.getenv("LLM_MODEL", "gpt-4o-mini")
        payload = self._build_llm_payload(context=context, reason=reason)

        try:
            async with httpx.AsyncClient(timeout=AI_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={
                        "model": model,
                        "temperature": 0.6,
                        "max_tokens": OUTPUT_TOKEN_BUDGET,
                        "response_format": {"type": "json_object"},
                        "messages": payload,
                    },
                )
            response.raise_for_status()
            body = response.json()
            content = body["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            speak = str(parsed.get("speak", "")).strip() or base_decision.speak
            emotion = parsed.get("emotion", base_decision.emotion)
            if emotion not in {"happy", "eat", "play"}:
                emotion = base_decision.emotion
            output_tokens = _estimate_tokens(speak)
            if output_tokens > OUTPUT_TOKEN_BUDGET:
                speak = speak[: OUTPUT_TOKEN_BUDGET * 3]
                output_tokens = _estimate_tokens(speak)
            usage = {
                "input_tokens": _estimate_tokens(json.dumps(payload, ensure_ascii=False)),
                "output_tokens": output_tokens,
            }
            now = datetime.now(timezone.utc)
            self._ai_call_timestamps.append(now)
            self._ai_token_usage.append((now, usage["input_tokens"] + usage["output_tokens"]))
            return (
                PetDecision(
                    visible=True,
                    emotion=emotion,
                    speak=speak,
                    reason=reason,
                    source="ai",
                    durationMs=4000,
                ),
                usage,
            )
        except (httpx.HTTPError, ValueError, KeyError, json.JSONDecodeError):
            return None

    def _fallback_decision(self, *, reason: str, emotion: str) -> PetDecision:
        return PetDecision(
            visible=True,
            emotion=emotion if emotion in {"happy", "eat", "play"} else "happy",
            speak=TEMPLATE_LIBRARY.get(reason, TEMPLATE_LIBRARY["encourage"]),
            reason=f"{reason}_fallback",
            source="fallback",
            durationMs=3000,
        )

    def _emit(self, decision: PetDecision) -> bool:
        now = datetime.now(timezone.utc)
        self._prune_window_queues(now)
        if self._last_emit_at and (now - self._last_emit_at).total_seconds() < DECISION_MIN_INTERVAL_SECONDS:
            return False
        reason_at = self._last_reason_at.get(decision.reason)
        if reason_at and (now - reason_at).total_seconds() < SAME_REASON_COOLDOWN_SECONDS:
            return False
        ten_minute_count = sum(
            1 for timestamp in self._decision_timestamps if (now - timestamp) <= timedelta(minutes=10)
        )
        if ten_minute_count >= MAX_SPEAK_PER_10MIN:
            return False

        self._last_emit_at = now
        self._last_reason_at[decision.reason] = now
        self._decision_timestamps.append(now)
        return True

    def _build_llm_payload(self, *, context: DecisionContext, reason: str) -> list[dict]:
        system_personality = "你是 Perch 宠物，语气温和简洁，输出必须是 JSON。"
        user_profile = {
            "username": context.profile.username,
            "free_time": context.profile.free_time,
            "reminders": context.profile.reminders.model_dump(mode="json"),
        }
        context_summary = {
            "reason": reason,
            "kpm": context.kpm.model_dump(mode="json"),
            "app": context.app.model_dump(mode="json"),
            "session_digest": context.session_digest,
            "habit_profile": context.habit_profile,
            "recent_decisions": context.recent_decisions_digest,
        }
        return [
            {"role": "system", "content": system_personality},
            {"role": "user", "content": json.dumps({"profile": user_profile, "context": context_summary}, ensure_ascii=False)},
            {
                "role": "user",
                "content": (
                    "请输出 JSON: {\"speak\": string, \"emotion\": \"happy|eat|play\"}。"
                    "文案不超过60字，保持鼓励但不过度打扰。"
                ),
            },
        ]

    def _prune_window_queues(self, now: datetime) -> None:
        one_hour_ago = now - timedelta(hours=1)
        while self._ai_call_timestamps and self._ai_call_timestamps[0] < one_hour_ago:
            self._ai_call_timestamps.popleft()
        while self._ai_token_usage and self._ai_token_usage[0][0] < one_hour_ago:
            self._ai_token_usage.popleft()
        while self._decision_timestamps and self._decision_timestamps[0] < (now - timedelta(minutes=10)):
            self._decision_timestamps.popleft()

    def _simple_kmeans_1d(self, values: list[int]) -> str:
        if not values:
            return "low"
        c1, c2 = float(min(values)), float(max(values))
        for _ in range(5):
            left = [value for value in values if abs(value - c1) <= abs(value - c2)]
            right = [value for value in values if value not in left]
            c1 = (sum(left) / len(left)) if left else c1
            c2 = (sum(right) / len(right)) if right else c2
        mean_value = sum(values) / len(values)
        return "low" if mean_value <= min(c1, c2) + abs(c1 - c2) * 0.4 else "high"

    def as_pet_state(self, decision: PetDecision) -> PetState:
        return PetState(visible=decision.visible, emotion=decision.emotion, speak=decision.speak)
