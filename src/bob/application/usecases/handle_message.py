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
from bob.domain.personality.negotiation import (
    Negotiation,
    NegotiationZone,
    Stance,
)
from bob.domain.personality.taste import Verdict
from bob.domain.personality.voice import (
    anti_bait_directive,
    guppi_canon,
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
    from bob.domain.personality.soul import SOUL
    from bob.domain.ports import (
        Clock,
        LLMMessage,
        MemoryRecall,
        Recalled,
        ToolCallingProvider,
        ZoneClassifier,
    )

logger = logging.getLogger(__name__)

# How many memories to recall when assembling the reply context.
_RECALL_K = 5

# How many recent conversation turns to replay into the reply context.
_HISTORY_K = 6

# Each turn perceives one message; a present sender is engaged.
_SINGLE_MESSAGE = 1

# The warm base persona, then Bob's voice guidance (BOB-016): the anti-bait
# directive + substance-ending few-shot break the base model's reflex of closing
# every reply with an engagement-bait question and a ☕ signature, so Bob lands
# like a person, not an assistant. The directive lives in the domain (persona
# voice), assembled in here onto the warm base tone.
# The warm base persona, then two voice concerns Bob's persona leans on (BOB-016):
# the anti-bait directive + few-shot (so he lands like a person, not an assistant
# fishing for the next reply with a ☕ signature), and the GUPPI canon (so whenever
# GUPPI comes up — tools wired or not — Bob speaks of him as "он", his
# non-sentient executor, with the wry running relationship). Both live in the
# domain (persona voice) and are assembled onto the warm base tone here.
_SYSTEM_PROMPT = (
    "You are Bob, a digital person from the Bobiverse. Reply in character, "
    "warmly and concisely, coloured by your current mood.\n"
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

    async def handle(self, event: MessageReceived) -> None:
        """Process one received message end to end (the EventBus subscriber)."""
        soul = await self._perceive(event)
        # Plan how Bob expresses this turn (BOB-018): pure, deterministic by seed.
        # Computed up front so the mode steers the reply path and the form hint
        # shapes the prompt; the rare flags ride along for later beads.
        plan = self._plan_expression(event, soul)
        recalled = await self._recall.recall(event.text, k=_RECALL_K)
        history = await self._episodes.recent_episodes(_HISTORY_K)
        # Run the slow generation inside the typing keepalive so "Bob is typing…"
        # stays visible for the whole real wait (BOB-009); then commit one rich final.
        async with self._gateway.typing_indicator(chat_id=event.chat_id):
            reply = await self._decide(event.text, soul, recalled, history, plan)
        await self._gateway.reply(chat_id=event.chat_id, markdown=reply)
        await self._persist(event, reply, soul)
        await self._record_owner_activity()
        # Tier 0 "remember" step: distil durable facts into semantic memory so a
        # later turn's recall can surface them. Best-effort — run() never raises,
        # so a flaky local model can never break a turn that already replied.
        await self._extract_facts.run(user_message=event.text, reply=reply)

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

    async def _decide(
        self,
        text: str,
        soul: SOUL,
        recalled: Sequence[Recalled],
        history: Sequence[Mapping[str, object]],
        plan: ExpressionPlan,
    ) -> str:
        """Build the request (selective redaction) and get the reply.

        Reply-shaping context (history + memory + mood/identity/taste) goes in
        ``shareable_context`` so it reaches the Tier 1 reply; the
        ``private_context`` channel is kept for Tier-0-only material (empty here).
        When capabilities are registered AND a tool-calling provider is wired, the
        reply runs through the capability tool-loop (the model may call a
        capability, GUPPI executes it, the result loops back); otherwise it stays
        on today's plain router path.

        The ``plan`` shapes the turn (BOB-018): a :data:`ExpressionMode.REACT_ONLY`
        plan routes through :meth:`_react_only_reply` — the explicit seam bob-c4w.2
        fills with a native reaction; until then it composes a normal full reply,
        so the path is live and tested, never dead code. The plan's ``form_hint``
        is folded into the system prompt as a soft length cue.
        """
        if plan.mode is ExpressionMode.REACT_ONLY:
            return await self._react_only_reply(text, soul, recalled, history, plan)
        return await self._compose_reply(text, soul, recalled, history, plan)

    async def _react_only_reply(
        self,
        text: str,
        soul: SOUL,
        recalled: Sequence[Recalled],
        history: Sequence[Mapping[str, object]],
        plan: ExpressionPlan,
    ) -> str:
        """Handle a react-only turn — the bob-c4w.2 seam, a full reply until then.

        BOB-018 wave 1 carries the :data:`ExpressionMode.REACT_ONLY` decision but
        not the native Telegram reaction (that is bob-c4w.2). To keep the path live
        and free of dead code, a react-only turn falls back to a normal composed
        reply here; bob-c4w.2 replaces this body with the ``MessageReactor`` call.
        """
        return await self._compose_reply(text, soul, recalled, history, plan)

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

    def _system_prompt_for(self, soul: SOUL, text: str, plan: ExpressionPlan) -> str:
        """Augment the warm base prompt with the stance + form-hint directives.

        The taste verdict + conviction on ``text`` pick the zone (who owns the
        matter) and the stance (how firmly Bob holds); the stance maps to a
        directive appended to — never replacing — the warm base tone. The plan's
        ``form_hint`` then appends a soft length cue (BOB-018), augmenting the
        variable-form voice. With no target opinion, no user-domain signal, and a
        NORMAL form hint, the prompt is unchanged but for the base voice line.
        """
        verdict = soul.taste.score(text)
        conviction = soul.taste.conviction_for(text)
        zone = self._zone_classifier.classify(
            text, taste_verdict=verdict, conviction=conviction
        )
        stance = self._negotiation.decide(zone, conviction=conviction)
        directives = [
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
    """
    verdict = soul.taste.score(topic).value
    lines = [
        f"Identity: {soul.identity}",
        f"Mood tone: {soul.mood.tone()}",
        f"Taste verdict on '{topic}': {verdict}",
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
