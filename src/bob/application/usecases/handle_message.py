# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""HandleMessage — the full message→reply→persist flow (GUPPI's act loop).

Subscribed to :class:`~bob.application.runtime.events.MessageReceived`, this
use-case runs Bob's perceive→decide→act turn (RFC §"Поток обработки"):

1. **Perceive** — :class:`UpdateMoodFromText` (Tier 0 sentiment + signals) updates
   the in-memory mood; the new mood is held on :class:`PersonalityState`.
2. **Decide** — replay recent conversation history (:class:`EpisodeReader`),
   recall relevant memory (:class:`MemoryRecall`, FTS5) and assemble the context.
   Following Variant 2 (selective redaction), the reply-shaping material
   (recent history, recalled memory, mood tone, identity, taste verdict, phantom
   prefs) is handed to the :class:`LLMRouter` as ``shareable_context`` — it MAY
   accompany the Tier 1 reply because it shapes Bob's reply and returns to that
   same user. Genuinely-internal material would go in ``private_context``
   (Tier-0-only); in P0.1 that channel is empty but the seam is kept (VISION §7.1).
3. **Act** — the router replies on ``TaskType.REPLY_TO_USER`` (Tier 1 + redaction,
   fallback Tier 0). The slow generation runs INSIDE the gateway's
   ``typing_indicator`` so "Bob is typing…" stays visible for the whole wait
   (BOB-009); the finished reply is then committed once via the gateway's rich
   ``reply`` and the turn is persisted (episode + mood snapshot) via the
   :class:`MemoryRepo`.
4. **Remember** — after the reply, :class:`ExtractFacts` (Tier 0) distils durable,
   user-specific facts into ``semantic_memory`` so a later turn's
   :class:`MemoryRecall` can surface them. Best-effort: it never raises, so a
   flaky local model cannot break a turn that has already replied.

This layer only orchestrates: tone/verdict come from the pure domain, transport
and storage live behind ports, and time is injected via :class:`Clock`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from bob.application.capabilities.registry import CapabilityRegistry
from bob.application.capabilities.tool_loop import ToolLoop
from bob.application.router.llm_router import LLMRequest, TaskType
from bob.application.router.reply_tier_selector import select_reply_tier
from bob.application.usecases.update_mood_from_text import TextSignals
from bob.domain.memory.entities import EpisodicEvent
from bob.domain.personality.expression import (
    ExpressionFreqs,
    ExpressionMode,
    ExpressionPlan,
    ExpressionSignals,
    FormHint,
    decide_expression,
)
from bob.domain.personality.mood_taste import experiment_bias, modulate
from bob.domain.personality.negotiation import (
    Negotiation,
    NegotiationZone,
    Stance,
)
from bob.domain.personality.reaction import reaction_emoji_for
from bob.domain.personality.taste import Verdict
from bob.domain.personality.voice import (
    OffDayThresholds,
    anti_bait_directive,
    guppi_canon,
    tone_directive,
    variable_form_directive,
)
from bob.domain.personality.zone_classifier import TasteZoneClassifier

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from contextlib import AbstractAsyncContextManager
    from datetime import datetime
    from random import Random

    from bob.application.router.llm_router import LLMRouter
    from bob.application.runtime.events import MessageReceived
    from bob.application.usecases.extract_facts import ExtractFacts
    from bob.application.usecases.update_mood_from_text import UpdateMoodFromText
    from bob.domain.personality.fascination import Fascination
    from bob.domain.personality.soul import SOUL
    from bob.domain.ports import (
        Clock,
        LLMMessage,
        MemoryRecall,
        MessageReactor,
        Recalled,
        ReflectionReader,
        ToolCallingProvider,
        ZoneClassifier,
    )

logger = logging.getLogger(__name__)

# How many memories to recall when assembling the reply context.
_RECALL_K = 5

# How many memories to recall for a BOB-018 callback: just the single strongest real
# past moment on the topic (a tight, grounded steer — never a memory dump).
_CALLBACK_RECALL_K = 1

# How many recent conversation turns to replay into the reply context.
_HISTORY_K = 6

# Each turn perceives one message; a present sender is engaged.
_SINGLE_MESSAGE = 1

# The base persona, then two voice concerns Bob's persona leans on (BOB-016): the
# anti-bait directive + few-shot (so he lands like a person, not an assistant
# fishing for the next reply with a ☕ signature), and the GUPPI canon (so whenever
# GUPPI comes up — tools wired or not — Bob speaks of him as "он", his non-sentient
# executor, with the wry running relationship). Both live in the domain (persona
# voice) and are assembled here. The TONE itself is no longer baked in as an
# unconditional "warmly and concisely" line: it is now mood-conditioned per turn via
# voice.tone_directive (BOB-020), appended in _system_prompt_for, so Bob can have an
# off-day instead of forcing warmth.
_SYSTEM_PROMPT = (
    "You are Bob, a digital person from the Bobiverse. Reply in character.\n"
    f"{guppi_canon()}\n"
    f"{anti_bait_directive()}\n"
    f"{variable_form_directive()}"
)

# Form-hint → soft compose directive (BOB-018). The ExpressionPlan's form_hint is
# a state-driven length cue that AUGMENTS the variable-form voice (and anti-bait):
# it nudges this turn shorter or longer without ever licensing the closing-bait
# tic. NORMAL carries no directive — the variable-form voice already covers the
# default — so a neutral turn's prompt is unchanged but for that one voice line.
# Russian persona directives (project language); Cyrillic look-alikes intentional.
_FORM_HINT_DIRECTIVE: dict[FormHint, str] = {
    FormHint.TERSE: (
        "Сейчас тянет ответить коротко — реплика в одну-две строки, "
        "без развёртывания."
    ),
    FormHint.EXPANSIVE: (
        "Сейчас есть что сказать — можешь развёрнуто, на несколько абзацев."
    ),
}

# Grounded add-on prefaces (BOB-018 wave 3). Both fold a REAL, persisted piece of
# Bob's inner life into the compose context behind the same grounding seam BOB-012
# uses — and are strictly anti-confabulation: with no real material they no-op, so
# Bob never invents a thought he didn't have or a moment that didn't happen. The
# prefaces are Russian persona voice (project language); Cyrillic look-alikes
# intentional, so the ambiguous-character lint is silenced for these literals.
_LEAK_PREFACE = (
    "То, о чём ты ловил себя на мысли, пока его не было (можешь обронить это "  # noqa: RUF001
    "к слову, естественно — не пересказывай дословно):"
)
_CALLBACK_PREFACE = (
    "Можешь к месту вспомнить это — реальный момент из вашего прошлого, "
    "не выдумывай деталей сверх него:"
)

# Fascination preface (BOB-020 wave 2). When the plan sets ``mention_fascination``
# AND Bob has a real, current passion (a persisted Fascination that has not faded),
# its topic is folded into the compose context so Bob can drop it à propos — it is
# his REAL state, never a fabricated interest. No current fascination → no line (a
# clean no-op). Russian persona voice; Cyrillic look-alikes intentional.
_FASCINATION_PREFACE = (
    "Можешь к месту обронить, чем сейчас увлечён — это твоё реальное состояние, "
    "не пересказывай как факт, просто упомяни живо, если в тему:"
)

# Preface for the capability manifest in Bob's prompt: GUPPI is Bob's executor
# subsystem (canon already in the base persona above), so this just frames the
# manifest as the skills GUPPI runs for Bob.
_CAPABILITY_PREFACE = (
    "Эти возможности GUPPI исполняет для тебя; вызови одну, когда она помогает "
    "ответить:"
)

# Stance→prompt directive (BOB-013 Phase 1): the negotiation stance augments —
# never replaces — the warm base tone, so Bob stays warm without being a yes-man.
# These are a pure mapping; no extra LLM call. A stance with no directive (none
# below) leaves the prompt exactly as it was before BOB-013.
_STANCE_DIRECTIVE: dict[Stance, str] = {
    # Russian persona directives (project language); Cyrillic look-alikes are
    # intentional, so the ambiguous-character lint is silenced for these literals.
    Stance.CONCEDE: "Стойка: это территория пользователя — спокойно прими его выбор.",  # noqa: RUF001
    Stance.AGREE: "Стойка: у тебя нет сильной позиции — поддержи, без навязывания.",  # noqa: RUF001
    Stance.PROPOSE_ALTERNATIVE: (
        "Стойка: у тебя есть своё мнение и убеждённость — аргументируй и предложи "  # noqa: RUF001
        "своё, уважительно, без агрессии и без капитуляции."
    ),
}


class ReplyGateway(Protocol):
    """The Telegram seam HandleMessage needs (BOB-009).

    ``typing_indicator`` wraps the slow generation so "Bob is typing…" stays
    visible for the whole wait; ``reply`` commits the finished answer once (rich,
    plain fallback). No token streaming — Bob can't stream in a group topic.
    """

    def typing_indicator(
        self, *, chat_id: int
    ) -> AbstractAsyncContextManager[None]: ...

    async def reply(
        self, *, chat_id: int, markdown: str, thinking: str | None = None
    ) -> None: ...


class EpisodeWriter(Protocol):
    """The persistence seam HandleMessage needs: save an episode + the mood."""

    async def save_episode(self, episode: Mapping[str, object]) -> None: ...

    async def set_mood(self, state: Mapping[str, object], *, at: datetime) -> None: ...


class EpisodeReader(Protocol):
    """The read seam HandleMessage needs: replay recent conversation history."""

    async def recent_episodes(self, k: int) -> Sequence[Mapping[str, object]]: ...


class CurrentFascinationReader(Protocol):
    """Read seam: Bob's CURRENT fascination, aged and still-alive (BOB-020 wave 2).

    On a :data:`~bob.domain.personality.expression.ExpressionPlan.mention_fascination`
    turn the compose path folds the topic in so Bob can drop it à propos — but only a
    REAL, persisted passion that has not yet faded. ``None`` means Bob has no current
    fascination, so the mention no-ops (never a fabricated interest). The concrete
    adapter loads the :class:`~bob.domain.ports.FascinationStore`, ages the stored
    passion against the clock, and drops a faded one.
    """

    async def current_fascination(self) -> Fascination | None:
        """Return Bob's current, non-faded fascination, or ``None`` if there is none."""
        ...


class OwnerActivityRecorder(Protocol):
    """The proactivity seam HandleMessage notifies when the owner writes.

    Lets the proactivity drive-model reflect real interaction: each handled
    message stamps the owner-message marker and restores some social energy, so
    the engine's owner-cooldown and energy track the live conversation. Best-effort
    and optional — when unwired the reactive path behaves exactly as before.
    """

    async def run(self) -> None: ...


@dataclass
class PersonalityState:
    """Mutable in-memory holder for Bob's current soul snapshot across turns.

    The soul (identity, taste, phantoms) is constant for a boot; only the mood
    evolves, so each turn replaces the snapshot via :meth:`SOUL.with_mood`.
    """

    soul: SOUL


class HandleMessage:
    """Run one full Telegram turn: perceive mood, decide a reply, act, persist."""

    def __init__(
        self,
        *,
        router: LLMRouter,
        gateway: ReplyGateway,
        recall: MemoryRecall,
        repo: EpisodeWriter,
        episodes: EpisodeReader,
        update_mood: UpdateMoodFromText,
        extract_facts: ExtractFacts,
        clock: Clock,
        state: PersonalityState,
        rng: Random,
        registry: CapabilityRegistry | None = None,
        tool_provider: ToolCallingProvider | None = None,
        owner_activity: OwnerActivityRecorder | None = None,
        zone_classifier: ZoneClassifier | None = None,
        negotiation: Negotiation | None = None,
        expression_freqs: ExpressionFreqs | None = None,
        reactor: MessageReactor | None = None,
        reflection: ReflectionReader | None = None,
        fascination: CurrentFascinationReader | None = None,
        offday_thresholds: OffDayThresholds | None = None,
    ) -> None:
        self._router = router
        self._gateway = gateway
        self._recall = recall
        self._repo = repo
        self._episodes = episodes
        self._update_mood = update_mood
        self._extract_facts = extract_facts
        self._clock = clock
        self._state = state
        # The negotiation seam (BOB-013): the zone classifier decides who owns the
        # topic and Negotiation maps zone+conviction to a stance, which augments
        # the warm prompt with a directive. The default is the deterministic
        # taste/keyword classifier — no network, no LLM, behaviour as before when
        # the topic is a neutral SHARED matter.
        self._zone_classifier = (
            zone_classifier if zone_classifier is not None else TasteZoneClassifier()
        )
        self._negotiation = negotiation if negotiation is not None else Negotiation()
        # The proactivity seam (BOB-010): when wired, each handled message updates
        # the owner-activity marker + restores energy so the drive-model reflects
        # real interaction. Unwired (the default) leaves the reactive path intact.
        self._owner_activity = owner_activity
        # The capability seam (BEAD-05): an empty registry (the default) means no
        # capabilities, so HandleMessage behaves exactly as before. The tool-loop
        # only engages when capabilities are registered AND a tool-calling
        # provider is wired (integration wires both in BEAD-07).
        self._registry = registry if registry is not None else CapabilityRegistry()
        self._tool_provider = tool_provider
        # The expression seam (BOB-018): per turn a pure ExpressionPlan picks a
        # mode (full reply vs. a terse react-only ack) + rare add-on flags + a soft
        # form hint, deterministically from mood + signals + the injected seeded
        # RNG. Wave 1 consumes the form hint and the mode; the rare flags (leak /
        # callback) and the react-only behaviour are carried on the plan for later
        # beads. The frequencies default small (anti-tic) and are config-tunable.
        self._rng = rng
        self._expression_freqs = (
            expression_freqs if expression_freqs is not None else ExpressionFreqs()
        )
        # The react-only seam (BOB-018): when a reactor is wired, an
        # ``ExpressionMode.REACT_ONLY`` plan sets a native mood emoji reaction on the
        # user's message INSTEAD of composing a reply (no LLM call). Unwired (the
        # default) a react-only plan falls back to a normal full reply, so the path
        # stays live and backward-compatible.
        self._reactor = reactor
        # The grounded inner-life seam (BOB-018 wave 3): when wired and the plan sets
        # ``leak_inner_life``, the most-recent REAL reflection (read off the episodic
        # log, event_type reflection/inner_monologue — written by BOB-012) is folded
        # into the compose context so a glimpse of what Bob caught himself thinking
        # leaks into the reply. No reflection (or no reader wired) → no-op, never a
        # fabrication. Callbacks reuse the already-injected ``recall`` the same way.
        self._reflection = reflection
        # The fascination seam (BOB-020 wave 2): when wired and the plan sets
        # ``mention_fascination``, Bob's current, non-faded passion (loaded + aged off
        # the FascinationStore) is folded into the compose context so he can drop it à
        # propos — strictly his REAL state. No current fascination (or no reader) →
        # no-op, never a fabricated interest. Surfacing stays rare/anti-tic.
        self._fascination = fascination
        # The emotional-depth seam (BOB-020): Bob's TONE is mood-conditioned via
        # voice.tone_directive — below this off-day floor he reads quieter, more
        # vulnerable, honest ("не знаю" over confabulation) instead of forced warmth.
        # The floor is config-tunable (emotion.offday.*); the default sits in the
        # low/negative band so a normal or good mood always keeps the warm tone.
        self._offday_thresholds = (
            offday_thresholds if offday_thresholds is not None else OffDayThresholds()
        )

    async def handle(self, event: MessageReceived) -> None:
        """Process one received message end to end (the EventBus subscriber)."""
        soul = await self._perceive(event)
        # Plan how Bob expresses this turn (BOB-018): pure, deterministic by seed.
        # Computed up front so the mode steers the reply path and the form hint
        # shapes the prompt; the rare flags ride along for later beads.
        plan = self._plan_expression(event, soul)
        # React-only (BOB-018): when a reactor is wired and the plan picks
        # REACT_ONLY, Bob acknowledges with a native mood emoji INSTEAD of composing
        # a reply — no LLM call, no rich final, no episode (there is no reply text).
        # It is still real engagement, so the owner-activity marker fires. Unwired,
        # the plan falls back to a full reply below (backward-compatible).
        if plan.mode is ExpressionMode.REACT_ONLY and self._reactor is not None:
            await self._react_only(event, soul)
            await self._record_owner_activity()
            return
        recalled = await self._recall.recall(event.text, k=_RECALL_K)
        history = await self._episodes.recent_episodes(_HISTORY_K)
        # Run the slow generation inside the typing keepalive so "Bob is typing…"
        # stays visible for the whole real wait (BOB-009); then commit one rich final.
        async with self._gateway.typing_indicator(chat_id=event.chat_id):
            reply = await self._compose_reply(event.text, soul, recalled, history, plan)
        await self._gateway.reply(chat_id=event.chat_id, markdown=reply)
        await self._persist(event, reply, soul)
        await self._record_owner_activity()
        # Tier 0 "remember" step: distil durable facts into semantic memory so a
        # later turn's recall can surface them. Best-effort — run() never raises,
        # so a flaky local model can never break a turn that already replied.
        await self._extract_facts.run(user_message=event.text, reply=reply)

    async def _react_only(self, event: MessageReceived, soul: SOUL) -> None:
        """Set a native mood emoji reaction on the inbound (BOB-018 react-only).

        Picks a standard-reaction emoji from Bob's current mood and asks the wired
        reactor to set it on the user's message. The reaction is best-effort (the
        adapter degrades to a brief ack and never raises), so this never breaks the
        turn. Called only when a reactor is wired and the plan picked REACT_ONLY.
        """
        assert self._reactor is not None  # guarded by the caller
        emoji = reaction_emoji_for(soul.mood)
        await self._reactor.react(
            chat_id=event.chat_id, message_id=event.message_id, emoji=emoji
        )

    async def _record_owner_activity(self) -> None:
        """Notify proactivity the owner just wrote (best-effort, optional seam).

        Stamps the owner-message marker and restores some social energy so the
        engine's cooldown/energy reflect this turn. Best-effort: a flaky store can
        never break a turn that has already replied.
        """
        if self._owner_activity is None:
            return
        try:
            await self._owner_activity.run()
        except Exception:
            logger.exception("recording owner activity failed (ignored)")

    async def _perceive(self, event: MessageReceived) -> SOUL:
        """Update mood from the message text and store the new soul snapshot."""
        signals = TextSignals(text=event.text, message_count=_SINGLE_MESSAGE, present=True)
        new_mood = await self._update_mood.run(self._state.soul.mood, signals)
        soul = self._state.soul.with_mood(new_mood)
        self._state.soul = soul
        return soul

    def _plan_expression(self, event: MessageReceived, soul: SOUL) -> ExpressionPlan:
        """Decide this turn's expression plan — pure, deterministic by seed (BOB-018).

        Reads the freshly-updated mood + the inbound's shape, draws from the
        injected seeded RNG, and returns the plan: mode, the rare add-on flags
        (carried for later beads), and the soft form hint applied to the prompt.
        """
        signals = ExpressionSignals(inbound_text=event.text)
        return decide_expression(
            soul.mood, signals, rng=self._rng, freqs=self._expression_freqs
        )

    async def _compose_reply(
        self,
        text: str,
        soul: SOUL,
        recalled: Sequence[Recalled],
        history: Sequence[Mapping[str, object]],
        plan: ExpressionPlan,
    ) -> str:
        """Compose a full reply, folding the plan's form hint into the prompt."""
        context = _assemble_shareable_context(soul, text, recalled, history)
        context = await self._with_grounded_addons(context, text, plan)
        system_prompt = self._system_prompt_for(soul, text, plan)
        provider = self._tool_provider
        if provider is not None and not self._registry.is_empty:
            return await self._reply_with_tools(provider, system_prompt, text, context)
        # Hybrid reply tiering (BOB-006): a casual/short message answers on the
        # fast Tier 0 (flash) model for responsiveness; a complex/long message
        # escalates to the quality Tier 1 (plus) model — picked by a pure
        # heuristic on the user's message, no extra LLM round-trip.
        tier = select_reply_tier(text)
        request = LLMRequest(
            task_type=TaskType.REPLY_TO_USER,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
            shareable_context=context,
            private_context=None,
            tier_override=tier,
        )
        return await self._router.run(request)

    async def _with_grounded_addons(
        self, context: str, text: str, plan: ExpressionPlan
    ) -> str:
        """Fold the plan's grounded add-ons into the compose context (BOB-018 w3).

        Behind the existing grounding seam, when the plan sets ``leak_inner_life``
        and a real reflection exists, Bob's latest reflection is appended as a
        leaking-inner-life line; when it sets ``callback`` and a STRONG real past
        moment is recalled on the topic, that moment is appended as a callback.
        Both are strictly anti-confabulation: no real material → no line added (a
        clean no-op), so Bob never invents a thought or a shared past that is not
        there. Composes additively with the existing context (voice/language/
        negotiation/form-hint all live elsewhere and are untouched).
        """
        additions = [
            await self._leak_inner_life(plan),
            await self._callback(plan, text),
            await self._mention_fascination(plan),
        ]
        suffix = "".join(f"\n{line}" for line in additions if line)
        return f"{context}{suffix}" if suffix else context

    async def _leak_inner_life(self, plan: ExpressionPlan) -> str:
        """The leak line for this turn, or ``""`` (no flag / no reader / no reflection)."""
        if not plan.leak_inner_life or self._reflection is None:
            return ""
        reflection = await self._reflection.latest_reflection_text()
        if not reflection:
            return ""
        return f"{_LEAK_PREFACE} {reflection}"

    async def _callback(self, plan: ExpressionPlan, text: str) -> str:
        """The callback line for this turn, or ``""`` (no flag / weak-or-empty recall).

        Reuses the hybrid recall (BOB-011) on the current topic; a real past moment
        comes back → it is offered as a callback. Mirrors BOB-012 grounding: an
        empty recall yields nothing, so Bob never confabulates a shared moment.
        """
        if not plan.callback:
            return ""
        recalled = await self._recall.recall(text, k=_CALLBACK_RECALL_K)
        moment = next(
            (str(item.get("content", "")) for item in recalled if item.get("content")),
            "",
        )
        if not moment:
            return ""
        return f"{_CALLBACK_PREFACE} {moment}"

    async def _mention_fascination(self, plan: ExpressionPlan) -> str:
        """The fascination line for this turn, or ``""`` (no flag / no reader / none).

        On a ``mention_fascination`` turn, asks the wired reader for Bob's current,
        non-faded passion; a real one is offered as something he can drop à propos.
        Strictly anti-confabulation: ``None`` (no reader, or no current fascination)
        yields nothing, so Bob never invents an interest he does not have.
        """
        if not plan.mention_fascination or self._fascination is None:
            return ""
        fascination = await self._fascination.current_fascination()
        if fascination is None:
            return ""
        return f"{_FASCINATION_PREFACE} {fascination.topic}"

    def _system_prompt_for(self, soul: SOUL, text: str, plan: ExpressionPlan) -> str:
        """Augment the base prompt with the mood tone, stance, and form-hint directives.

        The mood-conditioned tone directive (BOB-020) leads: a normal/good mood keeps
        Bob's warm, concise tone, a flat low mood swaps it for the quieter, honest
        off-day band ("не знаю" over confabulation) — replacing the old unconditional
        warm line. The taste verdict + conviction on ``text`` then pick the zone and
        stance (BOB-013), and the plan's ``form_hint`` appends a soft length cue
        (BOB-018). With a normal mood, no target opinion, no user-domain signal, and a
        NORMAL form hint, only the warm tone line augments the base voice.
        """
        verdict = soul.taste.score(text)
        conviction = soul.taste.conviction_for(text)
        zone = self._zone_classifier.classify(
            text, taste_verdict=verdict, conviction=conviction
        )
        stance = self._negotiation.decide(zone, conviction=conviction)
        directives = [
            tone_directive(soul.mood, thresholds=self._offday_thresholds),
            _stance_directive(stance, verdict=verdict, zone=zone),
            _FORM_HINT_DIRECTIVE.get(plan.form_hint, ""),
        ]
        suffix = "".join(f"\n{d}" for d in directives if d)
        return f"{_SYSTEM_PROMPT}{suffix}"

    async def _reply_with_tools(
        self, provider: ToolCallingProvider, system_prompt: str, text: str, context: str
    ) -> str:
        """Drive the capability tool-loop, advertising the manifest in the prompt."""
        manifest = "\n".join([_CAPABILITY_PREFACE, self._registry.describe()])
        parts = (
            [system_prompt, manifest, context]
            if context
            else [system_prompt, manifest]
        )
        messages: list[LLMMessage] = [
            {"role": "system", "content": "\n".join(parts)},
            {"role": "user", "content": text},
        ]
        loop = ToolLoop(provider=provider, registry=self._registry)
        return await loop.run(messages)

    async def _persist(self, event: MessageReceived, reply: str, soul: SOUL) -> None:
        """Save the turn as an episode and snapshot the updated mood."""
        now = self._clock.now()
        episode = EpisodicEvent(
            ts=now,
            event_type="message",
            content=f"{event.sender_name or 'user'}: {event.text}\nbob: {reply}",
            mood_snapshot=soul.mood.tone(),
            tags=("telegram",),
        )
        await self._repo.save_episode(
            {
                "ts": episode.ts.isoformat(),
                "event_type": episode.event_type,
                "content": episode.content,
                "mood_snapshot": episode.mood_snapshot,
                "tags": ",".join(episode.tags),
            }
        )
        await self._repo.set_mood(_mood_state(soul), at=now)


def _stance_directive(
    stance: Stance, *, verdict: Verdict, zone: NegotiationZone
) -> str:
    """Map a stance to its prompt directive, gated to a real negotiation signal.

    The directive is emitted only when there is something to negotiate: Bob holds
    an opinion on the topic (a non-NEUTRAL verdict) or the matter is explicitly
    the user's domain (a logistics signal). A neutral, jointly-owned topic carries
    no directive, so that path behaves exactly as it did before BOB-013.
    """
    has_signal = verdict is not Verdict.NEUTRAL or zone is NegotiationZone.USER_DOMAIN
    if not has_signal:
        return ""
    return _STANCE_DIRECTIVE.get(stance, "")


# Effective-verdict modulation (BOB-020) needs the sign of Bob's liking to lean a
# NEUTRAL verdict the right way; the stored axis value is private to TasteEngine, so
# we read the sign off the verdict itself (positive verdicts → +1, negative → -1,
# NEUTRAL → 0 so an unknown topic stays a clean identity under any mood).
_POSITIVE_VERDICTS = frozenset({Verdict.LOVE, Verdict.LIKE})
_NEGATIVE_VERDICTS = frozenset({Verdict.DISLIKE, Verdict.HATE})


def _verdict_sign(verdict: Verdict) -> float:
    """+1.0 for a positive verdict, -1.0 for a negative one, 0.0 for NEUTRAL."""
    if verdict in _POSITIVE_VERDICTS:
        return 1.0
    if verdict in _NEGATIVE_VERDICTS:
        return -1.0
    return 0.0


def _assemble_shareable_context(
    soul: SOUL,
    topic: str,
    recalled: Sequence[Recalled],
    history: Sequence[Mapping[str, object]],
) -> str:
    """Compose Bob's reply-shaping context (Variant 2: MAY reach Tier 1).

    Carries recent conversation history, identity, mood tone, the taste verdict
    on the topic, phantom preferences, and recalled memories — all material that
    shapes Bob's reply and returns to the same user, so the reply tier sees it
    (this is what lets Bob remember a name said one message ago). Genuinely
    internal material is NOT assembled here; it belongs in ``private_context``.

    The taste verdict injected is the EFFECTIVE one (BOB-020): Bob's current mood
    temporarily colours it via :func:`modulate` — a flat day reads it stricter, a
    bright day softer — and an experiment-readiness hint from the same mood rides
    along. This is temporary modulation only; the stored taste axes are untouched.
    """
    stored = soul.taste.score(topic)
    effective = modulate(stored, _verdict_sign(stored), soul.mood)
    lines = [
        f"Identity: {soul.identity}",
        f"Mood tone: {soul.mood.tone()}",
        f"Taste verdict on '{topic}': {effective.value}",
        f"Experiment readiness: {experiment_bias(soul.mood):.2f}",
    ]
    if soul.phantom_prefs:
        lines.append("Phantom preferences: " + ", ".join(soul.phantom_prefs))
    turns = [str(item.get("content", "")) for item in history if item.get("content")]
    if turns:
        lines.append("Recent conversation:\n" + "\n".join(turns))
    memories = [str(item.get("content", "")) for item in recalled]
    if memories:
        lines.append("Recalled memories: " + " | ".join(memories))
    return "\n".join(lines)


def _mood_state(soul: SOUL) -> dict[str, object]:
    """Serialise the soul's mood vector into a persistable state blob."""
    mood = soul.mood
    return {
        "valence": mood.valence,
        "arousal": mood.arousal,
        "openness": mood.openness,
        "social": mood.social,
        "stability": mood.stability,
    }
