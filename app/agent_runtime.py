from __future__ import annotations

import hashlib
import json
import math
import os
import time
import asyncio
from collections import deque
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import random

import httpx

from .models import (
    AppSnapshot,
    DecisionContext,
    KpmAggregate,
    MonitoringState,
    PetDecision,
    PetState,
    PetUpdatePayload,
    UserProfile,
)
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
MAX_SPEAK_WORDS = 20

AI_GAIN_REASONS = {
    "focus_drop_support",
    "health_break_reminder",
    "idle_companion",
    "welcome_back",
    "morning_greeting",
    "daytime_greeting",
    "night_wrap_up",
    "browser_relax",
}

TEMPLATE_LIBRARY: dict[str, str] = {
    "focus_drop_support": "{name}, that looked intense. Want a tiny pause and a head pat, meow?",
    "health_break_reminder": "{name}, one hour already. Rest your eyes with me for five minutes, purr.",
    "idle_companion": "{name}, I got lonely. Stretch with me and take a gentle breath, meow.",
    "welcome_back": "Welcome back, {name}. Let's keep going together, meow.",
    "morning_greeting": "Good morning, {name}. I am awake and cheering for you, meow.",
    "daytime_greeting": "Hi {name}, I am right here with you. Let's make this session count, meow.",
    "night_wrap_up": "{name}, it's late. Your keyboard is tired too. Let's rest now, purr.",
    "browser_relax": "That looks fun, {name}. A soft break is fine. I will watch with you, meow.",
    "meeting_soon": "{name}, meeting starts in five minutes. I will stay quiet and guard your focus, meow.",
    "first_meeting_of_day": "{name}, first meeting today. I will be quiet nearby, meow.",
}


@dataclass
class Observation:
    timestamp: datetime
    state: MonitoringState


@dataclass(frozen=True)
class ScenarioSignal:
    tag: str
    reason: str
    emotion: str
    silent: bool
    allow_ai: bool


class CalendarProvider:
    def meeting_starts_in_minutes(self) -> int | None:
        return None


class AnimationHook:
    def emit(self, scenario_tag: str) -> None:
        # Placeholder hook for frontend animation integration.
        _ = scenario_tag


def _estimate_tokens(text: str) -> int:
    return max(1, math.ceil(len(text) / 4))


def _demo_chat_mode_enabled() -> bool:
    value = (os.getenv("PERCH_DEMO_CHAT_MODE") or "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _resolve_llm_chat_completions_url() -> str:
    """Match OpenAI SDK base_url semantics: host only or full /v1/chat/completions."""
    default = "https://api.openai.com/v1/chat/completions"
    raw = (os.environ.get("LLM_API_URL") or default).strip().rstrip("/")
    if not raw:
        return default
    lower = raw.lower()
    if lower.endswith("/v1/chat/completions") or lower.endswith("/chat/completions"):
        return raw
    if lower.endswith("/v1"):
        return f"{raw}/chat/completions"
    return f"{raw}/v1/chat/completions"


def _normalize_cat_tone(text: str) -> str:
    trimmed = " ".join(text.strip().split())
    if not trimmed:
        return "I'm here with you, meow."
    words = trimmed.split(" ")
    if len(words) > MAX_SPEAK_WORDS:
        trimmed = " ".join(words[:MAX_SPEAK_WORDS])
    lowered = trimmed.lower()
    if not any(marker in lowered for marker in ("meow", "purr", "~")):
        trimmed = f"{trimmed.rstrip('.!?,;:')} meow."
    return trimmed


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
        app_name = observations[-1].state.app_name or "unknown app"
        focus_hours = ",".join(str(hour) for hour in habit_profile.get("focus_hours", [])[:3]) or "none"
        digest = (
            f"Last 30m: focused {focus_minutes}m, idle {idle_minutes}m, mostly in {app_name}. "
            f"Productive hours: {focus_hours}."
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
    def __init__(
        self,
        repository: MetricsRepository,
        calendar_provider: CalendarProvider | None = None,
        animation_hook: AnimationHook | None = None,
    ) -> None:
        self._repository = repository
        self._observation_store = ObservationStore()
        self._session_digest = SessionDigest()
        self._habit_profile = HabitProfile(repository)
        self._calendar_provider = calendar_provider or CalendarProvider()
        self._animation_hook = animation_hook or AnimationHook()
        self._recent_decisions: deque[PetDecision] = deque(maxlen=MAX_RECENT_DECISION_DIGESTS)
        self._recent_interactions: deque[str] = deque(maxlen=MAX_RECENT_INTERACTIONS)
        self._decision_timestamps: deque[datetime] = deque()
        self._ai_call_timestamps: deque[datetime] = deque()
        self._ai_token_usage: deque[tuple[datetime, int]] = deque()
        self._last_emit_at: datetime | None = None
        self._last_reason_at: dict[str, datetime] = {}
        self._previous_kpm: int = 0
        self._idle_streak_minutes: int = 0
        self._last_daily_greeting: date | None = None
        self._meeting_announced_days: set[date] = set()
        self._tone_variants = ("playful", "cozy", "witty", "gentle")

    def run_cycle(self, state: MonitoringState, profile: UserProfile, settings) -> PetDecision:
        started = time.perf_counter()
        blocked_by: str | None = None
        source = "rule"
        token_usage: dict[str, int] | None = None
        llm_attempted = False
        llm_success = False

        context = self._collect(state=state, profile=profile, settings=settings)
        scenario = self._match_scenario(context)
        reason = scenario.reason if scenario else self._classify(context)
        decision = self._decide_from_rules(context, reason, scenario=scenario)
        if scenario is not None:
            self._animation_hook.emit(scenario.tag)

        if self._should_call_llm(context=context, reason=reason, scenario=scenario):
            llm_attempted = True
            ai_result = asyncio.run(
                self._decide_with_llm(
                    context=context,
                    base_decision=decision,
                    reason=reason,
                    scenario_tag=scenario.tag if scenario else "general",
                )
            )
            if ai_result is not None:
                decision, token_usage = ai_result
                source = "ai"
                llm_success = True
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
            llm_attempted=llm_attempted,
            llm_success=llm_success,
        )
        self._recent_decisions.append(decision)
        self._previous_kpm = state.kpm_value
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
        cluster = self._simple_kmeans_1d([context.kpm.kpm_1m, int(context.kpm.kpm_5m), int(context.kpm.kpm_30m_avg)])
        if cluster == "low":
            return "idle_companion"
        return "focus_drop_support"

    def _match_scenario(self, context: DecisionContext) -> ScenarioSignal | None:
        current_day = context.timestamp.astimezone().date()
        app_name = (context.app.active_app or "").lower()
        meeting_in = self._calendar_provider.meeting_starts_in_minutes()
        focused_streak_minutes = sum(
            1 for item in reversed(self._observation_store.all()) if item.state.status.label == "Focused"
        )
        hour = context.timestamp.astimezone().hour

        if "zoom" in app_name or "teams" in app_name:
            if current_day not in self._meeting_announced_days:
                self._meeting_announced_days.add(current_day)
                return ScenarioSignal("First_Meeting_of_Day", "first_meeting_of_day", "happy", True, False)
        if meeting_in is not None and meeting_in <= 5:
            return ScenarioSignal("Meeting_Soon", "meeting_soon", "happy", False, True)
        if self._last_daily_greeting != current_day:
            self._last_daily_greeting = current_day
            if hour < 12:
                return ScenarioSignal("Morning_First_Seen", "morning_greeting", "happy", False, True)
            return ScenarioSignal("Daytime_First_Seen", "daytime_greeting", "happy", False, True)

        if focused_streak_minutes >= 60:
            return ScenarioSignal("Health_Break", "health_break_reminder", "happy", False, True)

        if context.kpm.kpm_1m >= 100 and context.kpm.kpm_5m >= 100:
            return ScenarioSignal("Deep_Work", "deep_work_silent", "happy", True, False)
        if self._previous_kpm >= 100 and context.kpm.kpm_1m <= 15:
            return ScenarioSignal("Focus_Drop", "focus_drop_support", "eat", False, True)

        if context.kpm.kpm_1m <= 1:
            self._idle_streak_minutes += 1
        else:
            if self._idle_streak_minutes >= 15 and context.kpm.kpm_1m > 5:
                self._idle_streak_minutes = 0
                return ScenarioSignal("Back_To_Desk", "welcome_back", "play", False, True)
            self._idle_streak_minutes = 0
        if self._idle_streak_minutes >= 15:
            return ScenarioSignal("Long_Idle", "long_idle_silent", "happy", True, False)

        if hour >= 23 and self._previous_kpm >= 80 and context.kpm.kpm_1m <= 20:
            return ScenarioSignal("Night_Wrap_Up", "night_wrap_up", "eat", False, True)

        if any(name in app_name for name in ("safari", "chrome", "edge", "firefox")) and context.kpm.kpm_5m < 8:
            return ScenarioSignal("Browser_Relax", "browser_relax", "play", False, True)

        return None

    def _display_name(self, profile: UserProfile) -> str:
        if profile.username.strip():
            return profile.username.strip()
        if profile.gender == "female":
            return "sis"
        if profile.gender == "male":
            return "bro"
        return "friend"

    def _decide_from_rules(
        self,
        context: DecisionContext,
        reason: str,
        scenario: ScenarioSignal | None = None,
    ) -> PetDecision:
        emotion_map = {
            "focus_drop_support": "eat",
            "health_break_reminder": "happy",
            "idle_companion": "play",
            "welcome_back": "play",
            "morning_greeting": "happy",
            "daytime_greeting": "happy",
            "night_wrap_up": "eat",
            "browser_relax": "play",
            "meeting_soon": "happy",
            "first_meeting_of_day": "happy",
            "deep_work_silent": "happy",
            "long_idle_silent": "happy",
        }
        if scenario is not None and scenario.silent:
            return PetDecision(
                visible=True,
                emotion=scenario.emotion,
                speak="",
                reason=reason,
                source="rule",
                durationMs=4000,
            )
        speak = TEMPLATE_LIBRARY.get(reason, TEMPLATE_LIBRARY["focus_drop_support"]).format(
            name=self._display_name(context.profile)
        )
        speak = _normalize_cat_tone(speak)
        return PetDecision(
            visible=True,
            emotion=emotion_map.get(reason, "happy"),
            speak=speak,
            reason=reason,
            source="rule",
            durationMs=4000,
        )

    def _should_call_llm(self, *, context: DecisionContext, reason: str, scenario: ScenarioSignal | None) -> bool:
        if scenario is not None and (scenario.silent or not scenario.allow_ai):
            return False
        if reason not in AI_GAIN_REASONS:
            return False
        now = datetime.now(timezone.utc)
        self._prune_window_queues(now)
        if len(self._ai_call_timestamps) >= MAX_AI_CALLS_PER_HOUR:
            return False
        if sum(tokens for _, tokens in self._ai_token_usage) >= MAX_AI_TOKENS_PER_HOUR:
            return False
        payload = self._build_llm_payload(
            context=context,
            reason=reason,
            scenario_tag=scenario.tag if scenario else "general",
        )
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
        scenario_tag: str,
    ) -> tuple[PetDecision, dict[str, int]] | None:
        api_key = os.getenv("OPENAI_API_KEY") or os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            return None
        url = _resolve_llm_chat_completions_url()
        model = os.getenv("LLM_MODEL", "gpt-4o-mini")
        payload = self._build_llm_payload(context=context, reason=reason, scenario_tag=scenario_tag)
        recent_speaks = {item.speak.strip() for item in self._recent_decisions if item.speak.strip()}

        try:
            async with httpx.AsyncClient(timeout=AI_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={
                        "model": model,
                        "temperature": 0.85,
                        "top_p": 0.9,
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
            speak = _normalize_cat_tone(speak)
            if speak in recent_speaks:
                retry_response = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={
                        "model": model,
                        "temperature": 0.95,
                        "top_p": 0.9,
                        "max_tokens": OUTPUT_TOKEN_BUDGET,
                        "response_format": {"type": "json_object"},
                        "messages": payload + [
                            {
                                "role": "user",
                                "content": "Your previous line was too similar to recent lines. Try different wording while keeping intent.",
                            }
                        ],
                    },
                )
                retry_response.raise_for_status()
                retry_body = retry_response.json()
                retry_content = retry_body["choices"][0]["message"]["content"]
                retry_parsed = json.loads(retry_content)
                retry_speak = _normalize_cat_tone(str(retry_parsed.get("speak", "")).strip() or speak)
                if retry_speak not in recent_speaks:
                    speak = retry_speak
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
            speak=_normalize_cat_tone(
                TEMPLATE_LIBRARY.get(reason, TEMPLATE_LIBRARY["focus_drop_support"]).format(name="friend")
            ),
            reason=f"{reason}_fallback",
            source="fallback",
            durationMs=3000,
        )

    def _emit(self, decision: PetDecision) -> bool:
        now = datetime.now(timezone.utc)
        self._prune_window_queues(now)
        demo_mode = _demo_chat_mode_enabled()
        min_interval_seconds = 0 if demo_mode else DECISION_MIN_INTERVAL_SECONDS
        same_reason_cooldown_seconds = 0 if demo_mode else SAME_REASON_COOLDOWN_SECONDS
        max_speak_per_10min = 120 if demo_mode else MAX_SPEAK_PER_10MIN

        if self._last_emit_at and (now - self._last_emit_at).total_seconds() < min_interval_seconds:
            return False
        reason_at = self._last_reason_at.get(decision.reason)
        if reason_at and (now - reason_at).total_seconds() < same_reason_cooldown_seconds:
            return False
        ten_minute_count = sum(
            1 for timestamp in self._decision_timestamps if (now - timestamp) <= timedelta(minutes=10)
        )
        if ten_minute_count >= max_speak_per_10min:
            return False

        self._last_emit_at = now
        self._last_reason_at[decision.reason] = now
        self._decision_timestamps.append(now)
        return True

    def _build_llm_payload(self, *, context: DecisionContext, reason: str, scenario_tag: str) -> list[dict]:
        tone_variant = random.choice(self._tone_variants)
        system_personality = (
            "You are Perch, an empathetic desktop cat with a slightly witty edge. "
            "You are not an AI assistant. You are a quiet companion who cares deeply about the user. "
            "When user is in Deep Work, keep silent and stay nearby without speaking. "
            "When the user works hard, sound tender and protective. When they rest, sound playful and happy. "
            "Always respond in English. Keep speak within 20 words. "
            "Prefer soft emotional wording and end naturally with meow, purr, or ~. "
            "Do not reuse exact wording from recent_decisions. "
            "Output JSON only."
        )
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
            "scenario_tag": scenario_tag,
            "tone_variant": tone_variant,
        }
        return [
            {"role": "system", "content": system_personality},
            {"role": "user", "content": json.dumps({"profile": user_profile, "context": context_summary}, ensure_ascii=False)},
            {
                "role": "user",
                "content": (
                    "Task: Use the provided [Context] to send one warm encouragement or gentle reminder. "
                    "Return strict JSON only: {\"speak\":\"...\",\"emotion\":\"happy|eat|play\"}. "
                    "Constraints: English only, at most 20 words in speak, no markdown, no extra keys. "
                    "Address user by name when available."
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

    def as_pet_update_payload(self, decision: PetDecision) -> PetUpdatePayload:
        return PetUpdatePayload(
            visible=decision.visible,
            emotion=decision.emotion,
            speak=decision.speak,
            reason=decision.reason,
            durationMs=decision.durationMs,
        )

    def reset_demo_session(self) -> None:
        self._last_daily_greeting = None
        self._idle_streak_minutes = 0
        self._last_emit_at = None
        self._last_reason_at.clear()
        self._decision_timestamps.clear()
